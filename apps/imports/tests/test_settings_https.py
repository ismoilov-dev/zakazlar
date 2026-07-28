import os
import importlib
from unittest import TestCase
from unittest.mock import patch


class HTTPSSettingsTestCase(TestCase):
    """Verify production security settings adjust correctly based on DJANGO_USE_HTTPS env var."""

    def _import_prod_settings(self, env_value: str | None):
        env_dict = {"DJANGO_SECRET_KEY": "secure-production-secret-key-for-test-suite-only"}
        if env_value is not None:
            env_dict["DJANGO_USE_HTTPS"] = env_value

        with patch.dict(os.environ, env_dict, clear=False):
            if env_value is None and "DJANGO_USE_HTTPS" in os.environ:
                del os.environ["DJANGO_USE_HTTPS"]
            import config.settings.base as base
            importlib.reload(base)
            import config.settings.production as prod
            importlib.reload(prod)
            return prod

    def test_https_disabled_settings(self):
        prod = self._import_prod_settings("false")
        self.assertFalse(prod.SECURE_SSL_REDIRECT)
        self.assertFalse(prod.SESSION_COOKIE_SECURE)
        self.assertFalse(prod.CSRF_COOKIE_SECURE)
        self.assertIsNone(prod.SECURE_PROXY_SSL_HEADER)

    def test_https_enabled_settings(self):
        prod = self._import_prod_settings("true")
        self.assertTrue(prod.SECURE_SSL_REDIRECT)
        self.assertTrue(prod.SESSION_COOKIE_SECURE)
        self.assertTrue(prod.CSRF_COOKIE_SECURE)
        self.assertEqual(prod.SECURE_PROXY_SSL_HEADER, ("HTTP_X_FORWARDED_PROTO", "https"))

    def test_https_default_is_true(self):
        prod = self._import_prod_settings(None)
        self.assertTrue(prod.SECURE_SSL_REDIRECT)
        self.assertTrue(prod.SESSION_COOKIE_SECURE)
        self.assertTrue(prod.CSRF_COOKIE_SECURE)
