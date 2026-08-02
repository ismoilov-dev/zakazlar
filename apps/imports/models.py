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
    sync_type = models.CharField(max_length=16, default="payroll")
    payroll_hash = models.CharField(max_length=64, blank=True, default="")
    orders_hash = models.CharField(max_length=64, blank=True, default="")
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


import re
from django.core.exceptions import ValidationError

SPREADSHEET_ID_REGEX = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
BARE_ID_REGEX = re.compile(r"^[a-zA-Z0-9-_]{25,100}$")


def extract_spreadsheet_id(input_val: str) -> tuple[str, str]:
    """Extract spreadsheet_id and spreadsheet_url from input string.

    Returns (spreadsheet_id, spreadsheet_url).
    Raises ValidationError if input is neither a valid Google Sheets URL nor a valid bare ID.
    """
    val = (input_val or "").strip()
    if not val:
        raise ValidationError("Google Sheets URL yoki ID kiritilishi shart.")

    match = SPREADSHEET_ID_REGEX.search(val)
    if match:
        extracted_id = match.group(1)
        url = val if val.startswith("http") else f"https://docs.google.com/spreadsheets/d/{extracted_id}"
        return extracted_id, url

    if BARE_ID_REGEX.match(val):
        url = f"https://docs.google.com/spreadsheets/d/{val}"
        return val, url

    raise ValidationError("Yaroqsiz Google Sheets URL yoki ID format. Masalan: https://docs.google.com/spreadsheets/d/.../ edit yoki bare ID.")


class SpreadsheetPeriod(TimeStampedModel):
    """Google Sheets workbook configured per monthly period."""

    period = models.DateField(unique=True, help_text="First day of month (YYYY-MM-01)")
    spreadsheet_id = models.CharField(max_length=128)
    spreadsheet_url = models.URLField(max_length=500, blank=True)
    is_active = models.BooleanField(default=False)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "spreadsheet_periods"
        ordering = ("-period",)

    def __str__(self) -> str:
        active_str = " [ACTIVE]" if self.is_active else ""
        return f"{self.period.strftime('%Y-%m')} — {self.spreadsheet_id[:12]}...{active_str}"

    def clean(self) -> None:
        super().clean()
        if self.period and self.period.day != 1:
            self.period = self.period.replace(day=1)

        target = self.spreadsheet_url or self.spreadsheet_id
        if target:
            try:
                extracted_id, url = extract_spreadsheet_id(target)
                self.spreadsheet_id = extracted_id
                if not self.spreadsheet_url:
                    self.spreadsheet_url = url
            except ValidationError as exc:
                msg = exc.message if hasattr(exc, "message") else str(exc)
                raise ValidationError({"spreadsheet_id": msg}) from exc

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        from django.db import transaction

        with transaction.atomic():
            if self.is_active:
                SpreadsheetPeriod.objects.filter(is_active=True).exclude(pk=self.pk).update(is_active=False)
            super().save(*args, **kwargs)

