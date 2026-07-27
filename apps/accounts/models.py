"""Telegram identity persistence models."""

from django.db import models

from apps.common.models import TimeStampedModel


class TelegramAccount(TimeStampedModel):
    """One Telegram identity bound to one active employee."""

    employee = models.ForeignKey(
        "employees.Employee",
        on_delete=models.CASCADE,
        related_name="telegram_accounts",
    )
    telegram_id = models.BigIntegerField(unique=True)
    username = models.CharField(max_length=255, blank=True)
    bound_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "telegram_accounts"

    def __str__(self) -> str:
        return f"{self.telegram_id} → {self.employee.employee_id}"
