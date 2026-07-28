from unittest.mock import MagicMock
from django.test import TestCase
from django.core.exceptions import ValidationError

from apps.imports.sources.sheets import SheetsSource


class MissingSourceColumnErrorTest(TestCase):
    def test_missing_source_column_raises_explicit_validation_error(self):
        """Parsing sheet without source column raises ValidationError with candidate list and actual headings."""
        raw_data = [
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус"],  # Missing source column
            ["1001", "0191", "Amir Karimov", "100,000", "28.07.2026", "успешно"],
        ]

        source = SheetsSource.__new__(SheetsSource)
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = raw_data

        with self.assertRaises(ValidationError) as ctx:
            source._parse_orders(mock_worksheet)

        err_msg = str(ctx.exception)
        self.assertIn("manba ustuni topilmadi", err_msg)
        self.assertIn("Источник", err_msg)
        self.assertIn("№", err_msg)
