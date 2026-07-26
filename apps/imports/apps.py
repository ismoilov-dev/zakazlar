"""Django application configuration for workbook imports."""

from django.apps import AppConfig


class ImportsConfig(AppConfig):
    """Configure import audit and processing concerns."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.imports"
    verbose_name = "Imports"
