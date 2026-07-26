"""Django application configuration for statistics."""

from django.apps import AppConfig


class StatisticsConfig(AppConfig):
    """Configure reporting and bonus calculation concerns."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.statistics"
    verbose_name = "Statistics"
