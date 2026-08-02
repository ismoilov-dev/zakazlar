import logging
import time
from datetime import date

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


    def sync_payroll(self, force: bool = False) -> SyncLog:
        """Fast path: Reads List2 and Guruhlar ONLY. Updates payroll, stats and groups without touching Sale records."""
        last_successful = SyncLog.get_last_successful()

        if not force and cache.get(self.CACHE_KEY):
            if last_successful:
                return last_successful

        if not force:
            cache.set(self.CACHE_KEY, True, timeout=self.CACHE_TTL_SECONDS)

        sync_log = None
        try:
            source = SheetsSource()
            sheet_id = source.sheet_id

            current_modified_time = ""
            try:
                drive_meta = source.client.http_client.get_file_drive_metadata(sheet_id)
                current_modified_time = str(drive_meta.get("modifiedTime", ""))
            except Exception as exc:
                logger.warning("Google Drive metadata olishda xatolik (sheet_id=%s): %s", sheet_id, exc)
                current_modified_time = ""

            if not force and current_modified_time and last_successful and last_successful.sheet_modified_at == current_modified_time:
                return last_successful

            sync_log = SyncLog.objects.create(
                status=SyncStatus.PENDING,
                sheet_modified_at=current_modified_time,
            )

            if self.SHEETS_RECALC_DELAY_SECONDS > 0:
                logger.info("Google Sheets hisob-kitoblari yakunlanishi uchun %s sekund kutilmoqda...", self.SHEETS_RECALC_DELAY_SECONDS)
                time.sleep(self.SHEETS_RECALC_DELAY_SECONDS)

            payroll, group_summaries = source.read_payroll_only()

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
            sync_log.finished_at = timezone.now()
            sync_log.row_count = processed
            sync_log.skipped_rows = skipped_rows
            sync_log.created_sales = 0
            sync_log.updated_sales = 0
            if skipped_rows > 0:
                sync_log.error_text = f"Tashlangan qatorlar: {skipped_rows} ta."
            sync_log.save(update_fields=["status", "finished_at", "row_count", "skipped_rows", "created_sales", "updated_sales", "error_text"])

            return sync_log

        except Exception as exc:
            logger.exception("Google Sheets payroll sync muvaffaqiyatsiz tugadi: %s", exc)
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
            raise ValidationError(f"Google Sheets payroll sync muvaffaqiyatsiz tugadi: {exc}") from exc

    def sync_orders(self, force: bool = False) -> SyncLog:
        """Slow path: Reads List1, resolves modal month, verifies period and writes Sale records."""
        last_successful = SyncLog.get_last_successful()

        sync_log = None
        try:
            source = SheetsSource()
            sheet_id = source.sheet_id

            current_modified_time = ""
            try:
                drive_meta = source.client.http_client.get_file_drive_metadata(sheet_id)
                current_modified_time = str(drive_meta.get("modifiedTime", ""))
            except Exception as exc:
                logger.warning("Google Drive metadata olishda xatolik (sheet_id=%s): %s", sheet_id, exc)
                current_modified_time = ""

            sync_log = SyncLog.objects.create(
                status=SyncStatus.PENDING,
                sheet_modified_at=current_modified_time,
            )

            orders, payroll = source.read()

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
            sync_log.finished_at = timezone.now()
            sync_log.row_count = len(orders)
            sync_log.skipped_rows = skipped_rows
            sync_log.created_sales = created
            sync_log.updated_sales = updated
            if skipped_rows > 0:
                sync_log.error_text = f"Tashlangan qatorlar: {skipped_rows} ta."
            sync_log.save(update_fields=["status", "finished_at", "row_count", "skipped_rows", "created_sales", "updated_sales", "error_text"])

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

