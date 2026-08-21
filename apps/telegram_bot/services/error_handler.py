"""Global Aiogram error handler and admin alert system."""

from __future__ import annotations

import logging
import traceback
from typing import Any

from aiogram import Bot
from aiogram.types import ErrorEvent, Update
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


def get_admin_ids() -> list[int]:
    """Parse admin Telegram IDs from Django settings or environment."""
    raw_val = getattr(settings, "TELEGRAM_ADMIN_IDS", None)
    if raw_val:
        if isinstance(raw_val, (list, tuple)):
            return [int(x) for x in raw_val if str(x).isdigit()]
        if isinstance(raw_val, str):
            return [int(x.strip()) for x in raw_val.split(",") if x.strip().isdigit()]
    return []


async def global_error_handler(event: ErrorEvent, bot: Bot) -> Any:
    """Catch unhandled bot errors and send structured alert to Admin Telegram ID(s)."""
    exc = event.exception
    update: Update = event.update

    logger.error("Unhandled exception in update %s: %s", update.update_id if update else "N/A", exc, exc_info=exc)

    admin_ids = get_admin_ids()
    if not admin_ids:
        return

    # Extract user info if available
    user_info = "N/A"
    update_type = "Unknown"
    if update:
        if update.message and update.message.from_user:
            u = update.message.from_user
            user_info = f"{u.full_name} (ID: <code>{u.id}</code>, @{u.username or 'yo_q'})"
            update_type = "Message"
        elif update.callback_query and update.callback_query.from_user:
            u = update.callback_query.from_user
            user_info = f"{u.full_name} (ID: <code>{u.id}</code>, @{u.username or 'yo_q'})"
            update_type = f"Callback ({update.callback_query.data})"

    tb_str = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    tb_snippet = tb_str[-800:]  # Last 800 chars for readability

    now_str = timezone.localtime().strftime("%d.%m.%Y %H:%M:%S")

    alert_text = (
        f"🚨 <b>BOTDA KUTILMAGAN XATOLIK YUZ BERDI!</b>\n\n"
        f"⏰ <b>Vaqt:</b> {now_str}\n"
        f"👤 <b>Foydalanuvchi:</b> {user_info}\n"
        f"📌 <b>Update turi:</b> {update_type}\n\n"
        f"❌ <b>Xatolik:</b> <code>{type(exc).__name__}: {str(exc)[:200]}</code>\n\n"
        f"📋 <b>Traceback:</b>\n<pre>{tb_snippet}</pre>"
    )

    for admin_id in admin_ids:
        try:
            await bot.send_message(chat_id=admin_id, text=alert_text, parse_mode="HTML")
        except Exception as send_err:
            logger.warning("Failed to send error alert to admin %s: %s", admin_id, send_err)
