from datetime import date

from django.core.management import call_command
from django.test import TestCase

from apps.employees.models import Employee, EmployeeMonthlyStat


class BackfillMonthlyStatsTest(TestCase):
    def test_backfill_monthly_stats_creates_and_skips_closed_record(self):
        emp = Employee.objects.create(
            employee_id="0191",
            full_name="Amir Karimov",
            summary_data={"earned_salary": "5000000.00"},
        )

        # Run backfill for 2026-06
        call_command("backfill_monthly_stats", "2026-06")

        stat = EmployeeMonthlyStat.objects.get(employee=emp, period=date(2026, 6, 1))
        self.assertEqual(stat.summary_data["earned_salary"], "5000000.00")
        self.assertEqual(stat.source_spreadsheet_id, "backfill")

        # Close stat
        stat.is_closed = True
        stat.save()

        # Update emp summary_data and run backfill again -> should refuse to overwrite closed stat
        emp.summary_data = {"earned_salary": "9999999.00"}
        emp.save()

        call_command("backfill_monthly_stats", "2026-06")

        stat.refresh_from_db()
        self.assertEqual(stat.summary_data["earned_salary"], "5000000.00")
