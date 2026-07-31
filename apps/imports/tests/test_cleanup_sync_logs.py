from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.imports.models import SyncLog, SyncStatus


class CleanupSyncLogsTest(TestCase):
    def test_cleanup_sync_logs_deletes_old_logs_and_preserves_latest_successful(self):
        now = timezone.now()
        old_date = now - timedelta(days=40)

        # Old failed log
        old_failed = SyncLog.objects.create(status=SyncStatus.FAILED)
        SyncLog.objects.filter(pk=old_failed.pk).update(started_at=old_date)

        # Old successful log (only successful one)
        old_successful = SyncLog.objects.create(status=SyncStatus.SUCCESS)
        SyncLog.objects.filter(pk=old_successful.pk).update(started_at=old_date, finished_at=old_date)

        # Recent failed log
        recent_failed = SyncLog.objects.create(status=SyncStatus.FAILED)

        call_command("cleanup_sync_logs", days=30)

        # Old failed log should be deleted
        self.assertFalse(SyncLog.objects.filter(pk=old_failed.pk).exists())
        # Old successful log MUST be preserved because it's the latest successful
        self.assertTrue(SyncLog.objects.filter(pk=old_successful.pk).exists())
        # Recent failed log should be preserved
        self.assertTrue(SyncLog.objects.filter(pk=recent_failed.pk).exists())
