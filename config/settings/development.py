"""Local-development Django settings.

This profile keeps developer-friendly diagnostics separate from production
security settings. PostgreSQL connection settings are shared from `base.py`.
"""

from .base import *  # noqa: F403
from .env import get_bool

DEBUG = get_bool("DJANGO_DEBUG", default=True)

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
