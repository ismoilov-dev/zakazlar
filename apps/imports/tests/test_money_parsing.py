import logging
from decimal import Decimal
from django.test import TestCase

from apps.imports.sources.excel import ExcelSource
from apps.imports.sources.sheets import SheetsSource


from apps.common.services.exceptions import ValidationError as DomainValidationError
from django.core.exceptions import ValidationError as DjangoValidationError



class MoneyParsingTest(TestCase):
    def test_money_parsing_formatting_and_warning(self) -> None:
        # Test 1: "1,5" -> 1.5
        self.assertEqual(SheetsSource._parse_money("1,5"), Decimal("1.5"))

        # Test 2: "1,234,567" -> 1234567
        self.assertEqual(SheetsSource._parse_money("1,234,567"), Decimal("1234567"))

        # Test 3: "1 234 567" -> 1234567
        self.assertEqual(SheetsSource._parse_money("1 234 567"), Decimal("1234567"))

        # Empty cells return Decimal("0.00")
        self.assertEqual(SheetsSource._parse_money(""), Decimal("0.00"))
        self.assertEqual(SheetsSource._parse_money(None), Decimal("0.00"))

        # Unparseable strings raise ValidationError
        with self.assertRaises((DjangoValidationError, DomainValidationError)):
            SheetsSource._parse_money("abc")

        with self.assertRaises((DjangoValidationError, DomainValidationError)):
            SheetsSource._parse_money("#REF!")

        # ExcelSource _money with decimal comma
        self.assertEqual(ExcelSource._money("1,5"), Decimal("1.50"))


