import logging
import re
import time
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.common.services.exceptions import ValidationError
from apps.imports.dto import OrderDTO
from apps.imports.models import SyncLog, SyncStatus
from apps.imports.services.importer import DataImporter
from apps.imports.sources.sheets import SheetsSource

logger = logging.getLogger(__name__)

SHEETS_RECALC_DELAY_SECONDS = getattr(settings, "SHEETS_RECALC_DELAY_SECONDS", 3)


def resolve_sync_period(orders: list[OrderDTO]) -> date:
    """Derive period from modal month of successfully parsed List1 orders (top month must be >= 60%)."""
    if not orders:
        raise ValidationError("Sinxronizatsiya davrini aniqlab bo'lmadi: birorta ham buyurtma o'qilmadi.")

    counts: dict[tuple[int, int], int] = {}
    for o in orders:
        if o.ordered_at:
            key = (o.ordered_at.year, o.ordered_at.month)
            counts[key] = counts.get(key, 0) + 1

    if not counts:
        raise ValidationError("Sinxronizatsiya davrini aniqlab bo'lmadi: yaroqli sanaga ega buyurtmalar yo'q.")

    total_valid_orders = sum(counts.values())
    sorted_months = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    (top_year, top_month), top_count = sorted_months[0]

    ratio = top_count / total_valid_orders
    if ratio < 0.60:
        raise ValidationError(
            f"Sync to'xtatildi: Buyurtmalarning aksariyat qismi ({top_count}/{total_valid_orders} = {ratio:.1%}) yagona bir oyga tegishli emas (kamida 60% talab qilinadi)."
        )

    resolved_date = date(top_year, top_month, 1)
    logger.info(
        "Sync davri (modal month) aniqlandi: %s (%s/%s buyurtma, %.1f%%)",
        resolved_date,
        top_count,
        total_valid_orders,
        ratio * 100,
    )
    return resolved_date


