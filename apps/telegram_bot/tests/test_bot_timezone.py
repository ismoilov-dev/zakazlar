from datetime import datetime
import zoneinfo
from django.test import TestCase
from django.utils import timezone

from apps.imports.models import SyncLog, SyncStatus
from apps.telegram_bot.routers import ensure_fresh_data_and_get_timestamp


class BotTimezoneTest(TestCase):
    async def test_ensure_fresh_data_timestamp_uses_local_timezone(self) -> None:
        # Create a UTC datetime: 2026-07-28 10:00:00 UTC
        # Asia/Samarkand (+05:00) time should be 15:00:00
        utc_dt = datetime(2026, 7, 28, 10, 0, 0, tzinfo=zoneinfo.ZoneInfo("UTC"))

        await SyncLog.objects.acreate(
            status=SyncStatus.SUCCESS,
            started_at=utc_dt,
            finished_at=utc_dt,
        )

        formatted_ts, _ = await ensure_fresh_data_and_get_timestamp()
        # Should display local time 15:00:00 instead of UTC 10:00:00
        self.assertEqual(formatted_ts, "28.07.2026 15:00:00")
