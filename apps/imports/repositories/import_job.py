"""ORM repository for workbook imports."""

from django.db import transaction
from django.utils import timezone
from django.core.files.uploadedfile import UploadedFile

from apps.common.repositories.base import DjangoRepository
from apps.imports.models import ImportJob, ImportStatus


class ImportJobRepository(DjangoRepository[ImportJob]):
    """Persist import lifecycle transitions without exposing ORM to services."""

    model = ImportJob

    def exists_with_checksum(self, checksum: str) -> bool:
        return self.model.objects.filter(checksum=checksum).exists()

    def create(self, *, workbook: UploadedFile, checksum: str, uploaded_by: object) -> ImportJob:
        return self.model.objects.create(workbook=workbook, checksum=checksum, uploaded_by=uploaded_by)

    def get_for_processing(self, job_id: int) -> ImportJob:
        return self.model.objects.select_for_update().get(pk=job_id)

    @transaction.atomic
    def mark_processing(self, job: ImportJob) -> None:
        job.status = ImportStatus.PROCESSING
        job.started_at = timezone.now()
        job.error_details = []
        job.save(update_fields=["status", "started_at", "error_details", "updated_at"])

    @transaction.atomic
    def mark_completed(self, job: ImportJob, *, processed: int, created: int, updated: int) -> None:
        job.status = ImportStatus.COMPLETED
        job.processed_rows = processed
        job.created_sales = created
        job.updated_sales = updated
        job.completed_at = timezone.now()
        job.save(
            update_fields=[
                "status", "processed_rows", "created_sales", "updated_sales", "completed_at", "updated_at"
            ]
        )

    @transaction.atomic
    def mark_failed(self, job: ImportJob, errors: list[dict[str, str]]) -> None:
        job.status = ImportStatus.FAILED
        job.error_details = errors
        job.completed_at = timezone.now()
        job.save(update_fields=["status", "error_details", "completed_at", "updated_at"])
