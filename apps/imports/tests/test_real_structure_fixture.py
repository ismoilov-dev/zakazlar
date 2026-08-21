from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from apps.employees.models import Employee
from apps.groups.models import SalesGroup
from apps.imports.dto import OrderDTO, PayrollDTO
from apps.imports.models import SyncLog, SyncStatus
from apps.imports.services.importer import DataImporter
from apps.imports.sources.sheets import SheetsSource
from apps.sales.models import Sale, SaleStatus, SaleSource
from apps.statistics.repositories.statistics import StatisticsRepository


class RealStructureFixtureTests(TestCase):
    def setUp(self):
        self.group_a = SalesGroup.objects.create(code="A", name="Group A")
        self.group_e = SalesGroup.objects.create(code="E", name="Group E")
        self.group_u = SalesGroup.objects.create(code="U", name="Group U")
        self.group_office = SalesGroup.objects.create(code="OFICE", name="Group Office")

        self.emp1 = Employee.objects.create(
            employee_id="0001",
            full_name="Alisher Navoiy ",  # trailing space in name
            group=self.group_a,
            monthly_salary=Decimal("5000000.00"),
        )
        self.emp191 = Employee.objects.create(
            employee_id="0191",
            full_name="Amir Karimov",
            group=self.group_a,
            monthly_salary=Decimal("4625400.00"),
        )

    def test_1_list1_fixture_exact_sum_delta_zero(self):
        """1. List1 fixture with trailing spaces, ' ' group column, duplicate 'кол-во1' -> exact expected sum."""
        source = object.__new__(SheetsSource)
        source.last_dropped_rows = []
        source.last_parse_summary = {}

        mock_ws = MagicMock()
        # Realistic headers matching prompt description exactly
        mock_ws.get_all_values.return_value = [
            [
                "№",
                "Ф.И.О.(mijoz)",
                "Контактный номер",
                "Дата Заказа",
                "Дата доставки",
                "ID(xodim)",
                "Ответственный(VLOOKUP)",
                " ",  # Column J: single space header for VLOOKUP group
                "Товар1",
                "кол-во1",  # L: quantity 1
                "Товар2",
                "кол-во1",  # N: duplicate header 'кол-во1' (quantity 2)
                "Сумма",
                "Регион",
                "Адрес",
                "статус",
                "Логистика",
                "Контакт",
                "Источник",
            ],
            [
                "1",
                "Jasur B.",
                "+998901234567",
                "2026-06-01 10:00:00",
                "2026-06-02",
                "0191",
                "Amir Karimov",
                "A",
                "Product Alpha",
                "2",
                "Product Beta",
                "1",
                "38 545 000",
                "Toshkent",
                "Chilonzor",
                "Успешно",
                "Express",
                "TG",
                "Первичный Заказ",
            ],
            [
                "2",
                "Sardor K.",
                "+998907654321",
                "2026-06-15 15:30:00",
                "2026-06-16",
                "0001",
                "Alisher Navoiy",
                "A",
                "Product Gamma",
                "1",
                "",
                "",
                "31,165,000.00",
                "Samarqand",
                "Markaz",
                "У курьера",
                "Standard",
                "Call",
                "База",
            ],
        ]

        orders = source._parse_orders(mock_ws, valid_employee_ids={"0191", "0001"})
        self.assertEqual(len(orders), 2)

        # Confirm duplicate header 'кол-во1' quantity extraction
        self.assertEqual(orders[0].quantity, 2)
        self.assertEqual(orders[0].group_code, "A")

        # Confirm exact expected total sum of 69,710,000 (38,545,000 + 31,165,000)
        parsed_sum = sum(o.sale_amount for o in orders)
        expected_sum = Decimal("69710000.00")
        self.assertEqual(parsed_sum, expected_sum)
        self.assertEqual(parsed_sum - expected_sum, Decimal("0.00"))

    def test_2_u_kuryera_status_mapped_to_successful(self):
        """2. Status 'У курьера' mapped to successful and not dropped."""
        source = object.__new__(SheetsSource)
        source.last_dropped_rows = []
        source.last_parse_summary = {}

        mock_ws = MagicMock()
        mock_ws.get_all_values.return_value = [
            ["ID", "Zakaz №", "Ответственный", "Сумма", "Дата Заказа", "статус", "guruh", "manba"],
            ["0191", "1001", "Amir", "1500000", "2026-06-10 12:00:00", "У курьера", "A", "База"],
            ["0191", "1002", "Amir", "2500000", "2026-06-11 12:00:00", "У КУРЬЕРА", "A", "База"],
            ["0191", "1003", "Amir", "3500000", "2026-06-12 12:00:00", "Курьерда", "A", "База"],
        ]

        orders = source._parse_orders(mock_ws, valid_employee_ids={"0191"})
        self.assertEqual(len(orders), 3)
        self.assertTrue(all(o.status == "successful" for o in orders))
        self.assertEqual(len(source.last_dropped_rows), 0)

    def test_3_unlisted_employee_tracked_in_synclog_and_auto_created(self):
        """3. Employee missing from List2 auto-creates Employee and records dropped sum if skipped."""
        importer = DataImporter()
        orders = [
            OrderDTO(
                order_id="ORD-UNLISTED-1",
                employee_id="9988",
                employee_name="Yangi Sotuvchi",
                group_code="A",
                status="successful",
                source="Pervichka",
                sale_amount=Decimal("10380000.00"),
                ordered_at=timezone.now(),
            )
        ]
        created, updated = importer.import_orders_only(orders=orders)
        self.assertEqual(created, 1)

        # Verify auto-created Employee & preserved Sale
        new_emp = Employee.objects.filter(employee_id="9988").first()
        self.assertIsNotNone(new_emp)
        self.assertEqual(new_emp.full_name, "Yangi Sotuvchi")

        sale = Sale.objects.filter(external_order_id="ORD-UNLISTED-1").first()
        self.assertIsNotNone(sale)
        self.assertEqual(sale.sale_amount, Decimal("10380000.00"))

    def test_4_dynamic_groups_e_u_office_leader_bonus_calculated(self):
        """4. Groups E, U, OFICE dynamically parsed from Guruhlar sheet and leader bonus calculated."""
        source = object.__new__(SheetsSource)

        # Guruhlar sheet matrix fixture with row0 having A, B, C, D, E, U, OFICE
        raw_rows = [
            ["SANA", "JAMI", "", "", "", "", "A", "A_PROFIT", "", "", "", "", "E", "E_PROFIT", "", "", "", "", "U", "U_PROFIT", "", "", "", "", "OFICE", "OFICE_PROFIT"],
            ["01.06.2026", "100000", "50000", "0", "0", "0", "5000000", "5000000", "0", "0", "0", "0", "4000000", "4000000", "0", "0", "0", "0", "3000000", "3000000", "0", "0", "0", "0", "2000000", "2000000"],
            ["JAMI:", "100000", "50000", "0", "0", "0", "5000000", "5000000", "0", "0", "0", "0", "4000000", "4000000", "0", "0", "0", "0", "3000000", "3000000", "0", "0", "0", "0", "2000000", "2000000"],
        ]

        groups = source._parse_groups(raw_rows)
        parsed_codes = [g.group_code for g in groups]
        self.assertIn("A", parsed_codes)
        self.assertIn("E", parsed_codes)
        self.assertIn("U", parsed_codes)
        self.assertIn("OFICE", parsed_codes)

        group_e_summary = next(g for g in groups if g.group_code == "E")
        self.assertEqual(group_e_summary.group_profit, Decimal("4000000.00"))
        self.assertEqual(group_e_summary.leader_bonus, Decimal("80000.00"))  # 2% of 4M profit

    def test_5_month_boundary_orders_included(self):
        """5. Month boundary orders (day 1 00:00:00 and last day 23:59:59) are included in statistics."""
        now = timezone.localtime()
        month_start = timezone.make_aware(datetime(now.year, now.month, 1, 0, 0, 0))

        import calendar
        last_day = calendar.monthrange(now.year, now.month)[1]
        month_end = timezone.make_aware(datetime(now.year, now.month, last_day, 23, 59, 59))

        Sale.objects.create(
            external_order_id="BOUNDARY-START",
            employee=self.emp191,
            status=SaleStatus.SUCCESSFUL,
            source=SaleSource.PERVICHKA,
            sale_amount=Decimal("10000000.00"),
            ordered_at=month_start,
        )
        Sale.objects.create(
            external_order_id="BOUNDARY-END",
            employee=self.emp191,
            status=SaleStatus.SUCCESSFUL,
            source=SaleSource.PERVICHKA,
            sale_amount=Decimal("20000000.00"),
            ordered_at=month_end,
        )

        repo = StatisticsRepository()
        totals = repo.employee_totals(self.emp191.id, target_date=now.date())
        self.assertEqual(totals["total_sales"], Decimal("30000000.00"))

    def test_6_guruhlar_sheet_finds_jami_summary_row(self):
        """6. Guruhlar matrix correctly finds the JAMI total summary row even with case variations."""
        source = object.__new__(SheetsSource)

        raw_rows = [
            ["SANA", "JAMI", "", "", "", "", "BAZA", "PROFIT"],
            ["01.06.2026", "500000", "0", "0", "0", "0", "500000", "500000"],
            ["02.06.2026", "500000", "0", "0", "0", "0", "500000", "500000"],
            ["ИТОГО ПО ГРУППАМ:", "1000000", "0", "0", "0", "0", "1000000", "1000000"],
        ]

        groups = source._parse_groups(raw_rows)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].group_code, "BAZA")
        self.assertEqual(groups[0].group_total_sales, Decimal("1000000.00"))
