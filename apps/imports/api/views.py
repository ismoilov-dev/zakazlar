import hmac
import logging
import os
import time

from django.conf import settings
from django.core.cache import cache
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.imports.services.sheets_sync import SheetsSyncService

logger = logging.getLogger(__name__)


class SheetChangedWebhookAPIView(APIView):
    """Receive Google Sheets onChange webhook signals to release cache lock immediately."""

    permission_classes = [AllowAny]
    RATE_LIMIT_CACHE_KEY = "sheet_webhook_last_call_timestamp"
    RATE_LIMIT_WINDOW_SECONDS = 5.0

    def post(self, request, *args, **kwargs) -> Response:
        secret = getattr(settings, "SHEETS_WEBHOOK_SECRET", None)
        if secret is None:
            secret = os.getenv("SHEETS_WEBHOOK_SECRET", "")
        secret = str(secret).strip()

        if not secret:
            logger.warning("Sheet changed webhook keldi, lekin SHEETS_WEBHOOK_SECRET sozlanmagan.")
            return Response(
                {"detail": "Webhook secret tozalanmagan / sozlanmagan."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        provided_secret = request.headers.get("X-Webhook-Secret") or request.META.get("HTTP_X_WEBHOOK_SECRET", "")
        if not hmac.compare_digest(provided_secret.strip(), secret):
            logger.warning("Sheet changed webhook xatosi: X-Webhook-Secret noto'g'ri.")
            return Response(
                {"detail": "Noto'g'ri webhook secret."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Rate limiting: limit rapid bursts to one cache lock clear per window
        now = time.time()
        last_call = cache.get(self.RATE_LIMIT_CACHE_KEY)
        if last_call and (now - float(last_call)) < self.RATE_LIMIT_WINDOW_SECONDS:
            logger.info("Sheet changed webhook rate-limited (takroriy so'rov %s s ichida).", self.RATE_LIMIT_WINDOW_SECONDS)
            return Response(
                {"status": "accepted", "detail": "Rate limited, signal qabul qilindi."},
                status=status.HTTP_202_ACCEPTED,
            )

        cache.set(self.RATE_LIMIT_CACHE_KEY, now, timeout=int(self.RATE_LIMIT_WINDOW_SECONDS * 2))
        SheetsSyncService.clear_cache_lock()
        logger.info("Sheet changed webhook qabul qilindi: cache lock bo'shatildi.")

        return Response(
            {"status": "accepted", "detail": "Cache lock bo'shatildi."},
            status=status.HTTP_202_ACCEPTED,
        )


class HealthCheckAPIView(APIView):
    """System health check endpoint including active period & last sync timestamp."""

    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs) -> Response:
        from apps.imports.models import SpreadsheetPeriod, SyncLog

        active_sp = SpreadsheetPeriod.objects.filter(is_active=True).first()
        active_period_str = active_sp.period.strftime("%Y-%m") if active_sp else None

        last_sync = SyncLog.get_last_successful()
        last_sync_ts = last_sync.finished_at.isoformat() if last_sync and last_sync.finished_at else None

        return Response(
            {
                "status": "ok",
                "active_period": active_period_str,
                "last_sync_timestamp": last_sync_ts,
            },
            status=status.HTTP_200_OK,
        )
