"""Workbook import audit models."""

from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class ImportStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class ImportJob(TimeStampedModel):
    """An uploaded workbook and its immutable processing audit."""

    workbook = models.FileField(upload_to="imports/%Y/%m/%d/")
    checksum = models.CharField(max_length=64, unique=True, editable=False)
    status = models.CharField(max_length=16, choices=ImportStatus.choices, default=ImportStatus.PENDING)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_import_jobs",
    )
    processed_rows = models.PositiveIntegerField(default=0)
    created_sales = models.PositiveIntegerField(default=0)
    updated_sales = models.PositiveIntegerField(default=0)
    error_details = models.JSONField(default=list, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "import_jobs"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"Import #{self.pk} ({self.status})"
