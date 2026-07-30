from datetime import date
from decimal import Decimal
from django.test import TestCase

from apps.employees.models import Employee, EmployeeMonthlyStat
from apps.imports.dto import PayrollDTO
from apps.imports.services.importer import DataImporter


class ImportMonthlyStatSnapshotTest(TestCase):
    def test_import_dto_lists_creates_and_updates_monthly_stat_respecting_closed_flag(self):
        importer = DataImporter()
        period = date(2026, 6, 1)

        payroll = [
            PayrollDTO(
                employee_id="0191",
                employee_name="Amir Karimov",
                group_code="A",
                monthly_salary=Decimal("5000000.00"),
                summary_data={"earned_salary": "5000000.00", "total_sales": "1000000.00"},
            )
        ]

        # First import -> creates EmployeeMonthlyStat
        importer.import_dto_lists(orders=[], payroll=payroll, period=period, sheet_id="sheet1")

        emp = Employee.objects.get(employee_id="0191")
        stat = EmployeeMonthlyStat.objects.get(employee=emp, period=period)
        self.assertEqual(stat.summary_data["earned_salary"], "5000000.00")
        self.assertEqual(stat.source_spreadsheet_id, "sheet1")

        # Second import -> updates summary_data if not closed
        payroll_updated = [
            PayrollDTO(
                employee_id="0191",
                employee_name="Amir Karimov",
                group_code="A",
                monthly_salary=Decimal("6000000.00"),
                summary_data={"earned_salary": "6000000.00", "total_sales": "2000000.00"},
            )
        ]
        importer.import_dto_lists(orders=[], payroll=payroll_updated, period=period, sheet_id="sheet2")
        stat.refresh_from_db()
        self.assertEqual(stat.summary_data["earned_salary"], "6000000.00")
        self.assertEqual(stat.source_spreadsheet_id, "sheet2")

        # Mark closed -> subsequent import MUST NOT overwrite
        stat.is_closed = True
        stat.save()

        payroll_after_closed = [
            PayrollDTO(
                employee_id="0191",
                employee_name="Amir Karimov",
                group_code="A",
                monthly_salary=Decimal("7000000.00"),
                summary_data={"earned_salary": "7000000.00", "total_sales": "3000000.00"},
            )
        ]
        importer.import_dto_lists(orders=[], payroll=payroll_after_closed, period=period, sheet_id="sheet3")
        stat.refresh_from_db()

        # Should remain 6000000.00 (from sheet2) because it was closed
        self.assertEqual(stat.summary_data["earned_salary"], "6000000.00")
        self.assertEqual(stat.source_spreadsheet_id, "sheet2")
