from decimal import Decimal

from django.test import TestCase

from apps.employees.models import Employee
from apps.imports.dto import PayrollDTO
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

    def test_sync_without_employee_clears_summary_data_for_removed_employee(self):
        """Syncing payroll with employee 0001 and then syncing without 0001 clears 0001's summary_data and resets salary."""
        importer = DataImporter()

        payroll1 = [
            PayrollDTO(
                employee_id="0001",
                employee_name="Employee One",
                group_code="A",
                monthly_salary=Decimal("5000000"),
                summary_data={"earned_salary": "5000000", "total_sales": "10000000"},
            ),
            PayrollDTO(
                employee_id="0002",
                employee_name="Employee Two",
                group_code="B",
                monthly_salary=Decimal("4000000"),
                summary_data={"earned_salary": "4000000", "total_sales": "8000000"},
            ),
        ]
        importer.import_dto_lists(orders=[], payroll=payroll1)

        emp1 = Employee.objects.get(employee_id="0001")
        self.assertEqual(emp1.summary_data.get("earned_salary"), "5000000")

        # Sync payroll containing only 0002
        payroll2 = [
            PayrollDTO(
                employee_id="0002",
                employee_name="Employee Two",
                group_code="B",
                monthly_salary=Decimal("4000000"),
                summary_data={"earned_salary": "4000000", "total_sales": "8000000"},
            ),
        ]
        importer.import_dto_lists(orders=[], payroll=payroll2)

        emp1.refresh_from_db()
        self.assertEqual(emp1.summary_data, {})
        self.assertEqual(emp1.monthly_salary, Decimal("0.00"))

