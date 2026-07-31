from datetime import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.employees.models import Employee
from apps.sales.models import Sale, SaleStatus
from apps.statistics.repositories.statistics import StatisticsRepository


class CurrentMonthFilteringTest(TestCase):
    def test_statistics_filters_by_current_active_month(self):
        """Only sales from the active month (July 2026) are aggregated, excluding June 2026."""
        employee = Employee.objects.create(employee_id="0191", full_name="Amir Karimov")

        june_date = timezone.make_aware(datetime(2026, 6, 15, 10, 0, 0))
        july_date = timezone.make_aware(datetime(2026, 7, 15, 10, 0, 0))

        # June 2026 sale (100,000)
        Sale.objects.create(
            employee=employee,
            external_order_id="0191_JUNE_1",
            sale_amount=Decimal("100000"),
            status=SaleStatus.SUCCESSFUL,
            ordered_at=june_date,
        )

        # July 2026 sale (200,000)
        Sale.objects.create(
            employee=employee,
            external_order_id="0191_JULY_1",
            sale_amount=Decimal("200000"),
            status=SaleStatus.SUCCESSFUL,
            ordered_at=july_date,
        )

        repo = StatisticsRepository()
        totals = repo.employee_totals(employee.pk)

        # Total orders in July 2026 should be 1 (not 2)
        self.assertEqual(totals["total_orders"], 1)
        self.assertEqual(totals["total_sales"], Decimal("200000"))
