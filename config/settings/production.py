"""Production security profile.

This profile becomes active after PostgreSQL and environment-based settings are
added. Values that must vary by deployment are intentionally not hard-coded.
"""

from .base import *  # noqa: F403

DEBUG = False

if not SECRET_KEY or SECRET_KEY.startswith(("django-insecure-", "replace-with-")):  # noqa: F405
    message = "DJANGO_SECRET_KEY must be set to a secure value in production."
    raise RuntimeError(message)

from .env import get_bool

use_https = get_bool("DJANGO_USE_HTTPS", default=True)

SESSION_COOKIE_SECURE = use_https
CSRF_COOKIE_SECURE = use_https
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if use_https else None
SECURE_SSL_REDIRECT = use_https
X_FRAME_OPTIONS = "DENY"

