from unittest.mock import patch
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import TestCase

from apps.imports.models import ImportJob, ImportStatus
from apps.imports.services.workbook import WorkbookImportService


class WorkbookImportServiceFailureTest(TestCase):
    @patch("apps.imports.services.workbook.ExcelSource")
    def test_unexpected_error_marks_job_failed(self, mock_excel_source_cls) -> None:
        mock_source = mock_excel_source_cls.return_value
        mock_source.read.side_effect = IntegrityError("Database integrity constraint violated")

        uploaded = SimpleUploadedFile("test.xlsx", b"dummy content", content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        service = WorkbookImportService()
        job = service.create_job(workbook=uploaded, uploaded_by=None)

        with self.assertRaises(IntegrityError):
            service.process(job_id=job.pk)

        job.refresh_from_db()
        self.assertEqual(job.status, ImportStatus.FAILED)
        self.assertEqual(len(job.error_details), 1)
        self.assertIn("Database integrity constraint violated", job.error_details[0]["message"])
