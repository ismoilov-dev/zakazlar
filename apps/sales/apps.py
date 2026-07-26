"""Django application configuration for sales data."""

from django.apps import AppConfig


class SalesConfig(AppConfig):
    """Configure sales data concerns."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.sales"
    verbose_name = "Sales"
