from decimal import Decimal

from django.test import TestCase

from apps.common.services.exceptions import ValidationError
from apps.employees.models import Employee
from apps.groups.models import SalesGroup
from apps.statistics.services.statistics import StatisticsService


class StatisticsMonthFilterTest(TestCase):
    def test_missing_summary_data_raises_validation_error(self) -> None:
        """An employee absent from List2 (empty summary_data) raises explicit ValidationError."""
        group = SalesGroup.objects.create(code="BAZA", name="Baza Group")
        Employee.objects.create(
            employee_id="0191",
            full_name="Amir Karimov",
            group=group,
            monthly_salary=Decimal("5000000.00"),
            summary_data={},
        )

        with self.assertRaises(ValidationError) as ctx:
            StatisticsService().employee_dashboard_for_employee("0191")

        self.assertIn("Ma'lumotlaringiz hali hisoblanmagan", str(ctx.exception))

    def test_statistics_mapped_from_summary_data(self) -> None:
        group = SalesGroup.objects.create(code="BAZA", name="Baza Group")
        Employee.objects.create(
            employee_id="0191",
            full_name="Amir Karimov",
            group=group,
            monthly_salary=Decimal("5000000.00"),
            summary_data={
                "total_sales": "500000.00",
                "successful_sales": "500000.00",
                "perv_sales": "500000.00",
                "baza_sales": "0.00",
                "otkaz_sales": "0.00",
                "v_proc_sales": "0.00",
                "earned_salary": "5000000.00",
                "successful_orders": 1,
            },
        )

        dashboard = StatisticsService().employee_dashboard_for_employee("0191")
        self.assertEqual(dashboard.total_sales, Decimal("500000.00"))
        self.assertEqual(dashboard.earned_salary, Decimal("5000000.00"))
        self.assertEqual(dashboard.successful_orders, 1)

