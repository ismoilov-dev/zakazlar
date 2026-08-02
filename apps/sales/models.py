"""Imported sales persistence models."""

from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

from apps.common.models import TimeStampedModel


class SaleStatus(models.TextChoices):
    SUCCESSFUL = "successful", "Successful"
    CANCELLED = "cancelled", "Cancelled"
    PENDING = "pending", "Pending"


class SaleSource(models.TextChoices):
    PERVICHKA = "Pervichka", "Pervichka"
    BAZA = "Baza", "Baza"
    UNKNOWN = "UNKNOWN", "Unknown"


class Sale(TimeStampedModel):
    """A single source order imported from a company workbook."""

    external_order_id = models.CharField(max_length=128, unique=True)
    employee = models.ForeignKey("employees.Employee", on_delete=models.PROTECT, related_name="sales")
    import_job = models.ForeignKey(
        "imports.ImportJob", on_delete=models.SET_NULL, null=True, blank=True, related_name="sales"
    )
    status = models.CharField(max_length=16, choices=SaleStatus.choices)
    source = models.CharField(max_length=64, choices=SaleSource.choices, default=SaleSource.UNKNOWN, blank=True)

    sale_amount = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal("0"))])
    has_sheet_error = models.BooleanField(default=False)
    profit_amount = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    ordered_at = models.DateTimeField()

    class Meta:
        db_table = "sales"
        ordering = ("-ordered_at",)
        indexes = [
            models.Index(fields=("employee", "status", "ordered_at")),
            models.Index(fields=("status", "ordered_at")),
        ]

    def __str__(self) -> str:
        return self.external_order_id
