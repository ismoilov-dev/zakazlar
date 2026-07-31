from unittest.mock import MagicMock

from django.test import TestCase

from apps.imports.sources.sheets import SheetsSource


class MonthPrefixOrderIdTest(TestCase):
    def test_same_order_number_in_different_months_creates_two_separate_orders(self):
        """June and July orders with order number '1001' produce distinct YYYYMM-prefixed order_ids."""
        raw_data_june = [
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус", "Источник"],
            ["1001", "0191", "Amir Karimov", "100,000", "28.06.2026", "успешно", "Baza"],
        ]

        raw_data_july2 = [
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус", "Источник"],
            ["1001", "0191", "Amir Karimov", "200,000", "28.07.2026", "успешно", "Baza"],
        ]

        source = SheetsSource.__new__(SheetsSource)
        mock_ws_june = MagicMock()
        mock_ws_june.get_all_values.return_value = raw_data_june

        orders_june = source._parse_orders(mock_ws_june)

        mock_ws_july2 = MagicMock()
        mock_ws_july2.get_all_values.return_value = raw_data_july2

        orders_july2 = source._parse_orders(mock_ws_july2)

        self.assertEqual(len(orders_june), 1)
        self.assertEqual(len(orders_july2), 1)
        self.assertEqual(orders_june[0].order_id, "202606_0191_1001")
        self.assertEqual(orders_july2[0].order_id, "202607_0191_1001")
        self.assertNotEqual(orders_june[0].order_id, orders_july2[0].order_id)