"""PostgreSQL database configuration factory.

Only non-secret development fallbacks live here. Deployment credentials are
provided through environment variables and documented in the environment stage.
"""

from __future__ import annotations

import os
from typing import Any


def postgresql_database() -> dict[str, dict[str, Any]]:
    """Build Django's default PostgreSQL connection configuration.

    `CONN_MAX_AGE` remains zero because this project exposes ASGI and uses an
    asynchronous bot process. Persistent connections are intentionally avoided
    at this layer; an external pool can be introduced when production load
    measurements justify it.
    """
    return {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("POSTGRES_DB", "sales_bot"),
            "USER": os.getenv("POSTGRES_USER", "sales_bot"),
            "PASSWORD": os.getenv("POSTGRES_PASSWORD", ""),
            "HOST": os.getenv("POSTGRES_HOST", "127.0.0.1"),
            "PORT": os.getenv("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": 0,
            "CONN_HEALTH_CHECKS": True,
            "OPTIONS": {
                "connect_timeout": 5,
                "application_name": "sales_telegram_bot",
            },
        },
    }
