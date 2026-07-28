from unittest.mock import MagicMock
from django.test import TestCase

from apps.imports.sources.sheets import SheetsSource


class StableOrderIdTest(TestCase):
    def test_order_id_is_stable_without_row_index(self):
        """Order ID is emp_id_clean_ord and remains identical regardless of row index."""
        raw_data = [
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус"],
            ["1001", "0191", "Amir Karimov", "100,000", "28.07.2026", "успешно"],
        ]

        source = SheetsSource.__new__(SheetsSource)
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = raw_data

        orders = source._parse_orders(mock_worksheet)
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0].order_id, "0191_1001")

    def test_empty_order_number_drops_row(self):
        """Row with empty order number № is dropped into dropped_rows."""
        raw_data = [
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус"],
            ["", "0191", "Amir Karimov", "100,000", "28.07.2026", "успешно"],
        ]

        source = SheetsSource.__new__(SheetsSource)
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = raw_data

        orders = source._parse_orders(mock_worksheet)
        self.assertEqual(len(orders), 0)
        self.assertEqual(source.last_parse_summary["dropped_invalid_id"], 1)
