from decimal import Decimal
from unittest.mock import MagicMock

from django.test import TestCase

from apps.imports.sources.sheets import SheetsSource


class SilentSyncFixesTest(TestCase):
    def test_invalid_decimal_id_does_not_crash_whole_sheet(self):
        """Row with invalid decimal ID '191,0' is logged and skipped, while valid rows are parsed."""
        raw_data = [
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус", "Источник"],
            ["1", "191,0", "Amir Karimov", "100,000", "28.07.2026", "успешно", "Baza"],  # Invalid ID
            ["2", "0191", "Amir Karimov", "200,000", "28.07.2026", "успешно", "Baza"],  # Valid ID
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
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус", "Источник"],
            ["1", "#N/A", "Amir Karimov", "100,000", "28.07.2026", "успешно", "Baza"],  # Formula error ID
            ["2", "0191", "Amir Karimov", "200,000", "28.07.2026", "успешно", "Baza"],  # Valid ID
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
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус", "Источник"]
        ] + [
            [str(i), "0191", "Amir Karimov", f"{i * 100000}", "28.07.2026", "успешно", "Baza"]
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
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус", "Источник"],
            ["1", "0191", "Amir Karimov", "100,000", "28.07.2026", "успешно", "Baza"],
        ] + [
            [str(i), "", "Amir Karimov", f"{i * 100000}", "28.07.2026", "успешно", "Baza"]
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
        self.assertEqual(source._parse_status("отказ клиента"), ("cancelled", False))
        self.assertEqual(source._parse_status("Возврат товара"), ("cancelled", False))

    def test_unknown_status_saved_as_pending_and_tracked(self):
        """Unknown status string 'Новый' causes row to be saved as 'pending' with is_unrecognized=True and tracked."""
        raw_data = [
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус", "Источник"],
            ["1", "0191", "Amir Karimov", "100,000", "28.07.2026", "Новый"],  # Unknown status
        ]

        source = SheetsSource.__new__(SheetsSource)
        source.last_unrecognized_statuses = {}
        source.last_unrecognized_statuses_sum = Decimal("0")
        source.last_duplicate_orders_count = 0
        source.last_duplicate_orders_sum = Decimal("0")

        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = raw_data

        orders = source._parse_orders(mock_worksheet)
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0].status, "pending")
        self.assertEqual(source.last_unrecognized_statuses.get("Новый"), 1)

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

    def test_courier_status_parses_as_successful_and_fixture_aggregation(self):
        """Courier status strings map to 'successful', 'В процесс' stays 'pending', 'Отказ' stays 'cancelled'."""
        source = SheetsSource.__new__(SheetsSource)
        self.assertEqual(source._parse_status("У курьера"), ("successful", False))
        self.assertEqual(source._parse_status("курьер"), ("successful", False))
        self.assertEqual(source._parse_status("kuryerda"), ("successful", False))
        self.assertEqual(source._parse_status("В процесс"), ("pending", False))
        self.assertEqual(source._parse_status("Отказ"), ("cancelled", False))

        raw_data = [
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус", "Источник"],
            ["1", "0191", "Amir Karimov", "100000", "28.07.2026", "Успешно", "Baza"],
            ["2", "0191", "Amir Karimov", "100000", "28.07.2026", "Успешно", "Baza"],
            ["3", "0191", "Amir Karimov", "100000", "28.07.2026", "Успешно", "Baza"],
            ["4", "0191", "Amir Karimov", "100000", "28.07.2026", "У курьера", "Baza"],
            ["5", "0191", "Amir Karimov", "100000", "28.07.2026", "У курьера", "Baza"],
        ]
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = raw_data

        orders = source._parse_orders(mock_worksheet)
        self.assertEqual(len(orders), 5)
        successful_count = sum(1 for o in orders if o.status == "successful")
        self.assertEqual(successful_count, 5)

    def test_id_structural_fallback_when_header_is_blank(self):
        """When ID header is blank (''), column immediately before 'Ответственный' is validated and used."""
        raw_data = [
            ["№", "Ф.И.О.", "Сумма", "статус", "Дата Заказа", "Источник", "", "Ответственный", "Bo'lim"],
            ["1", "Maqsuda", "100000", "Успешно", "01.08.2026", "Baza", "0191", "Amir Karimov", "A"],
            ["2", "Maqsuda 2", "200000", "Успешно", "01.08.2026", "Baza", "0192", "Sardor", "A"],
        ]
        source = SheetsSource.__new__(SheetsSource)
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = raw_data

        with self.assertLogs("apps.imports.sources.sheets", level="WARNING") as cm:
            orders = source._parse_orders(mock_worksheet)
            self.assertEqual(len(orders), 2)
            self.assertEqual(orders[0].employee_id, "0191")
            self.assertEqual(orders[1].employee_id, "0192")
            self.assertTrue(any("Strukturaviy fallback" in log for log in cm.output))

    def test_id_structural_fallback_fails_validation_when_data_is_not_digit_id(self):
        """When fallback column contains non-digit values (e.g. names), validation fails and raises ValidationError."""
        raw_data = [
            ["", "", "№", "Ф.И.О.", "Контактный номер", "Дата Заказа", "Источник", "Amir Karimov", "Ответственный", "Булим", "Товар1"],
            ["", "", "1", "Maqsuda", "123456789", "01.08.2026", "Baza", "Amir Karimov", "Amir Karimov", "A", "Bioflex"],
        ]
        source = SheetsSource.__new__(SheetsSource)
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = raw_data

        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError) as exc:
            source._parse_orders(mock_worksheet)
        self.assertIn("Ustun topilmadi ('ID')", str(exc.exception))

    def test_proper_id_header_uses_exact_matching_without_fallback(self):
        """A workbook with explicit 'ID' header resolves via exact match without calling fallback."""
        raw_data = [
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус", "Источник"],
            ["1", "0191", "Amir Karimov", "100000", "28.07.2026", "Успешно", "Baza"],
        ]
        source = SheetsSource.__new__(SheetsSource)
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = raw_data

        with self.assertLogs("apps.imports.sources.sheets", level="INFO") as cm:
            orders = source._parse_orders(mock_worksheet)
            self.assertEqual(len(orders), 1)
            self.assertEqual(orders[0].employee_id, "0191")
            self.assertTrue(any("Sheet ustun topildi ('ID'): indeks 1 ('ID')" in log for log in cm.output))
            self.assertFalse(any("Strukturaviy fallback" in log for log in cm.output))
