"""Aiogram application bootstrap."""

from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from apps.telegram_bot.routers import router


import logging
import os
import subprocess

logger = logging.getLogger(__name__)


def _get_git_commit() -> str:
    try:
        res = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=2)
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return "unknown"


async def run_polling(token: str) -> None:
    """Start long polling with the project's isolated router tree."""
    commit_hash = _get_git_commit()
    pid = os.getpid()
    logger.info("Starting Telegram bot process (PID: %s, Commit: %s)", pid, commit_hash)

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = Dispatcher()
    
    from apps.telegram_bot.services.error_handler import global_error_handler
    dispatcher.error.register(global_error_handler)
    dispatcher.include_router(router)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_my_commands([
            BotCommand(command="start", description="Botni ishga tushirish"),
            BotCommand(command="stats", description="Xizmatlar menyusi"),
            BotCommand(command="shaxsiy", description="Shaxsiy xizmatlar menyusi"),
            BotCommand(command="rop", description="ROP paneli"),
            BotCommand(command="chiqish", description="Tizimdan chiqish"),
        ])
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        await bot.session.close()
