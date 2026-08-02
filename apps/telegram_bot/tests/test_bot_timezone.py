import zoneinfo
from datetime import datetime
from unittest.mock import patch

from django.test import TestCase

from apps.imports.models import SyncLog, SyncStatus
from apps.telegram_bot.routers import ensure_fresh_data_and_get_timestamp


class BotTimezoneTest(TestCase):
    @patch("apps.telegram_bot.routers._do_sync")
    async def test_ensure_fresh_data_timestamp_uses_local_timezone(self, _mock_do_sync) -> None:
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

    @patch("apps.telegram_bot.routers._do_sync")
    async def test_orders_failure_does_not_affect_employee_payroll_staleness(self, _mock_do_sync) -> None:
        now = datetime.now(tz=zoneinfo.ZoneInfo("UTC"))
        await SyncLog.objects.acreate(
            sync_type="payroll",
            status=SyncStatus.SUCCESS,
            started_at=now,
            finished_at=now,
        )
        await SyncLog.objects.acreate(
            sync_type="orders",
            status=SyncStatus.FAILED,
            error_text="Period mismatch error",
            started_at=now,
            finished_at=now,
        )

        _, is_stale = await ensure_fresh_data_and_get_timestamp()
        self.assertFalse(is_stale)

