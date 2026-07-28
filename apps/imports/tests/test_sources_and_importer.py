"""Unit tests for import sources and DataImporter layer."""

from decimal import Decimal
from django.test import TestCase

from apps.common.services.exceptions import ValidationError
from apps.employees.models import Employee
from apps.imports.dto import OrderDTO, PayrollDTO, normalize_employee_id
from apps.imports.services.importer import DataImporter
from apps.sales.models import Sale, SaleStatus
from django.utils import timezone


class NormalizeEmployeeIdTest(TestCase):
    def test_normalize_employee_id(self) -> None:
        self.assertEqual(normalize_employee_id("0191"), "0191")
        self.assertEqual(normalize_employee_id("191"), "0191")
        self.assertEqual(normalize_employee_id(191), "0191")
        self.assertEqual(normalize_employee_id("191.0"), "0191")
        self.assertEqual(normalize_employee_id("70"), "0070")

    def test_invalid_employee_id(self) -> None:
        with self.assertRaises(ValidationError):
            normalize_employee_id("abc")
        with self.assertRaises(ValidationError):
            normalize_employee_id("")


class DataImporterTest(TestCase):
    def test_import_dto_lists(self) -> None:
        importer = DataImporter()
        now = timezone.now()
        payroll = [
            PayrollDTO(
                employee_id="0191",
                employee_name="Amir Karimov",
                group_code="B",
                monthly_salary=Decimal("5000000.00"),
            )
        ]
        orders = [
            OrderDTO(
                employee_id="0191",
                employee_name="Amir Karimov",
                group_code="B",
                order_id="47179",
                status=SaleStatus.SUCCESSFUL,
                source="Pervichka",
                sale_amount=Decimal("850000.00"),
                ordered_at=now,
            )
        ]
        result = importer.import_dto_lists(orders=orders, payroll=payroll)
        self.assertEqual(result.processed_rows, 1)
        self.assertEqual(result.created_sales, 1)
        self.assertEqual(Employee.objects.count(), 1)
        emp = Employee.objects.get(employee_id="0191")
        self.assertEqual(emp.full_name, "Amir Karimov")
        self.assertEqual(emp.monthly_salary, Decimal("5000000.00"))
        self.assertEqual(Sale.objects.count(), 1)
