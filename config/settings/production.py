"""Production security profile.

This profile becomes active after PostgreSQL and environment-based settings are
added. Values that must vary by deployment are intentionally not hard-coded.
"""

from .base import *  # noqa: F403

DEBUG = False

if not SECRET_KEY or SECRET_KEY.startswith(("django-insecure-", "replace-with-")):  # noqa: F405
    message = "DJANGO_SECRET_KEY must be set to a secure value in production."
    raise RuntimeError(message)

from .env import get_bool, has_env

if not has_env("DJANGO_USE_HTTPS"):
    message = (
        "DJANGO_USE_HTTPS environment variable must be set in production. "
        "Set DJANGO_USE_HTTPS=true if domain and SSL certificate are configured, "
        "or DJANGO_USE_HTTPS=false if accessing via IP over HTTP."
    )
    raise RuntimeError(message)

use_https = get_bool("DJANGO_USE_HTTPS")

SESSION_COOKIE_SECURE = use_https
CSRF_COOKIE_SECURE = use_https
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if use_https else None
SECURE_SSL_REDIRECT = use_https
X_FRAME_OPTIONS = "DENY"

