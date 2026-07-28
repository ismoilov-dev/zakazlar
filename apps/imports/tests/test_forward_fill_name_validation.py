from unittest.mock import MagicMock
from django.test import TestCase

from apps.imports.sources.sheets import SheetsSource


class ForwardFillNameValidationTest(TestCase):
    def test_forward_fill_fails_when_name_does_not_match(self):
        """Forward-fill is rejected and row is dropped if current row name differs from last seen name."""
        raw_data = [
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус", "Источник"],
            ["1", "0191", "Amir Karimov", "100,000", "28.07.2026", "успешно", "Baza"],
            ["2", "", "Feruza Boymo'minova", "200,000", "28.07.2026", "успешно", "Baza"],  # Different name
        ]

        source = SheetsSource.__new__(SheetsSource)
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = raw_data

        orders = source._parse_orders(mock_worksheet)
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0].employee_id, "0191")
        self.assertEqual(source.last_parse_summary["dropped_empty_id"], 1)

    def test_forward_fill_succeeds_when_name_matches(self):
        """Forward-fill succeeds when current row employee name matches last seen employee name."""
        raw_data = [
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус", "Источник"],
            ["1", "0191", "Amir Karimov", "100,000", "28.07.2026", "успешно", "Baza"],
            ["2", "", "Amir Karimov", "200,000", "28.07.2026", "успешно", "Baza"],  # Same name
        ]

        source = SheetsSource.__new__(SheetsSource)
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = raw_data

        orders = source._parse_orders(mock_worksheet)
        self.assertEqual(len(orders), 2)
        self.assertEqual(orders[0].employee_id, "0191")
        self.assertEqual(orders[1].employee_id, "0191")