class SheetsSyncService:

    """Orchestrates Google Sheets live synchronization with cache and freshness checks."""

    CACHE_KEY = "sheets_sync_recent_lock"
    CACHE_TTL_SECONDS = 10
    STALE_THRESHOLD_SECONDS = 300
    SHEETS_RECALC_DELAY_SECONDS = SHEETS_RECALC_DELAY_SECONDS

    def __init__(self) -> None:
        self.importer = DataImporter()

    @classmethod
    def clear_cache_lock(cls) -> None:
        """Clear cache lock so next sync_if_needed executes immediately."""
        cache.delete(cls.CACHE_KEY)

    def _get_drive_modified_time(self, source: SheetsSource, sheet_id: str) -> str:
        cache_key = f"drive_modified_time_{sheet_id}"
        cached_val = cache.get(cache_key)
        if cached_val is not None:
            return str(cached_val)

        try:
            drive_meta = source.client.http_client.get_file_drive_metadata(sheet_id)
            current_modified_time = str(drive_meta.get("modifiedTime", ""))
            if current_modified_time:
                cache.set(cache_key, current_modified_time, timeout=5)
            return current_modified_time
        except Exception as exc:
            logger.warning("Google Drive metadata olishda xatolik (sheet_id=%s): %s", sheet_id, exc)
            return ""

    def sync_payroll(self, force: bool = False) -> SyncLog:
        """Fast path: Reads List2 and Guruhlar ONLY. Updates payroll, stats and groups without touching Sale records."""
        last_successful = SyncLog.get_last_successful(sync_type="payroll")

        if not force and cache.get(self.CACHE_KEY):
            if last_successful:
                return last_successful

        if not force:
            cache.set(self.CACHE_KEY, True, timeout=self.CACHE_TTL_SECONDS)

        sync_log = None
        try:
            source = SheetsSource()
            sheet_id = source.sheet_id

            current_modified_time = self._get_drive_modified_time(source, sheet_id)

            if not force and current_modified_time and last_successful and last_successful.sheet_modified_at == current_modified_time:
                logger.info("Drive modified_time (%s) o'zgarmagan, short-circuit success log yaratilmoqda.", current_modified_time)
                return SyncLog.objects.create(
                    status=SyncStatus.SUCCESS,
                    sync_type="payroll",
                    finished_at=timezone.now(),
                    sheet_modified_at=current_modified_time,
                    payroll_hash=last_successful.payroll_hash,
                    orders_hash=last_successful.orders_hash,
                    row_count=0,
                    unchanged=True,
                )

            sync_log = SyncLog.objects.create(
                status=SyncStatus.PENDING,
                sync_type="payroll",
                sheet_modified_at=current_modified_time,
            )

            recalc_delay = getattr(settings, "SHEETS_RECALC_DELAY_SECONDS", 0)
            last_webhook = cache.get("sheet_webhook_last_call_timestamp")
            should_sleep = False
            if recalc_delay > 0 and last_webhook:
                try:
                    if (time.time() - float(last_webhook)) < 10.0:
                        should_sleep = True
                except (TypeError, ValueError):
                    pass

            if should_sleep:
                logger.info("Google Sheets hisob-kitoblari yakunlanishi uchun %s sekund kutilmoqda...", recalc_delay)
                time.sleep(recalc_delay)

            payroll, group_summaries = source.read_payroll_only()
            payroll_hash_val = getattr(source, "last_payroll_hash", "")
            payroll_hash = str(payroll_hash_val) if isinstance(payroll_hash_val, str) else ""

            last_payroll_log = SyncLog.get_last_successful(sync_type="payroll")
            if not force and payroll_hash and last_payroll_log and last_payroll_log.payroll_hash == payroll_hash:
                logger.info("Payroll hash (%s) o'zgarmagan, DB yozuvlari o'tkazib yuborildi.", payroll_hash)
                sync_log.status = SyncStatus.SUCCESS
                sync_log.sync_type = "payroll"
                sync_log.payroll_hash = payroll_hash
                sync_log.finished_at = timezone.now()
                sync_log.row_count = 0
                sync_log.skipped_rows = 0
                sync_log.created_sales = 0
                sync_log.updated_sales = 0
                sync_log.unchanged = True
                sync_log.save(
                    update_fields=[
                        "status",
                        "sync_type",
                        "payroll_hash",
                        "finished_at",
                        "row_count",
                        "skipped_rows",
                        "created_sales",
                        "updated_sales",
                        "unchanged",
                    ]
                )
                return sync_log

            skipped_rows = len(getattr(source, "last_dropped_payroll_rows", []))
            total_rows = len(payroll) + skipped_rows

            from apps.imports.sources.sheets import MAX_SKIPPED_ROWS_RATIO_THRESHOLD

            if total_rows > 0 and (skipped_rows / total_rows) > MAX_SKIPPED_ROWS_RATIO_THRESHOLD:
                raise ValidationError(
                    f"Tashlangan qatorlar ulushi ({skipped_rows}/{total_rows}) ruxsat etilgan {MAX_SKIPPED_ROWS_RATIO_THRESHOLD * 100:.1f}% me'yordan oshdi."
                )

            from apps.imports.models import SpreadsheetPeriod
            active_sp = SpreadsheetPeriod.objects.filter(is_active=True).first()
            if active_sp:
                period = active_sp.period
            else:
                period = date(timezone.now().year, timezone.now().month, 1)

            with transaction.atomic():
                processed = self.importer.import_payroll_only(
                    payroll=payroll,
                    group_summaries=group_summaries,
                    period=period,
                    sheet_id=getattr(source, "sheet_id", ""),
                )

            sync_log.status = SyncStatus.SUCCESS
            sync_log.sync_type = "payroll"
            sync_log.payroll_hash = payroll_hash
            sync_log.finished_at = timezone.now()
            sync_log.row_count = processed
            sync_log.skipped_rows = skipped_rows
            sync_log.created_sales = 0
            sync_log.updated_sales = 0
            sync_log.unchanged = False
            if skipped_rows > 0:
                sync_log.error_text = f"Tashlangan qatorlar: {skipped_rows} ta."
            sync_log.save(
                update_fields=[
                    "status",
                    "sync_type",
                    "payroll_hash",
                    "finished_at",
                    "row_count",
                    "skipped_rows",
                    "created_sales",
                    "updated_sales",
                    "unchanged",
                    "error_text",
                ]
            )

            return sync_log

        except Exception as exc:
            logger.exception("Google Sheets payroll sync muvaffaqiyatsiz tugadi: %s", exc)
            if sync_log is not None:
                sync_log.status = SyncStatus.FAILED
                sync_log.sync_type = "payroll"
                sync_log.finished_at = timezone.now()
                sync_log.error_text = str(exc)[:1000]
                sync_log.save(update_fields=["status", "sync_type", "finished_at", "error_text"])
            else:
                sync_log = SyncLog.objects.create(
                    status=SyncStatus.FAILED,
                    sync_type="payroll",
                    finished_at=timezone.now(),
                    error_text=str(exc)[:1000],
                )

            if last_successful:
                return last_successful
            raise ValidationError(f"Google Sheets payroll sync muvaffaqiyatsiz tugadi: {exc}") from exc

    def sync_orders(self, force: bool = False) -> SyncLog:
        """Slow path: Reads List1, resolves modal month, verifies period and writes Sale records."""
        last_successful = SyncLog.get_last_successful(sync_type="orders")

        sync_log = None
        try:
            source = SheetsSource()
            sheet_id = source.sheet_id

            current_modified_time = self._get_drive_modified_time(source, sheet_id)

            if not force and current_modified_time and last_successful and last_successful.sheet_modified_at == current_modified_time:
                logger.info("Drive modified_time (%s) o'zgarmagan, short-circuit success log yaratilmoqda.", current_modified_time)
                return SyncLog.objects.create(
                    status=SyncStatus.SUCCESS,
                    sync_type="orders",
                    finished_at=timezone.now(),
                    sheet_modified_at=current_modified_time,
                    payroll_hash=last_successful.payroll_hash,
                    orders_hash=last_successful.orders_hash,
                    row_count=0,
                    unchanged=True,
                )

            sync_log = SyncLog.objects.create(
                status=SyncStatus.PENDING,
                sync_type="orders",
                sheet_modified_at=current_modified_time,
            )

            orders, payroll = source.read()
            orders_hash_val = getattr(source, "last_orders_hash", "")
            orders_hash = str(orders_hash_val) if isinstance(orders_hash_val, str) else ""

            last_orders_log = SyncLog.get_last_successful(sync_type="orders")
            if not force and orders_hash and last_orders_log and last_orders_log.orders_hash == orders_hash:
                logger.info("Orders hash (%s) o'zgarmagan, DB yozuvlari o'tkazib yuborildi.", orders_hash)
                sync_log.status = SyncStatus.SUCCESS
                sync_log.sync_type = "orders"
                sync_log.orders_hash = orders_hash
                sync_log.finished_at = timezone.now()
                sync_log.row_count = 0
                sync_log.skipped_rows = 0
                sync_log.created_sales = 0
                sync_log.updated_sales = 0
                sync_log.unchanged = True
                sync_log.save(
                    update_fields=[
                        "status",
                        "sync_type",
                        "orders_hash",
                        "finished_at",
                        "row_count",
                        "skipped_rows",
                        "created_sales",
                        "updated_sales",
                        "unchanged",
                    ]
                )
                return sync_log

            skipped_rows = len(getattr(source, "last_dropped_rows", []))
            total_rows = len(orders) + skipped_rows

            from apps.imports.sources.sheets import MAX_SKIPPED_ROWS_RATIO_THRESHOLD

            if total_rows > 0 and (skipped_rows / total_rows) > MAX_SKIPPED_ROWS_RATIO_THRESHOLD:
                raise ValidationError(
                    f"Tashlangan qatorlar ulushi ({skipped_rows}/{total_rows}) ruxsat etilgan {MAX_SKIPPED_ROWS_RATIO_THRESHOLD * 100:.1f}% me'yordan oshdi."
                )

            period = resolve_sync_period(orders)

            from apps.imports.models import SpreadsheetPeriod
            active_period = SpreadsheetPeriod.objects.filter(is_active=True).first()
            if active_period:
                active_period_str = active_period.period.strftime("%Y-%m")
                data_modal_month = period.strftime("%Y-%m")
                if active_period_str != data_modal_month:
                    err_msg = f"Active SpreadsheetPeriod ({active_period_str}) does not match sheet data modal month ({data_modal_month}). Sync aborted."
                    logger.error(
                        "Active SpreadsheetPeriod (%s) does not match sheet data modal month (%s). Sync aborted.",
                        active_period_str,
                        data_modal_month,
                    )
                    raise ValidationError(err_msg)

            with transaction.atomic():
                created, updated = self.importer.import_orders_only(
                    orders=orders,
                    period=period,
                )

            sync_log.status = SyncStatus.SUCCESS
            sync_log.sync_type = "orders"
            sync_log.orders_hash = orders_hash
            sync_log.finished_at = timezone.now()
            sync_log.row_count = len(orders)
            sync_log.skipped_rows = skipped_rows
            sync_log.created_sales = created
            sync_log.updated_sales = updated
            sync_log.unchanged = False
            total_sales_sum = sum(o.sale_amount or Decimal("0") for o in orders)
            dropped_list = getattr(source, "last_dropped_rows", [])
            unrecognized_statuses = getattr(source, "last_unrecognized_statuses", {})
            unrecognized_statuses_sum = getattr(source, "last_unrecognized_statuses_sum", Decimal("0"))
            duplicate_orders_count = getattr(source, "last_duplicate_orders_count", 0)
            duplicate_orders_sum = getattr(source, "last_duplicate_orders_sum", Decimal("0"))

            column_map = getattr(source, "last_column_indexes", {})
            amt_idx = column_map.get("Сумма")
            dropped_sum = Decimal("0")
            unlisted_ids = set()
            for item in dropped_list:
                r_data = item.get("row_data", [])
                reason = str(item.get("reason", ""))
                if "List2" in reason or "topilmadi" in reason:
                    m = re.search(r"\((\d+)\)", reason)
                    if m:
                        unlisted_ids.add(m.group(1))
                if amt_idx is not None and amt_idx < len(r_data):
                    amt_str = str(r_data[amt_idx] or "").strip()
                    if amt_str and not source._is_sheet_error(amt_str):
                        try:
                            dropped_sum += source._parse_money(amt_str)
                        except Exception:
                            pass

            log_messages = []
            if skipped_rows > 0:
                unlisted_str = f" Topilmagan xodim ID lar: {', '.join(sorted(unlisted_ids))}." if unlisted_ids else ""
                log_messages.append(f"Tashlangan qatorlar: {skipped_rows} ta. Yo'qotilgan summa: {dropped_sum:,.0f} so'm.{unlisted_str}")
            if unrecognized_statuses:
                stat_items = [f"'{k}': {v} ta" for k, v in unrecognized_statuses.items()]
                log_messages.append(f"Noma'lum status matnlari: {', '.join(stat_items)} (Summa: {unrecognized_statuses_sum:,.0f} so'm).")
            if duplicate_orders_count > 0:
                log_messages.append(f"Dublikat № zakazlar: {duplicate_orders_count} ta (Summa: {duplicate_orders_sum:,.0f} so'm).")

            if log_messages:
                sync_log.error_text = "\n".join(log_messages)

            total_issue_sum = dropped_sum + unrecognized_statuses_sum
            if total_sales_sum > Decimal("0") and (total_issue_sum / total_sales_sum) > Decimal("0.01"):
                sync_log.status = SyncStatus.WARNING
                total_issue_count = skipped_rows + sum(unrecognized_statuses.values())
                warning_hdr = f"{total_issue_count} ta zakaz noma'lum status sababli hisobga olinmadi ({total_issue_sum:,.0f} so'm)."
                sync_log.error_text = f"WARNING: {warning_hdr}\n" + (sync_log.error_text or "")

            sync_log.save(
                update_fields=[
                    "status",
                    "sync_type",
                    "orders_hash",
                    "finished_at",
                    "row_count",
                    "skipped_rows",
                    "created_sales",
                    "updated_sales",
                    "unchanged",
                    "error_text",
                ]
            )

            return sync_log

        except Exception as exc:
            logger.exception("Google Sheets orders sync muvaffaqiyatsiz tugadi: %s", exc)
            if sync_log is not None:
                sync_log.status = SyncStatus.FAILED
                sync_log.finished_at = timezone.now()
                sync_log.error_text = str(exc)[:1000]
                sync_log.save(update_fields=["status", "finished_at", "error_text"])
            else:
                sync_log = SyncLog.objects.create(
                    status=SyncStatus.FAILED,
                    finished_at=timezone.now(),
                    error_text=str(exc)[:1000],
                )

            if last_successful:
                return last_successful
            raise ValidationError(f"Google Sheets orders sync muvaffaqiyatsiz tugadi: {exc}") from exc

    def sync_if_needed(self, force: bool = False, allow_period_mismatch: bool = False) -> SyncLog:
        """Fast path entrypoint for bot requests."""
        return self.sync_payroll(force=force)

