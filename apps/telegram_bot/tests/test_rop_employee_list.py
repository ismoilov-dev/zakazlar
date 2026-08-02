from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import TelegramAccount
from apps.employees.models import Employee, RopCredential
from apps.groups.models import SalesGroup
from apps.groups.services.rop_service import RopService
from apps.telegram_bot.routers import handle_rop_callback
from apps.telegram_bot.services.formatting import rop_employee_list_card_text


class RopEmployeeListTest(TestCase):
    def setUp(self) -> None:
        self.group_a = SalesGroup.objects.create(code="A", name="Group A")
        self.leader_a = Employee.objects.create(
            employee_id="0001",
            full_name="ELBEK XAYDAROV",
            group=self.group_a,
        )
        self.group_a.leader = self.leader_a
        self.group_a.save()

        self.cred_a = RopCredential.objects.create(employee=self.leader_a)
        self.cred_a.set_password("Secret123")
        self.cred_a.save()

        self.account_a = TelegramAccount.objects.create(
            employee=self.leader_a,
            telegram_id=111,
            role="ROP",
            rop_authenticated_at=timezone.now(),
        )

        # Additional employees in Group A
        self.emp1 = Employee.objects.create(
            employee_id="0007",
            full_name="IRODA XAKIMOVA",
            group=self.group_a,
            summary_data={"total_sales": "75,425,000", "successful_orders": "101"},
        )
        self.leader_a.summary_data = {"total_sales": "92,570,000", "successful_orders": "47"}
        self.leader_a.save()

        self.emp2 = Employee.objects.create(
            employee_id="0002",
            full_name="SARDOR QULDOSHIV",
            group=self.group_a,
            summary_data={"total_sales": "0", "successful_orders": "0"},
        )
        self.emp3 = Employee.objects.create(
            employee_id="0003",
            full_name="LAZIZBEK ABDURAXMONOV",
            group=self.group_a,
            summary_data={},
        )

        # Another group B with leader and employee
        self.group_b = SalesGroup.objects.create(code="B", name="Group B")
        self.leader_b = Employee.objects.create(
            employee_id="0099",
            full_name="LEADER B",
            group=self.group_b,
        )
        self.group_b.leader = self.leader_b
        self.group_b.save()

        self.emp_b = Employee.objects.create(
            employee_id="0088",
            full_name="OTHER SELLER B",
            group=self.group_b,
            summary_data={"total_sales": "150,000,000", "successful_orders": "200"},
        )

    def test_has_sales_filter(self) -> None:
        service = RopService()
        employees = service.get_group_employee_list(self.group_a, "has_sales")
        emp_ids = [e["employee_id"] for e in employees]
        self.assertEqual(emp_ids, ["0001", "0007"])
        self.assertEqual(employees[0]["sales_val"], Decimal("92570000"))
        self.assertEqual(employees[1]["sales_val"], Decimal("75425000"))

    def test_no_sales_filter(self) -> None:
        service = RopService()
        employees = service.get_group_employee_list(self.group_a, "no_sales")
        emp_ids = [e["employee_id"] for e in employees]
        self.assertEqual(emp_ids, ["0002", "0003"])

        text = rop_employee_list_card_text("A", "no_sales", employees, 1, len(employees))
        self.assertIn("1. 0002 SARDOR QULDOSHIV", text)
        self.assertIn("2. 0003 LAZIZBEK ABDURAXMONOV", text)
        # Verify 0 figures line is omitted for no_sales
        self.assertNotIn("📊 0", text)

    def test_all_filter(self) -> None:
        service = RopService()
        employees = service.get_group_employee_list(self.group_a, "all")
        self.assertEqual(len(employees), 4)
        emp_ids = [e["employee_id"] for e in employees]
        # Sorted by sales desc (0001, 0007), then 0 sales by emp_id asc (0002, 0003)
        self.assertEqual(emp_ids, ["0001", "0007", "0002", "0003"])

    def test_leader_sees_only_own_group(self) -> None:
        service = RopService()
        employees = service.get_group_employee_list(self.group_a, "all")
        emp_ids = [e["employee_id"] for e in employees]
        self.assertNotIn("0088", emp_ids)
        self.assertNotIn("0099", emp_ids)

    def test_missing_figure_formula_error_shows_dash_and_warning(self) -> None:
        Employee.objects.create(
            employee_id="0005",
            full_name="HASAN SALIMOV",
            group=self.group_a,
            summary_data={"total_sales": "#N/A"},
        )
        service = RopService()
        employees = service.get_group_employee_list(self.group_a, "no_sales")
        hasan = next(e for e in employees if e["employee_id"] == "0005")
        self.assertTrue(hasan["has_error"])
        self.assertIsNone(hasan["sales_val"])

        text = rop_employee_list_card_text("A", "no_sales", employees, 1, len(employees))
        self.assertIn("HASAN SALIMOV", text)
        self.assertIn("📊 —", text)
        self.assertIn("⚠️ 1 ta xodimning ma'lumoti hisoblanmagan.", text)

    def test_pagination_boundaries(self) -> None:
        # Create 25 employees
        for i in range(10, 35):
            Employee.objects.create(
                employee_id=f"00{i}",
                full_name=f"Employee {i}",
                group=self.group_a,
                summary_data={"total_sales": f"{i * 1000000}"},
            )

        service = RopService()
        employees = service.get_group_employee_list(self.group_a, "all")
        total_count = len(employees)
        self.assertGreater(total_count, 20)

        # Page 1
        text_p1 = rop_employee_list_card_text("A", "all", employees, 1, total_count, page_size=20)
        self.assertIn("1.", text_p1)
        self.assertIn("20.", text_p1)
        self.assertNotIn("21.", text_p1)

        # Page 2
        text_p2 = rop_employee_list_card_text("A", "all", employees, 2, total_count, page_size=20)
        self.assertIn("21.", text_p2)

    @patch("apps.telegram_bot.routers.ensure_fresh_data_and_get_timestamp", return_value=("02.08.2026 16:00:00", False))
    async def test_tampered_callback_grants_nothing(self, _mock_ts) -> None:
        callback = MagicMock()
        callback.from_user.id = 111
        callback.data = "rop_emp_filter:invalid_filter_key:abc"
        callback.message.edit_text = AsyncMock()
        callback.answer = AsyncMock()

        state = AsyncMock()
        state.get_data = AsyncMock(return_value={})
        await handle_rop_callback(callback, state)

        # Should fall back safely to 'all' filter for group A, page 1
        text = callback.message.edit_text.call_args[0][0]
        self.assertIn("A guruh — Barchasi", text)
        self.assertNotIn("Group B", text)
        self.assertNotIn("OTHER SELLER B", text)
