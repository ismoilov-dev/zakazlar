"""Unit tests for hardened spreadsheet ingestion, period resolution, and formula error handling."""
import os
from decimal import Decimal
from unittest.mock import MagicMock, patch
import pytest
from django.test import TestCase
from django.utils import timezone

from apps.common.services.exceptions import ValidationError
from apps.imports.models import SpreadsheetPeriod
from apps.imports.sources.sheets import SheetsSource, resolve_spreadsheet_id


class SpreadsheetIngestionEnhancementsTestCase(TestCase):
    """Test resolution order, strict header matching, formula errors, and forward fill safety."""

    def test_resolve_spreadsheet_id_mismatch_warning(self):
        """Test that resolve_spreadsheet_id logs a warning on env vs DB active period mismatch."""
        SpreadsheetPeriod.objects.create(
            period=timezone.now().date().replace(day=1),
            spreadsheet_id="db_active_sheet_123",
            is_active=True,
        )
        with patch.dict(os.environ, {"GOOGLE_SHEET_ID": "env_override_sheet_456"}):
            with self.assertLogs("apps.imports.sources.sheets", level="WARNING") as cm:
                sheet_id, source_desc = resolve_spreadsheet_id()
                self.assertEqual(sheet_id, "db_active_sheet_123")
                self.assertIn("Spreadsheet ID mismatch!", cm.output[0])

    def test_is_sheet_error_detection(self):
        """Test that Google Sheets formula errors are correctly identified."""
        for err in ["#REF!", "#DIV/0!", "#VALUE!", "#N/A", "#NAME?", "#NULL!", "#NUM!", "#ERROR!"]:
            self.assertTrue(SheetsSource._is_sheet_error(err))
            self.assertTrue(SheetsSource._is_sheet_error(f"  {err}  "))
        self.assertFalse(SheetsSource._is_sheet_error("100000"))
        self.assertFalse(SheetsSource._is_sheet_error(" Muvaffaqiyatli "))

    def test_money_parsing_with_locales_and_spaces(self):
        """Test parsing of monetary amounts with spaces, non-breaking spaces, and locale symbols."""
        test_cases = [
            ("69 710 000 so'm", Decimal("69710000.00")),
            ("59\xa0330\xa0000,00 сум", Decimal("59330000.00")),
            ("177.000,50", Decimal("177000.50")),
            (" $ 1 250 000.00 ", Decimal("1250000.00")),
            ("#DIV/0!", Decimal("0.00")),
        ]
        for raw, expected in test_cases:
            res = SheetsSource._parse_money(raw)
            self.assertEqual(res, expected)
