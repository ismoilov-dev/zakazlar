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
        if target_date is None:
            latest_sale = Sale.objects.order_by("-ordered_at").first()
            if latest_sale and latest_sale.ordered_at:
                now = timezone.localtime(latest_sale.ordered_at)
            else:
                now = timezone.localtime()
        else:
            now = timezone.localtime(target_date)

        return Sale.objects.filter(
            ordered_at__year=now.year,
            ordered_at__month=now.month,
        )

    def get_active_month_str(self) -> str:
        first_sale = Sale.objects.order_by("-ordered_at").first()
        if first_sale and first_sale.ordered_at:
            return timezone.localtime(first_sale.ordered_at).strftime("%m.%Y")
        return timezone.localtime().strftime("%m.%Y")

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

