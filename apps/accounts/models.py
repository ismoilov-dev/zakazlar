"""Telegram identity persistence models."""

from django.db import models

from apps.common.models import TimeStampedModel


class TelegramAccount(TimeStampedModel):
    """One Telegram identity bound to one active employee.

    Note on `role`: The `role` column represents a display preference ("which menu
    to show by default"). It is NEVER used as an authorization gate. Actual ROP
    capability is derived dynamically from facts in the database (active leader in
    SalesGroup, presence of RopCredential, and valid ROP session).
    """

    employee = models.ForeignKey(
        "employees.Employee",
        on_delete=models.CASCADE,
        related_name="telegram_accounts",
    )
    telegram_id = models.BigIntegerField(unique=True)
    username = models.CharField(max_length=255, blank=True)
    role = models.CharField(max_length=10, default="MOP")
    bound_at = models.DateTimeField(auto_now_add=True)
    rop_authenticated_at = models.DateTimeField(null=True, blank=True)


    class Meta:
        db_table = "telegram_accounts"
        constraints = [
            models.UniqueConstraint(fields=["employee"], name="unique_telegram_account_per_employee"),
        ]

    def __str__(self) -> str:
        return f"{self.telegram_id} → {self.employee.employee_id}"
