from django.test import TestCase

from apps.employees.models import Employee
from apps.groups.models import SalesGroup
from apps.imports.admin import ImportJobAdmin
from apps.imports.models import ImportJob


class AdminCascadeDeleteTest(TestCase):
    def test_cascade_delete_job_does_not_delete_payroll_employees(self) -> None:
        group = SalesGroup.objects.create(code="BAZA", name="Baza Group")
        employee = Employee.objects.create(
            employee_id="0191",
            full_name="Amir Karimov",
            group=group,
        )

        job = ImportJob.objects.create(checksum="dummy_checksum_123")

        # Perform cascade delete
        ImportJobAdmin._cascade_delete([job])

        # Employee should still exist!
        self.assertTrue(Employee.objects.filter(employee_id="0191").exists())
        self.assertEqual(ImportJob.objects.filter(id=job.id).count(), 0)
