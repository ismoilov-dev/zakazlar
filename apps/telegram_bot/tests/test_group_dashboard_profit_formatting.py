from decimal import Decimal
from django.test import TestCase

from apps.statistics.services.statistics import GroupDashboard
from apps.telegram_bot.services.formatting import group_dashboard_text


from apps.common.services.exceptions import ValidationError
from apps.employees.models import Employee
from apps.groups.models import SalesGroup
from apps.statistics.services.statistics import StatisticsService


class GroupDashboardProfitFormattingTest(TestCase):
    def test_group_dashboard_renders_stored_profit_and_bonus(self):
        dashboard = GroupDashboard(
            group_name="Group Alpha",
            group_code="A",
            successful_orders=0,
            total_sales=Decimal("50000000.00"),
            total_profit=Decimal("10000000.00"),
            leader_bonus=Decimal("200000.00"),
            leader_personal_profit=Decimal("0.00"),
            month_str="07.2026",
        )


        text = group_dashboard_text(dashboard)
        self.assertIn("10,000,000 so'm", text)
        self.assertIn("200,000 so'm", text)
        self.assertIn("Rahbar bonusi", text)

    def test_absent_guruhlar_sheet_raises_validation_error(self):
        leader = Employee.objects.create(employee_id="0001", full_name="Leader One")
        group = SalesGroup.objects.create(code="A", name="Group A", leader=leader)

        with self.assertRaises(ValidationError) as ctx:
            StatisticsService()._group_dashboard(group, leader)

        self.assertIn("Guruh ma'lumotlari sozlanmagan", str(ctx.exception))

