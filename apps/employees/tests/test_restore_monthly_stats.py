from datetime import date
from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import CommandError, call_command
from django.test import TestCase

from apps.employees.models import Employee, EmployeeMonthlyStat
from apps.imports.dto import PayrollDTO
from apps.imports.models import SpreadsheetPeriod


class RestoreMonthlyStatsTest(TestCase):
    def setUp(self):
        self.emp1 = Employee.objects.create(employee_id="0001", full_name="Amir Karimov")
        self.emp2 = Employee.objects.create(employee_id="0002", full_name="Bekzod Aliyev")

        self.stat_june = EmployeeMonthlyStat.objects.create(
            employee=self.emp1,
            period=date(2026, 6, 1),
            summary_data={"otkaz_sales": "60000000.00"},
            is_closed=False,
        )
        self.stat_june_closed = EmployeeMonthlyStat.objects.create(
            employee=self.emp2,
            period=date(2026, 6, 1),
            summary_data={"otkaz_sales": "10000000.00"},
            is_closed=True,
        )

    def test_missing_period_or_invalid_period_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("restore_monthly_stats", "2026-13", "--spreadsheet-id", "1W8wvi0nmrlnIsrqUBjNjEuoXbkcLQxFCK5fd3v3hto8")

    def test_missing_spreadsheet_id_without_db_record_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("restore_monthly_stats", "2026-05")

    @patch("apps.employees.management.commands.restore_monthly_stats.SheetsSource")
    def test_restore_refuses_closed_row_without_force(self, mock_sheets_source_cls):
        mock_source = mock_sheets_source_cls.return_value
        mock_source.sheet_id = "16rSon1F6rSon1F6rSon1F6rSon1F6rSon1F6rSon1F"

        mock_spreadsheet = MagicMock()
        mock_ws = MagicMock()
        mock_ws.title = "List2"
        mock_spreadsheet.worksheets.return_value = [mock_ws]
        mock_source.client.open_by_key.return_value = mock_spreadsheet

        mock_source._parse_payroll.return_value = [
            PayrollDTO(
                group_code="A",
                employee_id="0001",
                employee_name="Amir Karimov",
                monthly_salary=None,
                summary_data={"otkaz_sales": "52755000.00"},
            ),
            PayrollDTO(
                group_code="A",
                employee_id="0002",
                employee_name="Bekzod Aliyev",
                monthly_salary=None,
                summary_data={"otkaz_sales": "52755000.00"},
            ),
        ]

        out = StringIO()
        call_command("restore_monthly_stats", "2026-06", "--spreadsheet-id", "16rSon1F6rSon1F6rSon1F6rSon1F6rSon1F6rSon1F", stdout=out)

        output_text = out.getvalue()
        self.assertIn("[0001] Amir Karimov:", output_text)
        self.assertIn("otkaz_sales: 60000000.00 -> 52755000.00", output_text)
        self.assertIn("YOPILGAN OY (is_closed=True)", output_text)

        self.stat_june.refresh_from_db()
        self.assertEqual(self.stat_june.summary_data["otkaz_sales"], "52755000.00")

        self.stat_june_closed.refresh_from_db()
        self.assertEqual(self.stat_june_closed.summary_data["otkaz_sales"], "10000000.00")

    @patch("apps.employees.management.commands.restore_monthly_stats.SheetsSource")
    def test_restore_allows_closed_row_with_force_and_targets_only_given_period(self, mock_sheets_source_cls):
        stat_august = EmployeeMonthlyStat.objects.create(
            employee=self.emp1,
            period=date(2026, 8, 1),
            summary_data={"otkaz_sales": "60000000.00"},
        )

        mock_source = mock_sheets_source_cls.return_value
        mock_source.sheet_id = "16rSon1F6rSon1F6rSon1F6rSon1F6rSon1F6rSon1F"

        mock_spreadsheet = MagicMock()
        mock_ws = MagicMock()
        mock_ws.title = "List2"
        mock_spreadsheet.worksheets.return_value = [mock_ws]
        mock_source.client.open_by_key.return_value = mock_spreadsheet

        mock_source._parse_payroll.return_value = [
            PayrollDTO(
                group_code="A",
                employee_id="0002",
                employee_name="Bekzod Aliyev",
                monthly_salary=None,
                summary_data={"otkaz_sales": "52755000.00"},
            )
        ]

        out = StringIO()
        call_command("restore_monthly_stats", "2026-06", "--spreadsheet-id", "16rSon1F6rSon1F6rSon1F6rSon1F6rSon1F6rSon1F", "--force", stdout=out)

        self.stat_june_closed.refresh_from_db()
        self.assertEqual(self.stat_june_closed.summary_data["otkaz_sales"], "52755000.00")

        stat_august.refresh_from_db()
        self.assertEqual(stat_august.summary_data["otkaz_sales"], "60000000.00")
