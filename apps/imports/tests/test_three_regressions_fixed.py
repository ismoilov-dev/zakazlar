import logging
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from apps.employees.models import Employee
from apps.groups.models import SalesGroup
from apps.imports.dto import OrderDTO
from apps.imports.models import SyncLog, SyncStatus
from apps.imports.services.importer import DataImporter
from apps.imports.sources.sheets import SheetsSource
from apps.sales.models import Sale, SaleStatus
from apps.telegram_bot.services.formatting import card_text


class ThreeRegressionsFixedTests(TestCase):
    def setUp(self):
        self.group_a = SalesGroup.objects.create(code="A", name="Group A")
        self.emp_xumoyun = Employee.objects.create(
            employee_id="0001",
            full_name="XUMOYUN KAMOLOV",
            group=self.group_a,
            monthly_salary=Decimal("5000000.00"),
        )

    def test_1_parse_status_resilience(self):
        """1. _parse_status recognizes 'В процес', 'В процес.', 'в процес ', 'В процесс', 'У курьер', 'У курьер.', 'Успешно', 'Отказ' without errors."""
        source = object.__new__(SheetsSource)
        test_cases = [
            ("В процес", "pending"),
            ("В процес.", "pending"),
            ("в процес ", "pending"),
            ("В процесс", "pending"),
            ("У курьер", "successful"),
            ("У курьер.", "successful"),
            ("Успешно", "successful"),
            ("Отказ", "cancelled"),
        ]
        for input_text, expected_status in test_cases:
            with self.subTest(input_text=input_text):
                status, is_unrecognized = source._parse_status(input_text)
                self.assertEqual(status, expected_status)
                self.assertFalse(is_unrecognized)

    def test_2_unknown_status_saved_not_dropped(self):
        """2. Unknown status ('Xyz') is NOT dropped: saved as pending and tracked in unrecognized_statuses."""
        source = object.__new__(SheetsSource)
        status, is_unrecognized = source._parse_status("Xyz")
        self.assertEqual(status, "pending")
        self.assertTrue(is_unrecognized)

    def test_3_end_to_end_exact_sum_matching(self):
        """3. End-to-end test with exact XUMOYUN KAMOLOV figures:
        Успешно 42 455 000 + Отказ 19 255 000 + В процес 8 000 000 = 69 710 000. Delta = 0.
        """
        source = object.__new__(SheetsSource)
        raw_rows = [
            ["ID", "Ответственный", "№", "Сумма", "Дата Заказа", "статус", "Bo'lim", "Источник"],
            ["0001", "XUMOYUN KAMOLOV", "ORD-1", "42 455 000", "01.08.2026", "Успешно", "A", "Pervichka"],
            ["0001", "XUMOYUN KAMOLOV", "ORD-2", "19 255 000", "02.08.2026", "Отказ", "A", "Pervichka"],
            ["0001", "XUMOYUN KAMOLOV", "ORD-3", "8 000 000", "03.08.2026", "В процес", "A", "Pervichka"],
        ]

        orders = source._parse_orders(raw_rows, valid_employee_ids={"0001"})
        self.assertEqual(len(orders), 3)

        total_parsed_sum = sum(o.sale_amount for o in orders if o.sale_amount)
        expected_sum = Decimal("69710000.00")
        self.assertEqual(total_parsed_sum, expected_sum)

        delta = expected_sum - total_parsed_sum
        self.assertEqual(delta, Decimal("0.00"))

        statuses = [o.status for o in orders]
        self.assertIn("successful", statuses)
        self.assertIn("cancelled", statuses)
        self.assertIn("pending", statuses)

    def test_4_duplicate_order_id_preserved(self):
        """4. Duplicate order ID № in same month is preserved with unique ID and tracked without dropping sum."""
        source = object.__new__(SheetsSource)
        raw_rows = [
            ["ID", "Ответственный", "№", "Сумма", "Дата Заказа", "статус", "Bo'lim", "Источник"],
            ["0001", "XUMOYUN KAMOLOV", "ORD-100", "5 000 000", "01.08.2026", "Успешно", "A", "Pervichka"],
            ["0001", "XUMOYUN KAMOLOV", "ORD-100", "2 380 000", "01.08.2026", "Успешно", "A", "Pervichka"],
        ]

        orders = source._parse_orders(raw_rows, valid_employee_ids={"0001"})
        self.assertEqual(len(orders), 2)
        self.assertEqual(orders[0].order_id, "202608_0001_ORD-100")
        self.assertEqual(orders[1].order_id, "202608_0001_ORD-100_dup2")

        self.assertEqual(source.last_duplicate_orders_count, 1)
        self.assertEqual(source.last_duplicate_orders_sum, Decimal("2380000.00"))

    def test_5_parse_groups_ignores_u_kuryera_and_jami(self):
        """5. _parse_groups with real Guruhlar r1 containing 'У курьера' and 'Jami:' outputs ONLY valid groups {A, B, BAZA}."""
        source = object.__new__(SheetsSource)
        raw_rows = [
            ["У курьера", "Jami:", "", "", "", "", "", "A", "A_PROFIT", "", "", "", "", "B", "B_PROFIT", "", "", "", "", "BAZA", "BAZA_PROFIT"],
            ["SANA", "JAMI", "Успешно", "Отказ", "В процесс", "USP %", "OTKAZ %", "JAMI", "5000000", "0", "0", "0", "0", "JAMI", "4000000", "0", "0", "0", "0", "JAMI", "3000000"],
            ["JAMI:", "10000000", "5000000", "0", "0", "0", "0", "5000000", "5000000", "0", "0", "0", "0", "4000000", "4000000", "0", "0", "0", "0", "3000000", "3000000"],
        ]

        groups = source._parse_groups(raw_rows)
        parsed_codes = [g.group_code for g in groups]

        self.assertIn("A", parsed_codes)
        self.assertIn("B", parsed_codes)
        self.assertIn("BAZA", parsed_codes)
        self.assertNotIn("У КУРЬЕРА", parsed_codes)
        self.assertNotIn("JAMI:", parsed_codes)
        self.assertNotIn("JAMI", parsed_codes)

    def test_6_card_text_shows_authoritative_sum_and_mismatch_warning(self):
        """6. card_text uses DB Sale model aggregation as authoritative source and shows warning if List2 differs."""
        now = timezone.now()
        Sale.objects.create(
            employee=self.emp_xumoyun,
            external_order_id="TEST-1",
            sale_amount=Decimal("42455000.00"),
            status=SaleStatus.SUCCESSFUL,
            ordered_at=now,
        )
        Sale.objects.create(
            employee=self.emp_xumoyun,
            external_order_id="TEST-2",
            sale_amount=Decimal("19255000.00"),
            status=SaleStatus.CANCELLED,
            ordered_at=now,
        )
        Sale.objects.create(
            employee=self.emp_xumoyun,
            external_order_id="TEST-3",
            sale_amount=Decimal("8000000.00"),
            status=SaleStatus.PENDING,
            ordered_at=now,
        )

        # List2 summary_data has old/flawed total (59 330 000)
        summary_data = {
            "total_sales": "59330000",
            "successful_sales": "42455000",
            "otkaz_sales": "19255000",
            "v_proc_sales": "0",
        }

        text = card_text(
            card_type="total_sales",
            full_name=self.emp_xumoyun.full_name,
            group_code=self.emp_xumoyun.group.code,
            summary_data=summary_data,
            employee_id=self.emp_xumoyun.employee_id,
            period_date=now.date(),
        )

        # Assert authoritative DB Sale total (69 710 000) is displayed
        self.assertIn("69\xa0710\xa0000 so'm", text)
        # Assert warning badge is rendered for List2 vs DB Sale mismatch
        self.assertIn("List2 va zakazlar bo'yicha hisob mos kelmadi", text)

    def test_7_unified_period_resolution_and_matching_shaxsiy_and_stats(self):
        """7. Unified get_active_period_date produces identical target period date and sales totals for stats repo and card text."""
        from apps.imports.models import SpreadsheetPeriod
        from apps.statistics.repositories.statistics import StatisticsRepository, get_active_period_date

        target_p = timezone.now().date().replace(day=1)
        SpreadsheetPeriod.objects.all().delete()
        SpreadsheetPeriod.objects.create(spreadsheet_id="1W8wvi0nmrlnIsrqUBjNjEuoXbkcLQxFCK5fd3v3hto8", period=target_p, is_active=True)

        Sale.objects.create(
            employee=self.emp_xumoyun,
            external_order_id="UNIFIED-1",
            sale_amount=Decimal("69710000.00"),
            status=SaleStatus.SUCCESSFUL,
            ordered_at=timezone.now(),
        )

        resolved_date = get_active_period_date()
        self.assertEqual(resolved_date, target_p)

        repo_totals = StatisticsRepository().employee_totals(self.emp_xumoyun.id)
        self.assertEqual(repo_totals["total_sales"], Decimal("69710000.00"))

        text = card_text(
            card_type="total_sales",
            full_name=self.emp_xumoyun.full_name,
            group_code=self.emp_xumoyun.group.code,
            summary_data={"total_sales": "69710000"},
            employee_id=self.emp_xumoyun.employee_id,
            db_totals=repo_totals,
        )
        self.assertIn("69\xa0710\xa0000 so'm", text)
        self.assertNotIn("List2 va zakazlar bo'yicha hisob mos kelmadi", text)
