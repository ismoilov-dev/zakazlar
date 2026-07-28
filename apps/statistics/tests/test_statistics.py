from decimal import Decimal
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone

from apps.employees.models import Employee
from apps.groups.models import SalesGroup
from apps.sales.models import Sale, SaleStatus
from apps.statistics.services.statistics import StatisticsService


class StatisticsMonthFilterTest(TestCase):
    def test_statistics_filtered_by_current_month(self) -> None:
        group = SalesGroup.objects.create(code="BAZA", name="Baza Group")
        employee = Employee.objects.create(
            employee_id="0191",
            full_name="Amir Karimov",
            group=group,
            monthly_salary=Decimal("5000000.00"),
        )

        now = timezone.localtime()
        # Last month date
        first_of_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_month_date = first_of_this_month - timedelta(days=5)

        # Sale 1: last month
        Sale.objects.create(
            external_order_id="ORD-PREV-MONTH",
            employee=employee,
            status=SaleStatus.SUCCESSFUL,
            source="Pervichka",
            sale_amount=Decimal("1000000.00"),
            profit_amount=Decimal("0"),
            ordered_at=last_month_date,
        )

        # Sale 2: current month
        Sale.objects.create(
            external_order_id="ORD-CURR-MONTH",
            employee=employee,
            status=SaleStatus.SUCCESSFUL,
            source="Pervichka",
            sale_amount=Decimal("500000.00"),
            profit_amount=Decimal("0"),
            ordered_at=now,
        )

        dashboard = StatisticsService().employee_dashboard_for_employee("0191")

        # Total orders should only be 1 (current month)
        self.assertEqual(dashboard.total_orders, 1)
        self.assertEqual(dashboard.total_sales, Decimal("500000.00"))
        # Earned salary: 12% of 500,000 = 60,000
        self.assertEqual(dashboard.earned_salary, Decimal("60000.00"))
