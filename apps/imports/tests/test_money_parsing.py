import logging
from decimal import Decimal
from django.test import TestCase

from apps.imports.sources.excel import ExcelSource
from apps.imports.sources.sheets import SheetsSource


class MoneyParsingTest(TestCase):
    def test_money_parsing_formatting_and_warning(self) -> None:
        # Test 1: "1,5" -> 1.5
        self.assertEqual(SheetsSource._parse_money("1,5"), Decimal("1.5"))

        # Test 2: "1,234,567" -> 1234567
        self.assertEqual(SheetsSource._parse_money("1,234,567"), Decimal("1234567"))

        # Test 3: "1 234 567" -> 1234567
        self.assertEqual(SheetsSource._parse_money("1 234 567"), Decimal("1234567"))

        # Test 4: ExcelSource _money with decimal comma
        self.assertEqual(ExcelSource._money("1,5"), Decimal("1.50"))

        # Test 5: "#REF!" logs warning instead of silent zero
        with self.assertLogs("apps.imports.sources.excel", level="WARNING") as cm:
            val = ExcelSource._money("#REF!", sheet_name="List1", row_idx=5)
            self.assertEqual(val, Decimal("0.00"))
            self.assertTrue(any("#REF!" in log_msg for log_msg in cm.output))
