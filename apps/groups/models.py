from decimal import Decimal

from django.db import models

from apps.common.models import TimeStampedModel


class SalesGroup(TimeStampedModel):
    """A group of sellers with an optional employee leader."""

    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=128)
    leader = models.ForeignKey(
        "employees.Employee",
        on_delete=models.SET_NULL,
        related_name="led_groups",
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(default=True)
    group_profit = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    leader_bonus = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "sales_groups"
        ordering = ("code",)

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"

