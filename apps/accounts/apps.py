"""Django application configuration for account management."""

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """Configure account and Telegram identity concerns."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    verbose_name = "Accounts"
