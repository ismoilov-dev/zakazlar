from decimal import Decimal
from django.test import TestCase
from django.utils import timezone

from apps.employees.models import Employee
from apps.sales.models import Sale, SaleStatus
from apps.statistics.services.statistics import StatisticsService


class TotalOrdersSummaryTest(TestCase):
    def test_total_orders_uses_db_count_when_summary_data_is_present(self):
        """Dashboard should preserve summary_data successful_orders (7)."""
        employee = Employee.objects.create(
            employee_id="0191",
            full_name="Amir Karimov",
            summary_data={
                "successful_orders": 7,
                "total_sales": "1000000",
                "perv_sales": "700000",
                "baza_sales": "0",
                "otkaz_sales": "300000",
                "v_proc_sales": "0",
                "earned_salary": "1000000",
            },
        )

        dashboard = StatisticsService().employee_dashboard_for_employee("0191")
        self.assertEqual(dashboard.successful_orders, 7)
        self.assertEqual(dashboard.total_sales, Decimal("1000000"))

