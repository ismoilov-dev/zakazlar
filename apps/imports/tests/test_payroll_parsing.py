from unittest.mock import MagicMock

from django.core.exceptions import ValidationError
from django.test import TestCase

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

    def test_failed_payroll_rows_recorded_in_last_dropped_payroll_rows(self) -> None:
        source = SheetsSource.__new__(SheetsSource)
        source.last_dropped_payroll_rows = []

        mock_ws = MagicMock()
        mock_ws.title = "List2"
        mock_ws.get_all_values.return_value = [
            ["Guruh", "Tabel raqami", "FISH", "Oylik ish haqi"],
            ["A", "0191", "Amir Karimov", "5000000"],
            ["A", "0192", "Sardor", "faqa"],  # Invalid money string "faqa" -> parse failure
        ]



        parsed = source._parse_payroll(mock_ws)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(len(source.last_dropped_payroll_rows), 1)
        dropped_item = source.last_dropped_payroll_rows[0]
        self.assertEqual(dropped_item["sheet_title"], "List2")
        self.assertEqual(dropped_item["row_idx"], 3)
        self.assertIn("Noto'g'ri pul summasi formati", dropped_item["reason"])

