"""Tests for cache resilience, atomic locks, and clear_sheets_cache management command."""

from unittest.mock import patch

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase

from apps.imports.management.commands.clear_sheets_cache import clear_sheets_cache_keys
from apps.imports.models import SyncLog, SyncStatus
from apps.imports.services.sheets_sync import SheetsSyncService


class CacheResilienceTest(TestCase):
    def setUp(self):
        cache.clear()
        SyncLog.objects.all().delete()

    def test_cache_unavailable_does_not_fail_sync(self):
        """When cache operations raise exceptions, sync proceeds and logs 'CACHE UNAVAILABLE'."""
        service = SheetsSyncService()

        with patch.object(cache, "add", side_effect=Exception("DatabaseCache missing table 'sync_cache'")), \
             patch.object(cache, "get", side_effect=Exception("Cache error")), \
             patch.object(SheetsSyncService, "_get_drive_modified_time", return_value=("", False)), \
             patch("apps.imports.services.sheets_sync.SheetsSource") as mock_source_cls:
            mock_source = mock_source_cls.return_value
            mock_source.sheet_id = "test_sheet"
            mock_source.read_payroll_only.return_value = ([], [])
            mock_source.last_payroll_hash = "hash123"

            log = service.sync_payroll(force=True)

            self.assertEqual(log.status, SyncStatus.SUCCESS)
            self.assertIn("CACHE UNAVAILABLE", log.error_text or "")

    def test_atomic_lock_blocks_parallel_sync(self):
        """Parallel sync call when lock key is acquired returns last_successful log."""
        service = SheetsSyncService()

        # Create a initial successful log
        last_log = SyncLog.objects.create(
            status=SyncStatus.SUCCESS,
            sync_type="payroll",
            payroll_hash="prev_hash",
            row_count=5,
        )

        # Set lock key in cache manually
        cache.set(SheetsSyncService.CACHE_KEY_PAYROLL, True, timeout=10)

        # Second non-forced sync attempt
        second_log = service.sync_payroll(force=False)
        self.assertEqual(second_log.id, last_log.id)

    def test_clear_sheets_cache_command_clears_all_keys(self):
        """clear_sheets_cache management command clears all sheets-related cache keys."""
        cache.set("sheets_sync_recent_lock", True)
        cache.set("sheets_sync_orders_lock", True)
        cache.set("sheet_webhook_last_call_timestamp", "123456789")

        deleted_count = clear_sheets_cache_keys()
        self.assertGreaterEqual(deleted_count, 3)

        self.assertIsNone(cache.get("sheets_sync_recent_lock"))
        self.assertIsNone(cache.get("sheets_sync_orders_lock"))
        self.assertIsNone(cache.get("sheet_webhook_last_call_timestamp"))
