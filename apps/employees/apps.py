"""Django application configuration for employee records."""

from django.apps import AppConfig


class EmployeesConfig(AppConfig):
    """Configure employee directory concerns."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.employees"
    verbose_name = "Employees"
