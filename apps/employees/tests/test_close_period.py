from datetime import date

from django.core.management import call_command
from django.test import TestCase

from apps.employees.models import Employee, EmployeeMonthlyStat


class ClosePeriodTest(TestCase):
    def test_close_period_management_command_is_idempotent(self):
        emp = Employee.objects.create(employee_id="0191", full_name="Amir Karimov")
        stat = EmployeeMonthlyStat.objects.create(
            employee=emp,
            period=date(2026, 6, 1),
            summary_data={"earned_salary": "5000000.00"},
        )

        self.assertFalse(stat.is_closed)

        # Run close_period 2026-06
        call_command("close_period", "2026-06")

        stat.refresh_from_db()
        self.assertTrue(stat.is_closed)
        self.assertIsNotNone(stat.closed_at)

        # Run again (idempotent check)
        call_command("close_period", "2026-06")
        stat.refresh_from_db()
        self.assertTrue(stat.is_closed)
