from datetime import date
from unittest.mock import patch, MagicMock
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
        SpreadsheetPeriod.objects.all().delete()
        sp1 = SpreadsheetPeriod.objects.create(
            period=date(2025, 1, 1),
            spreadsheet_id="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upm1",
            is_active=True,
        )
        sp2 = SpreadsheetPeriod.objects.create(
            period=date(2025, 2, 1),
            spreadsheet_id="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upm2",
            is_active=True,
        )
        sp1.refresh_from_db()
        sp2.refresh_from_db()

        self.assertFalse(sp1.is_active)
        self.assertTrue(sp2.is_active)

    def test_resolve_spreadsheet_id_from_active_period(self):
        SpreadsheetPeriod.objects.all().delete()
        sp = SpreadsheetPeriod.objects.create(
            period=date(2025, 3, 1),
            spreadsheet_id="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upm3",
            is_active=True,
        )
        from apps.imports.sources.sheets import resolve_spreadsheet_id
        sid, source_desc = resolve_spreadsheet_id()
        self.assertEqual(sid, sp.spreadsheet_id)
        self.assertIn("DB SpreadsheetPeriod", source_desc)

    @patch("apps.imports.services.sheets_sync.SheetsSource")
    def test_period_mismatch_aborts_sync(self, mock_source_cls):
        from datetime import datetime, timezone as dt_timezone
        from decimal import Decimal
        from unittest.mock import MagicMock
        from apps.common.services.exceptions import ValidationError
        from apps.imports.dto import OrderDTO
        from apps.imports.services.sheets_sync import SheetsSyncService

        SpreadsheetPeriod.objects.all().delete()
        active_sp = SpreadsheetPeriod.objects.create(
            period=date(2026, 8, 1),
            spreadsheet_id="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upm1",
            is_active=True,
        )

        mock_source = MagicMock()
        mock_source.sheet_id = active_sp.spreadsheet_id
        mock_source.client.http_client.get_file_drive_metadata.return_value = {"modifiedTime": "2026-08-01T12:00:00Z"}

        orders = [
            OrderDTO(
                employee_id="0001",
                employee_name="Elbek",
                group_code="A",
                order_id="202607_0001_1",
                status="successful",
                source="Baza",
                sale_amount=Decimal("100000"),
                ordered_at=datetime(2026, 7, 15, tzinfo=dt_timezone.utc),
            )
        ]
        mock_source.read.return_value = (orders, [])
        mock_source_cls.return_value = mock_source

        service = SheetsSyncService()
        with self.assertRaises(ValidationError) as ctx:
            service.sync_if_needed(force=True, allow_period_mismatch=False)

        self.assertIn("does not match sheet data modal month", str(ctx.exception))

    def test_health_check_endpoint(self):
        SpreadsheetPeriod.objects.all().delete()
        sp = SpreadsheetPeriod.objects.create(
            period=date(2026, 9, 1),
            spreadsheet_id="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upm4",
            is_active=True,
        )
        response = self.client.get("/health/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["active_period"], "2026-09")
