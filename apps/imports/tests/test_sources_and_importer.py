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

    def test_unlisted_employee_order_does_not_create_employee(self) -> None:
        """Order for employee ID not in payroll roster does not auto-create an Employee or Sale."""
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
                employee_id="9999",  # Not in payroll
                employee_name="Unknown Person",
                group_code="A",
                order_id="99999",
                status=SaleStatus.SUCCESSFUL,
                source="Baza",
                sale_amount=Decimal("100000.00"),
                ordered_at=now,
            )
        ]
        result = importer.import_dto_lists(orders=orders, payroll=payroll)
        self.assertEqual(Employee.objects.count(), 1)
        self.assertEqual(Employee.objects.first().employee_id, "0191")
        self.assertEqual(Sale.objects.count(), 0)


    def test_order_row_does_not_override_payroll_group(self) -> None:
        from apps.statistics.services.statistics import StatisticsService
        importer = DataImporter()
        now = timezone.now()
        payroll = [
            PayrollDTO(
                employee_id="0191",
                employee_name="Amir Karimov",
                group_code="BAZA",
                monthly_salary=Decimal("5000000.00"),
                summary_data={
                    "total_sales": "1000000.00",
                    "successful_sales": "1000000.00",
                    "perv_sales": "0.00",
                    "baza_sales": "1000000.00",
                    "otkaz_sales": "0.00",
                    "v_proc_sales": "0.00",
                    "earned_salary": "5000000.00",
                    "successful_orders": 1,
                },
            )
        ]
        orders = [
            OrderDTO(
                employee_id="0191",
                employee_name="Amir Karimov",
                group_code="A",  # Order row specifies 'A', but payroll specified 'BAZA'
                order_id="47180",
                status=SaleStatus.SUCCESSFUL,
                source="Baza",
                sale_amount=Decimal("1000000.00"),
                ordered_at=now,
            )
        ]
        importer.import_dto_lists(orders=orders, payroll=payroll)
        emp = Employee.objects.get(employee_id="0191")
        self.assertEqual(emp.group.code, "BAZA")

        dashboard = StatisticsService().employee_dashboard_for_employee("0191")
        self.assertEqual(dashboard.earned_salary, Decimal("5000000.00"))

    def test_parse_orders_skips_trailing_empty_rows(self) -> None:
        from unittest.mock import MagicMock
        from apps.imports.sources.sheets import SheetsSource

        source = object.__new__(SheetsSource)
        source.last_dropped_rows = []

        mock_ws = MagicMock()
        mock_ws.get_all_values.return_value = [
            ["ID", "Zakaz №", "Ответственный", "Сумма", "Дата Заказа", "статус", "guruh", "manba"],
            ["0191", "1001", "Amir", "50000", "2026-07-28 10:00:00", "Успешно", "A", "База"],
            ["", "", "", "", "", "", "", ""],
            [" \xa0 ", "", "", "", "", "", "", ""],
        ]


        orders = source._parse_orders(mock_ws, valid_employee_ids={"0191"})
        self.assertEqual(len(orders), 1)
        self.assertEqual(len(source.last_dropped_rows), 0)
        self.assertEqual(source.last_parse_summary["empty_rows_skipped"], 2)

    def test_unrecognized_sources_map_to_unknown_without_dropping(self) -> None:
        from unittest.mock import MagicMock
        from apps.imports.sources.sheets import SheetsSource

        source = object.__new__(SheetsSource)
        source.last_dropped_rows = []

        mock_ws = MagicMock()
        mock_ws.get_all_values.return_value = [
            ["ID", "Zakaz №", "Ответственный", "Сумма", "Дата Заказа", "статус", "guruh", "manba"],
            ["0191", "1001", "Amir", "50000", "2026-07-28 10:00:00", "Успешно", "A", "Dumka"],
            ["0191", "1002", "Amir", "50000", "2026-07-28 10:00:00", "Успешно", "A", "Otkaz"],
            ["0191", "1003", "Amir", "50000", "2026-07-28 10:00:00", "Успешно", "A", ""],
        ]

        orders = source._parse_orders(mock_ws, valid_employee_ids={"0191"})
        self.assertEqual(len(orders), 3)
        self.assertEqual(len(source.last_dropped_rows), 0)
        self.assertTrue(all(o.source == "UNKNOWN" for o in orders))

    def test_normalize_source_mapping(self) -> None:
        from apps.imports.sources.sheets import SheetsSource
        self.assertEqual(SheetsSource._normalize_source("Первичный Заказ"), ("Pervichka", None))
        self.assertEqual(SheetsSource._normalize_source("База"), ("Baza", None))
        self.assertEqual(SheetsSource._normalize_source("Dumka"), ("UNKNOWN", "Dumka"))
        self.assertEqual(SheetsSource._normalize_source(""), ("UNKNOWN", None))




