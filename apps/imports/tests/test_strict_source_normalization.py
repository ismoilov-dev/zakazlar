from unittest.mock import MagicMock
from django.test import TestCase

from apps.imports.sources.sheets import SheetsSource


class StrictSourceNormalizationTest(TestCase):
    def test_unknown_source_string_maps_to_unknown(self):
        """Unknown source string 'Instagram' maps to UNKNOWN choice without dropping row."""
        raw_data = [
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус", "Источник"],
            ["1001", "0191", "Amir Karimov", "100,000", "28.07.2026", "успешно", "Instagram"],
        ]

        source = SheetsSource.__new__(SheetsSource)
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = raw_data

        orders = source._parse_orders(mock_worksheet)
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0].source, "UNKNOWN")


    def test_valid_source_strings_normalize_correctly(self):
        """Valid source strings 'Первичный' and 'База' normalize correctly."""
        raw_data = [
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус", "Источник"],
            ["1001", "0191", "Amir Karimov", "100,000", "28.07.2026", "успешно", "Первичный"],
            ["1002", "0191", "Amir Karimov", "200,000", "28.07.2026", "успешно", "База"],
        ]

        source = SheetsSource.__new__(SheetsSource)
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = raw_data

        orders = source._parse_orders(mock_worksheet)
        self.assertEqual(len(orders), 2)
        self.assertEqual(orders[0].source, "Pervichka")
        self.assertEqual(orders[1].source, "Baza")
