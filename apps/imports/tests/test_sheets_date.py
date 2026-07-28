from datetime import datetime
from django.test import TestCase
from django.utils import timezone

from apps.imports.sources.sheets import SheetsSource


class SheetsDateTest(TestCase):
    def test_sheets_date_returns_aware_datetime(self) -> None:
        parsed_dt = SheetsSource._parse_date("01.07.2026")
        self.assertIsInstance(parsed_dt, datetime)
        self.assertTrue(timezone.is_aware(parsed_dt))
        self.assertEqual(parsed_dt.year, 2026)
        self.assertEqual(parsed_dt.month, 7)
        self.assertEqual(parsed_dt.day, 1)

        iso_parsed_dt = SheetsSource._parse_date("2026-07-01")
        self.assertIsInstance(iso_parsed_dt, datetime)
        self.assertTrue(timezone.is_aware(iso_parsed_dt))
