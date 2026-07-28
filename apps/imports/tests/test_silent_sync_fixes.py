from decimal import Decimal
from unittest.mock import MagicMock
from django.test import TestCase

from apps.common.services.exceptions import ValidationError
from apps.imports.sources.sheets import SheetsSource


class SilentSyncFixesTest(TestCase):
    def test_invalid_decimal_id_does_not_crash_whole_sheet(self):
        """Row with invalid decimal ID '191,0' is logged and skipped, while valid rows are parsed."""
        raw_data = [
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус"],
            ["1", "191,0", "Amir Karimov", "100,000", "28.07.2026", "успешно"],  # Invalid ID
            ["2", "0191", "Amir Karimov", "200,000", "28.07.2026", "успешно"],  # Valid ID
        ]

        source = SheetsSource.__new__(SheetsSource)
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = raw_data

        orders = source._parse_orders(mock_worksheet)
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0].employee_id, "0191")
        self.assertEqual(source.last_parse_summary["dropped_invalid_id"], 1)

    def test_formula_error_id_does_not_crash_whole_sheet(self):
        """Row with formula error ID '#N/A' is logged and skipped, while valid rows are parsed."""
        raw_data = [
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус"],
            ["1", "#N/A", "Amir Karimov", "100,000", "28.07.2026", "успешно"],  # Formula error ID
            ["2", "0191", "Amir Karimov", "200,000", "28.07.2026", "успешно"],  # Valid ID
        ]

        source = SheetsSource.__new__(SheetsSource)
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = raw_data

        orders = source._parse_orders(mock_worksheet)
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0].employee_id, "0191")

    def test_ten_data_rows_yield_exactly_ten_orders(self):
        """A sheet with 10 valid data rows yields exactly 10 OrderDTO objects."""
        raw_data = [
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус"]
        ] + [
            [str(i), "0191", "Amir Karimov", f"{i * 100000}", "28.07.2026", "успешно"]
            for i in range(1, 11)
        ]

        source = SheetsSource.__new__(SheetsSource)
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = raw_data

        orders = source._parse_orders(mock_worksheet)
        self.assertEqual(len(orders), 10)

    def test_forward_fill_ten_row_block_with_id_only_in_first_row(self):
        """A 10-row block with ID only in the first row parses via forward-fill to 10 OrderDTO objects."""
        raw_data = [
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус"],
            ["1", "0191", "Amir Karimov", "100,000", "28.07.2026", "успешно"],
        ] + [
            [str(i), "", "Amir Karimov", f"{i * 100000}", "28.07.2026", "успешно"]
            for i in range(2, 11)
        ]

        source = SheetsSource.__new__(SheetsSource)
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = raw_data

        orders = source._parse_orders(mock_worksheet)
        self.assertEqual(len(orders), 10)
        self.assertTrue(all(o.employee_id == "0191" for o in orders))

    def test_status_mapping_cancellation_substrings(self):
        """Substrings 'отказ клиента' and 'Возврат товара' map correctly to 'cancelled'."""
        source = SheetsSource.__new__(SheetsSource)
        self.assertEqual(source._parse_status("отказ клиента"), "cancelled")
        self.assertEqual(source._parse_status("Возврат товара"), "cancelled")

    def test_unknown_status_drops_row_and_does_not_default_to_successful(self):
        """Unknown status string 'Новый' causes row to be dropped with warning, not defaulted to 'successful'."""
        raw_data = [
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус"],
            ["1", "0191", "Amir Karimov", "100,000", "28.07.2026", "Новый"],  # Unknown status
        ]

        source = SheetsSource.__new__(SheetsSource)
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = raw_data

        orders = source._parse_orders(mock_worksheet)
        self.assertEqual(len(orders), 0)
        self.assertEqual(source.last_parse_summary["dropped_invalid_id"], 1)

    def test_single_bad_row_in_payroll_does_not_crash_whole_payroll_sheet(self):
        """One bad row in payroll worksheet is logged and skipped without breaking valid rows."""
        raw_data = [
            ["ID", "FISH", "Guruhi", "Ish haqi"],
            ["0191", "", "A", "1,000,000"],  # Empty FISH -> ValidationError
            ["0192", "Feruza Boymo'minova", "A", "2,000,000"],  # Valid row
        ]

        source = SheetsSource.__new__(SheetsSource)
        mock_worksheet = MagicMock()
        mock_worksheet.title = "List2"
        mock_worksheet.get_all_values.return_value = raw_data

        payroll = source._parse_payroll(mock_worksheet)
        self.assertEqual(len(payroll), 1)
        self.assertEqual(payroll[0].employee_id, "0192")
