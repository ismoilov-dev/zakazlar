"""Aiogram middlewares for anti-flood throttling and concurrency protection."""

from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from django.core.cache import cache

logger = logging.getLogger(__name__)


class ThrottlingMiddleware(BaseMiddleware):
    """Anti-flood throttling middleware using Django cache."""

    def __init__(self, rate_limit: float = 0.5) -> None:
        super().__init__()
        self.rate_limit = rate_limit

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user_id: int | None = None
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id

        if user_id:
            cache_key = f"bot_throttle_{user_id}"
            try:
                is_throttled = cache.get(cache_key)
                if is_throttled:
                    logger.warning("Throttling rapid request from user %s", user_id)
                    if isinstance(event, CallbackQuery):
                        try:
                            await event.answer("Juda ko'p so'rov yuborildi. Iltimos, biroz kutib qayta urinib ko'ring.", show_alert=True)
                        except Exception:
                            pass
                    return None
                cache.set(cache_key, True, timeout=1)
            except Exception as exc:
                logger.warning("Throttling cache error for user %s: %s", user_id, exc)

        return await handler(event, data)
