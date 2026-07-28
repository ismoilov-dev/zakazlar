"""Service for synchronized Google Sheets reads, cache freshness, and audit logging."""

from __future__ import annotations

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.common.services.exceptions import ValidationError
from apps.imports.models import SyncLog, SyncStatus
from apps.imports.services.importer import DataImporter
from apps.imports.sources.sheets import SheetsSource


class SheetsSyncService:
    """Orchestrates Google Sheets live synchronization with cache and freshness checks."""

    CACHE_KEY = "sheets_sync_recent_lock"
    CACHE_TTL_SECONDS = 60

    def __init__(self) -> None:
        self.importer = DataImporter()

    def sync_if_needed(self, force: bool = False) -> SyncLog:
        """Check Drive modifiedTime & cache lock. Perform atomic DB snapshot update if fresh data exists."""
        last_successful = SyncLog.get_last_successful()

        # 1. Immediate cache lock check to prevent concurrent thundering herd network calls
        if not force and cache.get(self.CACHE_KEY):
            if last_successful:
                return last_successful

        # Set lock immediately to prevent other concurrent requests from calling Google API simultaneously
        if not force:
            cache.set(self.CACHE_KEY, True, timeout=self.CACHE_TTL_SECONDS)

        try:
            source = SheetsSource()
            sheet_id = source.sheet_id

            # 2. Query Google Drive API for spreadsheet modifiedTime
            current_modified_time = ""
            try:
                drive_meta = source.client.http_client.get_file_drive_metadata(sheet_id)
                current_modified_time = str(drive_meta.get("modifiedTime", ""))
            except Exception:
                current_modified_time = ""

            # 3. Check if spreadsheet was modified since last successful sync
            if not force and current_modified_time and last_successful and last_successful.sheet_modified_at == current_modified_time:
                return last_successful

            # 4. Perform atomic sync
            sync_log = SyncLog.objects.create(
                status=SyncStatus.PENDING,
                sheet_modified_at=current_modified_time,
            )

            orders, payroll = source.read()

            with transaction.atomic():
                result = self.importer.import_dto_lists(orders=orders, payroll=payroll)
                sync_log.status = SyncStatus.SUCCESS
                sync_log.finished_at = timezone.now()
                sync_log.row_count = result.processed_rows
                sync_log.created_sales = result.created_sales
                sync_log.updated_sales = result.updated_sales
                sync_log.save(update_fields=["status", "finished_at", "row_count", "created_sales", "updated_sales"])

            return sync_log

        except Exception as exc:
            # If error occurs and we have a previous successful log, fall back to it gracefully
            if last_successful:
                return last_successful
            raise ValidationError(f"Google Sheets sync muvaffaqiyatsiz tugadi: {exc}") from exc
