import asyncio
from unittest.mock import patch
from django.test import TestCase

from apps.telegram_bot.routers import SYNC_TIMEOUT_SECONDS, ensure_fresh_data_and_get_timestamp


class SyncTimeoutAndStaleTest(TestCase):
    def test_sync_timeout_constant_is_three_seconds(self):
        """SYNC_TIMEOUT_SECONDS should be 3.0 seconds."""
        self.assertEqual(SYNC_TIMEOUT_SECONDS, 3.0)

    @patch("apps.telegram_bot.routers.SheetsSyncService")
    async def test_ensure_fresh_data_calls_sync_without_force(self, mock_service_cls):
        """Background sync should be called with force=False."""
        mock_service = mock_service_cls.return_value
        await ensure_fresh_data_and_get_timestamp()
        await asyncio.sleep(0.1)
        mock_service.sync_if_needed.assert_called_with(force=False)

    @patch("apps.telegram_bot.routers.SheetsSyncService")
    async def test_concurrent_calls_share_single_flight_sync_task(self, mock_service_cls):
        """Concurrent callers share single-flight sync task."""
        mock_service = mock_service_cls.return_value

        res1, res2 = await asyncio.gather(
            ensure_fresh_data_and_get_timestamp(),
            ensure_fresh_data_and_get_timestamp(),
        )
        self.assertIsNotNone(res1)
        self.assertIsNotNone(res2)

