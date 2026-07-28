from unittest.mock import MagicMock
from django.test import TestCase

from apps.imports.sources.sheets import SheetsSource


class InvalidDateDropsRowTest(TestCase):
    def test_unparseable_date_drops_row_with_warning(self):
        """Unparseable order date string causes row to be dropped into dropped_rows."""
        raw_data = [
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус", "Источник"],
            ["1001", "0191", "Amir Karimov", "100,000", "INVALID_DATE", "успешно", "Baza"],
        ]

        source = SheetsSource.__new__(SheetsSource)
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = raw_data

        orders = source._parse_orders(mock_worksheet)
        self.assertEqual(len(orders), 0)
        self.assertEqual(source.last_parse_summary["dropped_invalid_id"], 1)
