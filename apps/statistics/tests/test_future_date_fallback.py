from datetime import datetime
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone

from apps.employees.models import Employee
from apps.sales.models import Sale, SaleStatus
from apps.statistics.repositories.statistics import StatisticsRepository


class FutureDateFallbackTest(TestCase):
    def test_rogue_future_sale_does_not_zero_out_current_month_statistics(self):
        """Having 9 current month sales and 1 rogue future year sale in DB still returns 9 for employee_totals."""
        employee = Employee.objects.create(employee_id="0191", full_name="Amir Karimov")

        now = timezone.localtime()
        # 9 current month sales
        for i in range(1, 10):
            Sale.objects.create(
                employee=employee,
                external_order_id=f"CURR_{i}",
                sale_amount=Decimal("100000"),
                status=SaleStatus.SUCCESSFUL,
                ordered_at=now,
            )

        # 1 rogue future sale (year 2027)
        future_date = timezone.make_aware(datetime(2027, 7, 1, 10, 0, 0))
        Sale.objects.create(
            employee=employee,
            external_order_id="FUTURE_1",
            sale_amount=Decimal("100000"),
            status=SaleStatus.SUCCESSFUL,
            ordered_at=future_date,
        )

        repo = StatisticsRepository()
        totals = repo.employee_totals(employee.pk)

        # employee_totals should fallback to current calendar month (2026-07) and return 9 orders, not 1
        self.assertEqual(totals["total_orders"], 9)
