from datetime import date
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.imports.models import SpreadsheetPeriod, extract_spreadsheet_id


class SpreadsheetPeriodTest(TestCase):
    def test_extract_spreadsheet_id_full_url(self):
        url = "https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit#gid=0"
        sid, surl = extract_spreadsheet_id(url)
        self.assertEqual(sid, "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms")
        self.assertEqual(surl, url)

    def test_extract_spreadsheet_id_bare_id(self):
        bare_id = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
        sid, surl = extract_spreadsheet_id(bare_id)
        self.assertEqual(sid, bare_id)
        self.assertEqual(surl, f"https://docs.google.com/spreadsheets/d/{bare_id}")

    def test_extract_spreadsheet_id_invalid_raises_validation_error(self):
        with self.assertRaises(ValidationError):
            extract_spreadsheet_id("not_a_valid_url_or_id")

    def test_single_active_constraint(self):
        sp1 = SpreadsheetPeriod.objects.create(
            period=date(2026, 7, 1),
            spreadsheet_id="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upm1",
            is_active=True,
        )
        sp2 = SpreadsheetPeriod.objects.create(
            period=date(2026, 8, 1),
            spreadsheet_id="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upm2",
            is_active=True,
        )
        sp1.refresh_from_db()
        sp2.refresh_from_db()

        self.assertFalse(sp1.is_active)
        self.assertTrue(sp2.is_active)
