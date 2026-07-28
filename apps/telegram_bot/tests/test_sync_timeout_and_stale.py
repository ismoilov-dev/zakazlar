import asyncio
from unittest.mock import patch
from django.test import TestCase

from apps.telegram_bot.routers import SYNC_TIMEOUT_SECONDS, ensure_fresh_data_and_get_timestamp


class SyncTimeoutAndStaleTest(TestCase):
    def test_sync_timeout_constant_is_four_seconds(self):
        """SYNC_TIMEOUT_SECONDS should be 4.0 seconds."""
        self.assertEqual(SYNC_TIMEOUT_SECONDS, 4.0)

    @patch("apps.telegram_bot.routers.SheetsSyncService")
    async def test_ensure_fresh_data_calls_sync_without_force(self, mock_service_cls):
        """Background sync should be called with force=False."""
        mock_service = mock_service_cls.return_value
        await ensure_fresh_data_and_get_timestamp()
        await asyncio.sleep(0.1)
        mock_service.sync_if_needed.assert_called_with(force=False)
