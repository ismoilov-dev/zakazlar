import os
from unittest.mock import patch

from django.core.cache import cache
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.imports.services.sheets_sync import SheetsSyncService


class SheetChangedWebhookTests(APITestCase):
    def setUp(self) -> None:
        cache.clear()
        self.url = reverse("imports_api:sheet-changed")
        self.secret = "test-webhook-secret-12345"

    def test_webhook_returns_503_when_secret_not_configured(self) -> None:
        with patch.dict(os.environ, {"SHEETS_WEBHOOK_SECRET": ""}):
            with self.settings(SHEETS_WEBHOOK_SECRET=""):
                response = self.client.post(self.url, HTTP_X_WEBHOOK_SECRET=self.secret)
                self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    def test_webhook_returns_403_when_secret_invalid(self) -> None:
        with self.settings(SHEETS_WEBHOOK_SECRET=self.secret):
            response = self.client.post(self.url, HTTP_X_WEBHOOK_SECRET="wrong-secret")
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_webhook_returns_202_and_clears_cache_lock(self) -> None:
        # Pre-set cache lock
        cache.set(SheetsSyncService.CACHE_KEY, True, timeout=60)
        self.assertTrue(cache.get(SheetsSyncService.CACHE_KEY))

        with self.settings(SHEETS_WEBHOOK_SECRET=self.secret):
            response = self.client.post(self.url, HTTP_X_WEBHOOK_SECRET=self.secret)
            self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
            # Verify lock is now cleared
            self.assertIsNone(cache.get(SheetsSyncService.CACHE_KEY))

    def test_webhook_rate_limiting(self) -> None:
        with self.settings(SHEETS_WEBHOOK_SECRET=self.secret):
            # First request
            res1 = self.client.post(self.url, HTTP_X_WEBHOOK_SECRET=self.secret)
            self.assertEqual(res1.status_code, status.HTTP_202_ACCEPTED)

            # Immediate second request
            res2 = self.client.post(self.url, HTTP_X_WEBHOOK_SECRET=self.secret)
            self.assertEqual(res2.status_code, status.HTTP_202_ACCEPTED)
            self.assertIn("Rate limited", res2.data.get("detail", ""))
