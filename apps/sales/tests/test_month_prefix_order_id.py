from unittest.mock import MagicMock
from django.test import TestCase

from apps.imports.sources.sheets import SheetsSource


class MonthPrefixOrderIdTest(TestCase):
    def test_same_order_number_in_different_months_creates_two_separate_orders(self):
        """July and August orders with order number '1001' produce distinct YYYYMM-prefixed order_ids."""
        raw_data_july = [
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус", "Источник"],
            ["1001", "0191", "Amir Karimov", "100,000", "28.07.2026", "успешно", "Baza"],
        ]

        raw_data_august = [
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус", "Источник"],
            ["1001", "0191", "Amir Karimov", "200,000", "28.08.2026", "успешно", "Baza"],
        ]

        source = SheetsSource.__new__(SheetsSource)
        mock_ws_july = MagicMock()
        mock_ws_july.get_all_values.return_value = raw_data_july

        orders_july = source._parse_orders(mock_ws_july)

        mock_ws_august = MagicMock()
        mock_ws_august.get_all_values.return_value = raw_data_august

        orders_august = source._parse_orders(mock_ws_august)

        self.assertEqual(len(orders_july), 1)
        self.assertEqual(len(orders_august), 1)
        self.assertEqual(orders_july[0].order_id, "202607_0191_1001")
        self.assertEqual(orders_august[0].order_id, "202608_0191_1001")
        self.assertNotEqual(orders_july[0].order_id, orders_august[0].order_id)
