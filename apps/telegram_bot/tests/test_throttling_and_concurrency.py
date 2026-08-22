"""Unit tests for ThrottlingMiddleware anti-flood protection."""
from unittest.mock import AsyncMock, MagicMock
from django.test import TestCase
from django.core.cache import cache
from aiogram.types import Message, User, Chat

from apps.telegram_bot.middlewares import ThrottlingMiddleware


class ThrottlingMiddlewareTestCase(TestCase):
    """Test anti-flood request throttling per user ID."""

    def setUp(self):
        cache.clear()

    async def test_throttling_middleware_blocks_rapid_requests(self):
        middleware = ThrottlingMiddleware(rate_limit=1.0)
        handler = AsyncMock(return_value="OK")

        user = User(id=999888, is_bot=False, first_name="TestUser")
        chat = Chat(id=999888, type="private")
        event = Message(message_id=1, date=100000, chat=chat, from_user=user, text="/start")

        # First request succeeds
        res1 = await middleware(handler, event, {})
        self.assertEqual(res1, "OK")
        self.assertEqual(handler.call_count, 1)

        # Immediate second request is throttled
        res2 = await middleware(handler, event, {})
        self.assertIsNone(res2)
        self.assertEqual(handler.call_count, 1)
