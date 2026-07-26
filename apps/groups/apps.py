"""Django application configuration for sales groups."""

from django.apps import AppConfig


class GroupsConfig(AppConfig):
    """Configure sales group concerns."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.groups"
    verbose_name = "Groups"
