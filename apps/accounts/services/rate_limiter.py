"""Rate limiting for Telegram registration attempts."""

from __future__ import annotations

import logging
from django.core.cache import cache

logger = logging.getLogger(__name__)

MAX_FAILED_ATTEMPTS = 3
CACHE_TIMEOUT = 3600  # 1 hour


def _get_cache_key(telegram_id: int) -> str:
    return f"reg_fail_attempts:{telegram_id}"


def record_failed_attempt(telegram_id: int, employee_id: str = "", typed_name: str = "") -> int:
    """Record a failed registration attempt and return updated fail count.

    Logs a WARNING with telegram_id, attempted employee_id, and typed_name.
    """
    logger.warning(
        "Registration failure: telegram_id=%s, attempted_employee_id=%s, typed_name=%s",
        telegram_id,
        employee_id,
        typed_name,
    )
    key = _get_cache_key(telegram_id)
    fails = cache.get(key, 0) + 1
    cache.set(key, fails, timeout=CACHE_TIMEOUT)
    return fails


def is_rate_limited(telegram_id: int) -> bool:
    """Return True if user has reached or exceeded max failed attempts (>= 3 in last hour)."""
    key = _get_cache_key(telegram_id)
    fails = cache.get(key, 0)
    return fails >= MAX_FAILED_ATTEMPTS


def clear_failed_attempts(telegram_id: int) -> None:
    """Clear failed attempts count for a user (e.g. on successful binding)."""
    key = _get_cache_key(telegram_id)
    cache.delete(key)
