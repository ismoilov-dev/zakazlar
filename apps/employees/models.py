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
