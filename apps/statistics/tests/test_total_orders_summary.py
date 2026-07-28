from decimal import Decimal
from django.test import TestCase
from django.utils import timezone

from apps.employees.models import Employee
from apps.sales.models import Sale, SaleStatus
from apps.statistics.services.statistics import StatisticsService


class TotalOrdersSummaryTest(TestCase):
    def test_total_orders_uses_db_count_when_summary_data_is_present(self):
        """Dashboard should use DB total_orders (10) while preserving summary_data successful_orders (7)."""
        employee = Employee.objects.create(
            employee_id="0191",
            full_name="Amir Karimov",
            summary_data={"successful_orders": 7, "total_sales": "1000000"},
        )

        for i in range(10):
            Sale.objects.create(
                employee=employee,
                external_order_id=f"ORD-{i}",
                sale_amount=Decimal("100000"),
                status=SaleStatus.SUCCESSFUL if i < 7 else SaleStatus.CANCELLED,
                ordered_at=timezone.now(),
            )

        dashboard = StatisticsService().employee_dashboard_for_employee("0191")
        self.assertEqual(dashboard.total_orders, 10)
        self.assertEqual(dashboard.successful_orders, 7)
