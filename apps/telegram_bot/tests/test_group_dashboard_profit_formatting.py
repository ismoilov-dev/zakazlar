from decimal import Decimal
from django.test import TestCase

from apps.statistics.services.statistics import GroupDashboard
from apps.telegram_bot.services.formatting import group_dashboard_text


class GroupDashboardProfitFormattingTest(TestCase):
    def test_zero_profit_displays_no_profit_data_text(self):
        """When group total_profit is 0, render 'Foyda ma'lumotlari mavjud emas' instead of 0 bonus."""
        dashboard = GroupDashboard(
            group_name="Group Alpha",
            group_code="A",
            successful_orders=8,
            total_profit=Decimal("0.00"),
            leader_bonus=Decimal("0.00"),
            leader_personal_profit=Decimal("0.00"),
            month_str="07.2026",
        )

        text = group_dashboard_text(dashboard)
        self.assertIn("Foyda ma'lumotlari mavjud emas", text)
