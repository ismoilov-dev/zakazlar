import logging
from datetime import date
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.sales.models import Sale, SaleStatus

logger = logging.getLogger(__name__)


def get_active_period_date(target_date=None) -> date:
    """Unified period date resolution for both /shaxsiy and /stats."""
    if target_date is not None:
        from datetime import datetime
        if isinstance(target_date, str):
            parts = target_date.split("-")
            return date(int(parts[0]), int(parts[1]), 1)
        if isinstance(target_date, datetime):
            return target_date.date()
        return target_date

    # 1. Primary choice: active SpreadsheetPeriod
    from apps.imports.models import SpreadsheetPeriod
    active_sp = SpreadsheetPeriod.objects.filter(is_active=True).first()
    if active_sp and active_sp.period:
        return active_sp.period

    # 2. Fallback: latest sale ordered_at date
    first_sale = Sale.objects.order_by("-ordered_at").first()
    if first_sale and first_sale.ordered_at:
        return timezone.localtime(first_sale.ordered_at).date()

    return timezone.localtime().date()


class StatisticsRepository:
    """Calculate aggregates in PostgreSQL instead of loading sale rows."""

    def _get_current_month_qs(self, target_date=None):
        period_dt = get_active_period_date(target_date)
        return Sale.objects.filter(
            ordered_at__year=period_dt.year,
            ordered_at__month=period_dt.month,
        )

    def get_active_month_str(self, target_date=None) -> str:
        period_dt = get_active_period_date(target_date)
        return period_dt.strftime("%m.%Y")

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

    def all_employees_totals_dict(self, target_date=None) -> dict[int, dict[str, object]]:
        """Fetch monthly totals aggregated for all employees in a single SQL query."""
        qs = self._get_current_month_qs(target_date)
        rows = qs.values("employee_id").annotate(
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
        return {r["employee_id"]: r for r in rows if r["employee_id"] is not None}

