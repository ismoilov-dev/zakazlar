"""Importer service for Excel workbooks delegating to ExcelSource and DataImporter."""

from __future__ import annotations

from hashlib import sha256

from django.core.files.uploadedfile import UploadedFile
from django.db import transaction

from apps.common.services.exceptions import ValidationError
from apps.imports.models import ImportJob, ImportStatus
from apps.imports.repositories.import_job import ImportJobRepository
from apps.imports.services.importer import DataImporter
from apps.imports.sources.excel import ExcelSource


import logging

logger = logging.getLogger(__name__)


class WorkbookImportService:
    """Import `List1` orders and `List2` employee salaries transactionally."""

    def __init__(self) -> None:
        self.jobs = ImportJobRepository()
        self.importer = DataImporter()

    def create_job(self, *, workbook: UploadedFile, uploaded_by: object) -> ImportJob:
        if not workbook.name.lower().endswith(".xlsx"):
            raise ValidationError("Faqat .xlsx fayl yuklash mumkin.")
        if workbook.size > 20 * 1024 * 1024:
            raise ValidationError("Excel fayl hajmi 20 MB dan oshmasligi kerak.")
        payload = workbook.read()
        workbook.seek(0)
        checksum = sha256(payload).hexdigest()
        if self.jobs.exists_with_checksum(checksum):
            raise ValidationError("Bu Excel fayl avval import qilingan.")
        return self.jobs.create(workbook=workbook, checksum=checksum, uploaded_by=uploaded_by)

    def process(self, *, job_id: int) -> ImportJob:
        with transaction.atomic():
            job = self.jobs.get_for_processing(job_id)
            if job.status not in {ImportStatus.PENDING, ImportStatus.FAILED}:
                raise ValidationError("Ushbu import qayta ishga tushirilmaydi.")
            self.jobs.mark_processing(job)
        try:
            job.workbook.open("rb")
            try:
                content = job.workbook.read()
            finally:
                job.workbook.close()

            source = ExcelSource(content)
            orders, payroll = source.read()

            result = self.importer.import_dto_lists(orders=orders, payroll=payroll, job=job)
            self.jobs.mark_completed(
                job,
                processed=result.processed_rows,
                created=result.created_sales,
                updated=result.updated_sales,
            )
        except Exception as exc:
            logger.exception("Workbook processing failed for job_id=%s: %s", job_id, exc)
            self.jobs.mark_failed(job, [{"message": str(exc)}])
            raise
        return self.jobs.get(job_id)
