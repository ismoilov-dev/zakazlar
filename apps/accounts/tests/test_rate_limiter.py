from django.core.cache import cache
from django.test import TestCase

from apps.accounts.services.rate_limiter import (
    clear_failed_attempts,
    is_rate_limited,
    record_failed_attempt,
)


class RateLimiterTest(TestCase):
    def setUp(self) -> None:
        cache.clear()

    def test_rate_limiter_allows_up_to_two_failures_and_blocks_on_third(self) -> None:
        user_id = 99999

        self.assertFalse(is_rate_limited(user_id))

        record_failed_attempt(user_id, "0001", "Wrong Name 1")
        self.assertFalse(is_rate_limited(user_id))

        record_failed_attempt(user_id, "0001", "Wrong Name 2")
        self.assertFalse(is_rate_limited(user_id))

        record_failed_attempt(user_id, "0001", "Wrong Name 3")
        self.assertTrue(is_rate_limited(user_id))

    def test_clear_failed_attempts_resets_counter(self) -> None:
        user_id = 88888
        for _ in range(3):
            record_failed_attempt(user_id, "0002", "Bad Name")

        self.assertTrue(is_rate_limited(user_id))

        clear_failed_attempts(user_id)
        self.assertFalse(is_rate_limited(user_id))
