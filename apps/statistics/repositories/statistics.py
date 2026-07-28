import logging
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.sales.models import Sale, SaleStatus

logger = logging.getLogger(__name__)


class StatisticsRepository:
    """Calculate aggregates in PostgreSQL instead of loading sale rows."""

    def _get_current_month_qs(self):
        now = timezone.localtime()
        return Sale.objects.filter(ordered_at__year=now.year, ordered_at__month=now.month)

    def employee_totals(self, employee_id: int) -> dict[str, object]:
        return self._aggregate(self._get_current_month_qs().filter(employee_id=employee_id))

    def group_totals(self, group_id: int) -> dict[str, object]:
        return self._aggregate(self._get_current_month_qs().filter(employee__group_id=group_id))

    def employee_sources(self, employee_id: int) -> list[dict[str, object]]:
        return list(
            self._get_current_month_qs()
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

