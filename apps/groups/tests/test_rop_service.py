from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from apps.employees.models import Employee
from apps.groups.models import SalesGroup
from apps.groups.services.rop_service import RopService
from apps.telegram_bot.services.formatting import rop_salary_card_text


class RopServiceSalaryBasisTest(TestCase):
    def setUp(self):
        self.service = RopService()

    def test_calculate_rop_salary_based_on_uspeshka_summasi(self):
        """ROP salary is 2% of group Uspeshka summasi, not total sales sum."""
        group_a = SalesGroup.objects.create(code="A", name="Group A")
        Employee.objects.create(
            employee_id="0001",
            full_name="Emp 1",
            group=group_a,
            summary_data={"total_sales": "50,000,000", "successful_sales": "20,000,000"},
        )
        Employee.objects.create(
            employee_id="0002",
            full_name="Emp 2",
            group=group_a,
            summary_data={"total_sales": "42,500,000", "successful_sales": "19,815,000"},
        )

        salary_info = self.service.calculate_rop_salary(group_a)
        self.assertEqual(salary_info["group_total_sales"], Decimal("92500000.00"))
        self.assertEqual(salary_info["group_successful_sales"], Decimal("39815000.00"))
        self.assertEqual(salary_info["rate_pct_str"], "2%")
        self.assertEqual(salary_info["computed_salary"], Decimal("796300.00"))
        self.assertEqual(salary_info["uncalculated_uspeshka_count"], 0)

        card_text = rop_salary_card_text(group_a.code, salary_info)
        self.assertIn("📊 Guruh jami savdosi: <b>92,500,000 so'm</b>", card_text)
        self.assertIn("✅ Guruh uspeshka summasi: <b>39,815,000 so'm</b>", card_text)
        self.assertIn("📐 Foiz: <b>2%</b>", card_text)
        self.assertIn("💵 ROP oyligi: <b>796,300 so'm</b>", card_text)

    def test_calculate_rop_salary_missing_uspeshka_column(self):
        """When Uspeshka column is missing, salary line shows missing warning and logs WARNING."""
        group_b = SalesGroup.objects.create(code="B", name="Group B")
        Employee.objects.create(
            employee_id="0003",
            full_name="Emp 3",
            group=group_b,
            summary_data={"total_sales": "10,000,000"},
        )

        with self.assertLogs("apps.groups.services.rop_service", level="WARNING") as cm:
            salary_info = self.service.calculate_rop_salary(group_b)

        self.assertIsNone(salary_info["group_successful_sales"])
        self.assertIsNone(salary_info["computed_salary"])
        self.assertTrue(any("missing Uspeshka summasi column/data" in log for log in cm.output))

        card_text = rop_salary_card_text(group_b.code, salary_info)
        self.assertIn("✅ Guruh uspeshka summasi: ⚠️ Bu ko'rsatkich hisoblanmagan.", card_text)
        self.assertIn("💵 ROP oyligi: ⚠️ Bu ko'rsatkich hisoblanmagan.", card_text)

    def test_calculate_rop_salary_formula_error_employee_excluded_and_counted(self):
        """Employees with formula errors in Uspeshka summasi contribute nothing and are noted on card."""
        group_c = SalesGroup.objects.create(code="C", name="Group C")
        Employee.objects.create(
            employee_id="0004",
            full_name="Emp 4",
            group=group_c,
            summary_data={"total_sales": "10,000,000", "successful_sales": "10,000,000"},
        )
        Employee.objects.create(
            employee_id="0005",
            full_name="Emp 5",
            group=group_c,
            summary_data={"total_sales": "5,000,000"},  # missing successful_sales
        )
        Employee.objects.create(
            employee_id="0006",
            full_name="Emp 6",
            group=group_c,
            summary_data={"total_sales": "5,000,000", "successful_sales": "INVALID_DECIMAL"},  # formula error
        )

        salary_info = self.service.calculate_rop_salary(group_c)
        self.assertEqual(salary_info["group_successful_sales"], Decimal("10000000.00"))
        self.assertEqual(salary_info["computed_salary"], Decimal("200000.00"))
        self.assertEqual(salary_info["uncalculated_uspeshka_count"], 2)

        card_text = rop_salary_card_text(group_c.code, salary_info)
        self.assertIn("💵 ROP oyligi: <b>200,000 so'm</b>", card_text)
        self.assertIn("⚠️ 2 ta xodimning uspeshka summasi hisoblanmagan.", card_text)
