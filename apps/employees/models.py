"""Employee directory persistence models."""

from decimal import Decimal

from django.core.validators import RegexValidator
from django.db import models

from apps.common.models import TimeStampedModel


class Employee(TimeStampedModel):
    """A seller or group leader identified by a company Employee ID."""

    employee_id = models.CharField(
        max_length=32,
        unique=True,
        validators=[RegexValidator(r"^\d{4,32}$", "Employee ID faqat raqamlardan iborat bo'lishi kerak.")],
    )
    full_name = models.CharField(max_length=255)
    monthly_salary = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    summary_data = models.JSONField(default=dict, blank=True)
    group = models.ForeignKey(
        "groups.SalesGroup",
        on_delete=models.PROTECT,
        related_name="employees",
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "employees"
        ordering = ("employee_id",)
        indexes = [models.Index(fields=("employee_id", "is_active"))]

    def __str__(self) -> str:
        return f"{self.employee_id} — {self.full_name}"


from django.conf import settings


class EmployeeMonthlyStat(TimeStampedModel):
    """Historical per-month snapshot of an employee's List2 summary data."""

    employee = models.ForeignKey(
        Employee,
        on_delete=models.PROTECT,
        related_name="monthly_stats",
    )
    period = models.DateField(help_text="First day of month (YYYY-MM-01)")
    summary_data = models.JSONField(default=dict, blank=True)
    source_spreadsheet_id = models.CharField(max_length=128, blank=True)
    is_closed = models.BooleanField(default=False)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="closed_monthly_stats",
    )

    class Meta:
        db_table = "employee_monthly_stats"
        unique_together = ("employee", "period")
        ordering = ("-period",)

    def __str__(self) -> str:
        return f"{self.employee.employee_id} — {self.period.strftime('%m.%Y')}"

