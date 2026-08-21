from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from apps.employees.models import Employee
from apps.groups.models import SalesGroup
from apps.imports.dto import OrderDTO, PayrollDTO
from apps.imports.services.importer import DataImporter
from apps.imports.services.sheets_sync import SheetsSyncService
from apps.imports.sources.sheets import SheetsSource
from apps.sales.models import Sale, SaleStatus, SaleSource
from apps.statistics.repositories.statistics import StatisticsRepository


class SumMismatchRegressionTests(TestCase):
    def setUp(self):
        self.group = SalesGroup.objects.create(code="A", name="Group A")
        self.emp = Employee.objects.create(
            employee_id="0015",
            full_name="Xumoyun Kamolov",
            group=self.group,
            monthly_salary=Decimal("5000000.00"),
        )

    def test_parse_money_formatting_variations(self):
        """1. Test _parse_money with various space, comma, dot thousands separators."""
        self.assertEqual(SheetsSource._parse_money("69 710 000"), Decimal("69710000"))
        self.assertEqual(SheetsSource._parse_money("69,710,000"), Decimal("69710000"))
        self.assertEqual(SheetsSource._parse_money("69.710.000"), Decimal("69710000"))
        self.assertEqual(SheetsSource._parse_money("69 710 000,50"), Decimal("69710000.50"))
        self.assertEqual(SheetsSource._parse_money("69710000"), Decimal("69710000"))
        self.assertEqual(SheetsSource._parse_money("1,5"), Decimal("1.5"))

    def test_employee_missing_from_payroll_rejected_no_autocreate(self):
        """2. Employee missing from List2 payroll roster should be rejected, not auto-created."""
        importer = DataImporter()
        orders = [
            OrderDTO(
                order_id="ORD-999",
                employee_id="0999",
                employee_name="Yangi Xodim",
                group_code="A",
                status="successful",
                source="Pervichka",
                sale_amount=Decimal("10380000.00"),
                ordered_at=timezone.now(),
            )
        ]
        created, updated = importer.import_orders_only(orders=orders)
        self.assertEqual(created, 0)
        self.assertEqual(updated, 0)

        new_emp = Employee.objects.filter(employee_id="0999").first()
        self.assertIsNone(new_emp)

        sale = Sale.objects.filter(external_order_id="ORD-999").first()
        self.assertIsNone(sale)

    def test_sale_amount_none_has_sheet_error_handling(self):
        """3. Sale with has_sheet_error=True and sale_amount=None does not crash aggregate SUM."""
        Sale.objects.create(
            external_order_id="ERR-001",
            employee=self.emp,
            status=SaleStatus.SUCCESSFUL,
            source=SaleSource.PERVICHKA,
            sale_amount=None,
            has_sheet_error=True,
            ordered_at=timezone.now(),
        )
        Sale.objects.create(
            external_order_id="VAL-001",
            employee=self.emp,
            status=SaleStatus.SUCCESSFUL,
            source=SaleSource.PERVICHKA,
            sale_amount=Decimal("5000000.00"),
            ordered_at=timezone.now(),
        )

        repo = StatisticsRepository()
        totals = repo.employee_totals(self.emp.id)
        self.assertEqual(totals["total_sales"], Decimal("5000000.00"))

    def test_month_boundary_orders_included_in_statistics(self):
        """4. Orders on month start (00:00:00) and month end (23:59:59) are included in stats query."""
        now = timezone.localtime()
        month_start = timezone.make_aware(datetime(now.year, now.month, 1, 0, 0, 0))
        
        import calendar
        last_day = calendar.monthrange(now.year, now.month)[1]
        month_end = timezone.make_aware(datetime(now.year, now.month, last_day, 23, 59, 59))

        Sale.objects.create(
            external_order_id="START-001",
            employee=self.emp,
            status=SaleStatus.SUCCESSFUL,
            source=SaleSource.PERVICHKA,
            sale_amount=Decimal("1000000.00"),
            ordered_at=month_start,
        )
        Sale.objects.create(
            external_order_id="END-001",
            employee=self.emp,
            status=SaleStatus.SUCCESSFUL,
            source=SaleSource.PERVICHKA,
            sale_amount=Decimal("2000000.00"),
            ordered_at=month_end,
        )

        repo = StatisticsRepository()
        totals = repo.employee_totals(self.emp.id, target_date=now.date())
        self.assertEqual(totals["total_sales"], Decimal("3000000.00"))

    def test_end_to_end_10_orders_exact_sum(self):
        """5. End-to-end test: 10 orders imported yield exact aggregated sum of 69,710,000."""
        importer = DataImporter()
        orders = []
        now = timezone.localtime()

        amounts = [
            Decimal("10000000.00"),
            Decimal("8000000.00"),
            Decimal("7000000.00"),
            Decimal("6000000.00"),
            Decimal("5000000.00"),
            Decimal("9000000.00"),
            Decimal("4000000.00"),
            Decimal("10000000.00"),
            Decimal("5710000.00"),
            Decimal("5000000.00"),
        ]
        expected_total = sum(amounts)
        self.assertEqual(expected_total, Decimal("69710000.00"))

        for i, amt in enumerate(amounts, start=1):
            orders.append(
                OrderDTO(
                    order_id=f"ORD-E2E-{i}",
                    employee_id="0015",
                    employee_name="Xumoyun Kamolov",
                    group_code="A",
                    status="successful" if i % 2 == 1 else "pending",
                    source="Pervichka" if i % 2 == 1 else "Baza",
                    sale_amount=amt,
                    ordered_at=now,
                )
            )

        importer.import_orders_only(orders=orders)
        repo = StatisticsRepository()
        totals = repo.employee_totals(self.emp.id, target_date=now.date())
        self.assertEqual(totals["total_sales"], expected_total)
