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
from apps.sales.models import Sale
from apps.telegram_bot.services.formatting import card_text


class ThreeRegressionsFixedTests(TestCase):
    def setUp(self):
        self.group_a = SalesGroup.objects.create(code="A", name="Group A")
        self.emp_known = Employee.objects.create(
            employee_id="0001",
            full_name="Alisher Navoiy",
            group=self.group_a,
            monthly_salary=Decimal("5000000.00"),
        )

    def test_1_parse_groups_ignores_u_kuryera_and_jami(self):
        """1. _parse_groups with real Guruhlar r1 containing 'У курьера' and 'Jami:' outputs ONLY valid groups {A, B, C, D, BAZA}."""
        source = object.__new__(SheetsSource)
        # Real Guruhlar r1 fixture as described in user prompt
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

    def test_2_import_orders_only_rejects_unlisted_employee_no_autocreate(self):
        """2. import_orders_only rejects order for employee missing in List2 roster (no auto-creation)."""
        importer = DataImporter()
        unlisted_order = OrderDTO(
            order_id="ORD-UNLISTED-99",
            employee_id="9999",
            employee_name="Noma'lum Xodim",
            group_code="A",
            status="successful",
            source="Pervichka",
            sale_amount=Decimal("10380000.00"),
            ordered_at=timezone.now(),
        )

        created, updated = importer.import_orders_only(orders=[unlisted_order])

        # Verify order was rejected (0 created)
        self.assertEqual(created, 0)

        # Verify no unlisted Employee was auto-created in database
        unlisted_emp = Employee.objects.filter(employee_id="9999").first()
        self.assertIsNone(unlisted_emp)

        # Verify no Sale was created for unlisted order
        sale = Sale.objects.filter(external_order_id="ORD-UNLISTED-99").first()
        self.assertIsNone(sale)

    def test_3_formatting_card_text_uses_authoritative_source_without_max(self):
        """3. formatting.py card_text uses single authoritative summary_data source without max() guessing, logging error on discrepancy."""
        summary_data = {
            "total_sales": "59330000",
            "perv_sales": "38545000",
            "baza_sales": "0",
            "otkaz_sales": "18605000",
            "v_proc_sales": "2180000",
            "successful_sales": "38545000",
        }

        with self.assertLogs("apps.telegram_bot.services.formatting", level="ERROR") as cm:
            # Create discrepancy: total_sales=59330000, but perv+baza+otkaz+v_proc = 69710000
            summary_discrepant = dict(summary_data)
            summary_discrepant["perv_sales"] = "48925000"  # component sum = 48925000 + 18605000 + 218000 = 69710000

            text = card_text(
                card_type="total_sales",
                full_name="XUMOYUN KAMOLOV",
                group_code="A",
                summary_data=summary_discrepant,
            )

            # Assert authoritative value (59 330 000) is rendered, NOT max (69 710 000)
            self.assertIn("59\xa0330\xa0000 so'm", text)
            # Assert ERROR log was recorded for discrepancy
            self.assertTrue(any("Discrepancy in total_sales" in log for log in cm.output))
