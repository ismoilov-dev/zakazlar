"""Django application configuration for Telegram integration."""

from django.apps import AppConfig


class TelegramBotConfig(AppConfig):
    """Configure Telegram presentation adapter concerns."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.telegram_bot"
    verbose_name = "Telegram Bot"
