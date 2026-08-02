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

    def test_closed_row_rejects_upsert_from_repository_and_importer(self):
        from apps.employees.repositories.monthly_stat import ClosedPeriodError, EmployeeMonthlyStatRepository
        from apps.imports.dto import PayrollDTO
        from apps.imports.services.importer import DataImporter

        emp = Employee.objects.create(employee_id="0001", full_name="Test Employee")
        stat = EmployeeMonthlyStat.objects.create(
            employee=emp,
            period=date(2026, 6, 1),
            summary_data={"otkaz_sales": "52755000.00"},
            is_closed=True,
        )

        repo = EmployeeMonthlyStatRepository()
        with self.assertRaises(ClosedPeriodError):
            repo.upsert_snapshot(
                employee=emp,
                period=date(2026, 6, 1),
                summary_data={"otkaz_sales": "60000000.00"},
                force=False,
            )

        stat.refresh_from_db()
        self.assertEqual(stat.summary_data["otkaz_sales"], "52755000.00")

        importer = DataImporter()
        from apps.imports.models import SpreadsheetPeriod
        SpreadsheetPeriod.objects.all().delete()
        SpreadsheetPeriod.objects.create(
            period=date(2026, 6, 1),
            spreadsheet_id="16rSon1F6rSon1F6rSon1F6rSon1F6rSon1F6rSon1F",
            is_active=True,
        )
        importer.import_dto_lists(
            orders=[],
            payroll=[
                PayrollDTO(
                    group_code="A",
                    employee_id="0001",
                    employee_name="Test Employee",
                    monthly_salary=None,
                    summary_data={"otkaz_sales": "60000000.00"},
                )
            ],
            period=date(2026, 6, 1),
        )

        stat.refresh_from_db()
        self.assertEqual(stat.summary_data["otkaz_sales"], "52755000.00")

    def test_repository_allows_forced_upsert_on_closed_row(self):
        from apps.employees.repositories.monthly_stat import EmployeeMonthlyStatRepository

        emp = Employee.objects.create(employee_id="0002", full_name="Test Employee 2")
        stat = EmployeeMonthlyStat.objects.create(
            employee=emp,
            period=date(2026, 6, 1),
            summary_data={"otkaz_sales": "52755000.00"},
            is_closed=True,
        )

        repo = EmployeeMonthlyStatRepository()
        updated_stat, created = repo.upsert_snapshot(
            employee=emp,
            period=date(2026, 6, 1),
            summary_data={"otkaz_sales": "52755000.00", "restored": True},
            force=True,
        )

        self.assertFalse(created)
        self.assertTrue(updated_stat.summary_data.get("restored"))
