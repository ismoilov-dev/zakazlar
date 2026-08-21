import logging
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.sales.models import Sale, SaleStatus

logger = logging.getLogger(__name__)


class StatisticsRepository:
    """Calculate aggregates in PostgreSQL instead of loading sale rows."""

    def _get_current_month_qs(self, target_date=None):
        calendar_now = timezone.localtime()
        if target_date is None:
            latest_sale = Sale.objects.order_by("-ordered_at").first()
            if latest_sale and latest_sale.ordered_at:
                latest_dt = timezone.localtime(latest_sale.ordered_at)
                months_diff = (latest_dt.year - calendar_now.year) * 12 + (latest_dt.month - calendar_now.month)
                if months_diff > 1:
                    logger.warning(
                        "Bazadagi eng oxirgi zakaz sanasi (%s) kalendar oyidan 1 oydan ortiq kelajakda. Kalendar oyiga qaytildi.",
                        latest_dt.strftime("%d.%m.%Y"),
                    )
                    now = calendar_now
                else:
                    now = latest_dt
            else:
                now = calendar_now
        if target_date is not None:
            from datetime import datetime
            if isinstance(target_date, datetime):
                now = timezone.localtime(target_date)
                target_year, target_month = now.year, now.month
            else:
                target_year, target_month = target_date.year, target_date.month
            return Sale.objects.filter(
                ordered_at__year=target_year,
                ordered_at__month=target_month,
            )

        return Sale.objects.filter(
            ordered_at__year=now.year,
            ordered_at__month=now.month,
        )

    def get_active_month_str(self) -> str:
        calendar_now = timezone.localtime()
        first_sale = Sale.objects.order_by("-ordered_at").first()
        if first_sale and first_sale.ordered_at:
            latest_dt = timezone.localtime(first_sale.ordered_at)
            months_diff = (latest_dt.year - calendar_now.year) * 12 + (latest_dt.month - calendar_now.month)
            if months_diff <= 1:
                return latest_dt.strftime("%m.%Y")
        return calendar_now.strftime("%m.%Y")

    def employee_totals(self, employee_id: int, target_date=None) -> dict[str, object]:
        return self._aggregate(self._get_current_month_qs(target_date).filter(employee_id=employee_id))

    def group_totals(self, group_id: int, target_date=None) -> dict[str, object]:
        return self._aggregate(self._get_current_month_qs(target_date).filter(employee__group_id=group_id))

    def employee_sources(self, employee_id: int, target_date=None) -> list[dict[str, object]]:
        return list(
            self._get_current_month_qs(target_date)
            .filter(employee_id=employee_id)
            .values("source")
            .annotate(
                total_orders=Count("id"),
                successful_orders=Count("id", filter=Q(status=SaleStatus.SUCCESSFUL)),
                cancelled_orders=Count("id", filter=Q(status=SaleStatus.CANCELLED)),
                successful_sales=Coalesce(
                    Sum("sale_amount", filter=Q(status=SaleStatus.SUCCESSFUL)), Decimal("0")
                ),
            )
            .order_by("source")
        )

    @staticmethod
    def _aggregate(queryset: object) -> dict[str, object]:
        return queryset.aggregate(  # type: ignore[union-attr]
            total_orders=Count("id"),
            successful_orders=Count("id", filter=Q(status=SaleStatus.SUCCESSFUL)),
            cancelled_orders=Count("id", filter=Q(status=SaleStatus.CANCELLED)),
            pending_orders=Count("id", filter=Q(status=SaleStatus.PENDING)),
            total_sales=Coalesce(Sum("sale_amount"), Decimal("0")),
            perv_sales=Coalesce(
                Sum("sale_amount", filter=Q(status=SaleStatus.SUCCESSFUL) & ~Q(source__iexact="Baza")),
                Decimal("0"),
            ),
            baza_sales=Coalesce(
                Sum("sale_amount", filter=Q(status=SaleStatus.SUCCESSFUL, source__iexact="Baza")),
                Decimal("0"),
            ),
            otkaz_sales=Coalesce(
                Sum("sale_amount", filter=Q(status=SaleStatus.CANCELLED)), Decimal("0")
            ),
            v_proc_sales=Coalesce(
                Sum("sale_amount", filter=Q(status=SaleStatus.PENDING)), Decimal("0")
            ),
            total_profit=Coalesce(
                Sum("profit_amount", filter=Q(status=SaleStatus.SUCCESSFUL)), Decimal("0")
            ),
        )

