from unittest.mock import MagicMock
from django.test import TestCase

from django.core.exceptions import ValidationError
from apps.imports.sources.sheets import SheetsSource


class PayrollParsingTest(TestCase):
    def test_all_payroll_sheets_failed_raises_error_and_logs(self) -> None:
        mock_spreadsheet = MagicMock()
        ws_orders = MagicMock()
        ws_orders.title = "List1"
        ws_orders.get_all_values.return_value = [
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус", "Источник", " "],
            ["101", "0191", "Test User", "10000", "01.07.2026", "успешно", "Baza", "A"]
        ]

        ws_payroll = MagicMock()
        ws_payroll.title = "Xodimlar maoshi"
        # Return bad headers with missing ID
        ws_payroll.get_all_values.return_value = [
            ["Bad Header 1", "Bad Header 2"]
        ]

        mock_spreadsheet.worksheets.return_value = [ws_orders, ws_payroll]

        source = SheetsSource.__new__(SheetsSource)
        source.sheet_id = "test_id"
        source.client = MagicMock()
        source.client.open_by_key.return_value = mock_spreadsheet

        with self.assertLogs("apps.imports.sources.sheets", level="WARNING") as cm:
            with self.assertRaises(ValidationError) as exc_cm:
                source.read()

            self.assertIn("Birorta ham payroll varog'ini tahlil qilib bo'lmadi", str(exc_cm.exception))
            self.assertTrue(any("Xodimlar maoshi" in log for log in cm.output))
