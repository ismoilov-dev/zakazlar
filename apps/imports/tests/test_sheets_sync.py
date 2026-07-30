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

