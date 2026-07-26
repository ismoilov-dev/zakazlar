"""Run the Telegram bot as a separate Django process."""

from __future__ import annotations

import asyncio

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.telegram_bot.runner import run_polling


class Command(BaseCommand):
    """Start Aiogram polling after Django settings have been loaded."""

    help = "Run the sales Telegram bot using long polling."

    def handle(self, *args: object, **options: object) -> None:
        if not settings.TELEGRAM_BOT_TOKEN or settings.TELEGRAM_BOT_TOKEN.startswith("replace-with-"):
            raise CommandError("TELEGRAM_BOT_TOKEN .env faylida berilishi shart.")
        asyncio.run(run_polling(settings.TELEGRAM_BOT_TOKEN))
