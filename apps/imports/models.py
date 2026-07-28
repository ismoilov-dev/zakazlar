"""Workbook import audit models."""

from __future__ import annotations

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


class SyncStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SUCCESS = "success", "Success"
    SKIPPED = "skipped", "Skipped"
    FAILED = "failed", "Failed"


class SyncLog(TimeStampedModel):
    """Audit log for automated Google Sheets live synchronizations."""

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    row_count = models.PositiveIntegerField(default=0)
    skipped_rows = models.PositiveIntegerField(default=0)
    created_sales = models.PositiveIntegerField(default=0)
    updated_sales = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=16, choices=SyncStatus.choices, default=SyncStatus.PENDING)
    error_text = models.TextField(blank=True, default="")
    sheet_modified_at = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        db_table = "sync_logs"
        ordering = ("-started_at",)

    def __str__(self) -> str:
        return f"SyncLog #{self.pk} ({self.status} at {self.started_at})"

    @classmethod
    def get_last_successful(cls) -> SyncLog | None:
        return cls.objects.filter(status=SyncStatus.SUCCESS).first()

