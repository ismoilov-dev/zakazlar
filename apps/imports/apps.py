"""Django application configuration for workbook imports."""

from django.apps import AppConfig
from django.core.checks import Warning, register


def check_cache_table(app_configs, **kwargs):
    warnings = []
    try:
        from django.db import connection
        tables = connection.introspection.table_names()
        if "sync_cache" not in tables:
            warnings.append(
                Warning(
                    "Cache table 'sync_cache' does not exist in database! Run 'python manage.py createcachetable'.",
                    id="imports.W001",
                )
            )
    except Exception:
        pass
    return warnings


class ImportsConfig(AppConfig):
    """Configure import audit and processing concerns."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.imports"
    verbose_name = "Imports"

    def ready(self) -> None:
        """Register system checks for imports app."""
        register(check_cache_table)
