"""Sales-group persistence models."""

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

    class Meta:
        db_table = "sales_groups"
        ordering = ("code",)

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"
