from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.imports.models import SyncLog, SyncStatus
from apps.imports.services.sheets_sync import SheetsSyncService
from apps.telegram_bot.routers import ensure_fresh_data_and_get_timestamp


class SheetsSyncFailureTest(TestCase):
    @patch("apps.imports.services.sheets_sync.SheetsSource")
    def test_sync_failure_updates_synclog_and_stale_flag(self, mock_sheets_source_cls) -> None:
        # Set up mock source to raise exception on read()
        mock_source = mock_sheets_source_cls.return_value
        mock_source.sheet_id = "test_sheet_id"
        mock_source.read.side_effect = Exception("API connection timeout")

        service = SheetsSyncService()
        with self.assertRaises(Exception):
            service.sync_if_needed(force=True)

        # Check SyncLog
        log = SyncLog.objects.order_by("-started_at").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.status, SyncStatus.FAILED)
        self.assertIsNotNone(log.finished_at)
        self.assertIn("API connection timeout", log.error_text)

    @patch("apps.telegram_bot.routers._do_sync")
    async def test_is_stale_returns_true_when_failed(self, _mock_do_sync) -> None:
        # Create a FAILED log
        await SyncLog.objects.acreate(
            status=SyncStatus.FAILED,
            error_text="Fatal error",
            finished_at=timezone.now(),
        )

        _, is_stale = await ensure_fresh_data_and_get_timestamp()
        self.assertTrue(is_stale)

    @patch("apps.imports.services.sheets_sync.SHEETS_RECALC_DELAY_SECONDS", 0)
    @patch("apps.imports.services.sheets_sync.SheetsSource")
    def test_period_mismatch_aborts_sync_with_error_and_nothing_written(self, mock_sheets_source_cls) -> None:
        from datetime import date, datetime, timezone as tz
        from decimal import Decimal
        from apps.common.services.exceptions import ValidationError
        from apps.employees.models import EmployeeMonthlyStat
        from apps.imports.dto import OrderDTO, PayrollDTO
        from apps.imports.models import SpreadsheetPeriod

        SpreadsheetPeriod.objects.all().delete()
        SpreadsheetPeriod.objects.create(
            period=date(2026, 8, 1),
            spreadsheet_id="1W8wvi0nmrlnIsrqUBjNjEuoXbkcLQxFCK5fd3v3hto8",
            is_active=True,
        )

        mock_source = mock_sheets_source_cls.return_value
        mock_source.sheet_id = "16rSon1F6rSon1F6rSon1F6rSon1F6rSon1F6rSon1F"
        mock_source.read.return_value = (
            [
                OrderDTO(
                    employee_id="0001",
                    employee_name="Test Seller",
                    group_code="A",
                    order_id="1001",
                    status="Muvaffaqiyatli",
                    source="Test",
                    sale_amount=Decimal("100000"),
                    ordered_at=datetime(2026, 6, 15, 10, 0, tzinfo=tz.utc),
                )
            ],
            [
                PayrollDTO(
                    group_code="A",
                    employee_id="0001",
                    employee_name="Test Seller",
                    monthly_salary=None,
                    summary_data={"total_sales": "100000"},
                )
            ],
        )

        service = SheetsSyncService()
        with self.assertLogs("apps.imports.services.sheets_sync", level="ERROR") as cm:
            with self.assertRaises(ValidationError):
                service.sync_if_needed(force=True)

        self.assertTrue(any("does not match" in log for log in cm.output))
        self.assertEqual(EmployeeMonthlyStat.objects.count(), 0)

