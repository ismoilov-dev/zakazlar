"""Django application configuration for shared technical primitives."""

from django.apps import AppConfig


class CommonConfig(AppConfig):
    """Configure cross-cutting technical concerns."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.common"
    verbose_name = "Common"
