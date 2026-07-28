from decimal import Decimal
from django.test import TestCase

from apps.employees.models import Employee
from apps.imports.dto import OrderDTO, PayrollDTO
from apps.imports.services.importer import DataImporter


class ClearSummaryDataTest(TestCase):
    def test_reimport_without_summary_data_clears_db_summary_data(self):
        """Re-importing a payroll row with summary_data=None should clear existing summary_data to {} in DB."""
        importer = DataImporter()

        payroll1 = [
            PayrollDTO(
                employee_id="0191",
                employee_name="Amir Karimov",
                group_code="A",
                monthly_salary=Decimal("1000000"),
                summary_data={"successful_orders": 5, "total_sales": "500000"},
            )
        ]
        importer.import_dto_lists(orders=[], payroll=payroll1)

        emp = Employee.objects.get(employee_id="0191")
        self.assertEqual(emp.summary_data.get("successful_orders"), 5)

        # Re-import with summary_data=None
        payroll2 = [
            PayrollDTO(
                employee_id="0191",
                employee_name="Amir Karimov",
                group_code="A",
                monthly_salary=Decimal("1000000"),
                summary_data=None,
            )
        ]
        importer.import_dto_lists(orders=[], payroll=payroll2)

        emp.refresh_from_db()
        self.assertEqual(emp.summary_data, {})
