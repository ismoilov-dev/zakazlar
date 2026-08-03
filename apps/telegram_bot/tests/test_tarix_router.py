from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import TestCase

from apps.accounts.models import TelegramAccount
from apps.employees.models import Employee, EmployeeMonthlyStat
from apps.telegram_bot.routers import employee_tarix, handle_xizmatlar_callback


class TarixRouterTest(TestCase):
    def setUp(self):
        self.emp = Employee.objects.create(
            employee_id="0191",
            full_name="Amir Karimov",
            summary_data={"earned_salary": "5000000.00"},
        )
        self.account = TelegramAccount.objects.create(
            employee=self.emp,
            telegram_id=12345678,
            username="amir_k",
        )
        self.stat = EmployeeMonthlyStat.objects.create(
            employee=self.emp,
            period=date(2026, 6, 1),
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

    async def test_tarix_unbound_user_replies_error(self):
        message = MagicMock()
        message.from_user.id = 999999
        message.answer = AsyncMock()

        await employee_tarix(message)
        message.answer.assert_called_once()
        self.assertIn("Avval Employee ID", message.answer.call_args[0][0])

    async def test_tarix_bound_user_shows_period_buttons(self):
        message = MagicMock()
        message.from_user.id = 12345678
        message.answer = AsyncMock()

        await employee_tarix(message)
        message.answer.assert_called_once()
        self.assertIn("Kerakli oy hisobotini tanlang", message.answer.call_args[0][0])
        reply_markup = message.answer.call_args[1].get("reply_markup")
        self.assertIsNotNone(reply_markup)

    def test_active_month_excluded_from_tarix_periods(self):
        from apps.imports.models import SpreadsheetPeriod
        from apps.statistics.services.statistics import StatisticsService

        SpreadsheetPeriod.objects.all().delete()
        SpreadsheetPeriod.objects.create(period=date(2026, 8, 1), spreadsheet_id="1W8wvi0nmrlnIsrqUBjNjEuoXbkcLQxFCK5fd3v3hto8", is_active=True)
        EmployeeMonthlyStat.objects.create(
            employee=self.emp,
            period=date(2026, 8, 1),
            summary_data={"earned_salary": "6000000.00"},
        )

        periods = StatisticsService().available_periods_for_telegram(self.account.telegram_id)
        period_dates = [p[0] for p in periods]
        self.assertNotIn(date(2026, 8, 1), period_dates)
        self.assertIn(date(2026, 6, 1), period_dates)

    @patch("apps.telegram_bot.routers.ensure_fresh_data_and_get_timestamp", return_value=("30.07.2026 12:00:00", False))
    async def test_show_historical_stat_callback_renders_stat(self, _mock_ts):
        callback = MagicMock()
        callback.from_user.id = 12345678
        callback.data = "xm_card:earned_salary:2026-06-01"
        callback.message.edit_text = AsyncMock()
        callback.answer = AsyncMock()

        await handle_xizmatlar_callback(callback)
        callback.message.edit_text.assert_called_once()
        text = callback.message.edit_text.call_args[0][0]
        self.assertIn("Amir Karimov", text)
        self.assertIn("Iyun 2026", text)

    @patch("apps.telegram_bot.routers.ensure_fresh_data_and_get_timestamp", return_value=("30.07.2026 12:00:00", False))
    async def test_show_historical_stat_closed_period_shows_closed_footer(self, _mock_ts):
        from asgiref.sync import sync_to_async

        def close_stat():
            self.stat.is_closed = True
            self.stat.save()

        await sync_to_async(close_stat)()

        callback = MagicMock()
        callback.from_user.id = 12345678
        callback.data = "xm_card:earned_salary:2026-06-01"
        callback.message.edit_text = AsyncMock()
        callback.answer = AsyncMock()

        await handle_xizmatlar_callback(callback)
        text = callback.message.edit_text.call_args[0][0]
        self.assertIn("🔒 <b>Oy yopilgan</b>", text)

    @patch("apps.telegram_bot.routers.ensure_fresh_data_and_get_timestamp", return_value=("30.07.2026 12:00:00", False))
    async def test_historical_card_reads_snapshot_not_live_data(self, _mock_ts):
        from asgiref.sync import sync_to_async

        def update_live_and_snapshot():
            self.emp.summary_data = {"otkaz_sales": "60000000.00", "earned_salary": "9999999.00"}
            self.emp.monthly_salary = Decimal("9999999.00") if hasattr(self, "Decimal") else 9999999
            self.emp.save()
            self.stat.summary_data = {
                "otkaz_sales": "52755000.00",
                "earned_salary": "3000000.00",
                "total_sales": "1000000.00",
                "successful_sales": "1000000.00",
                "perv_sales": "0.00",
                "baza_sales": "1000000.00",
                "v_proc_sales": "0.00",
                "successful_orders": 1,
            }
            self.stat.save()

        await sync_to_async(update_live_and_snapshot)()

        callback = MagicMock()
        callback.from_user.id = 12345678
        callback.data = "xm_card:otkaz:2026-06-01"
        callback.message.edit_text = AsyncMock()
        callback.answer = AsyncMock()

        await handle_xizmatlar_callback(callback)
        text = callback.message.edit_text.call_args[0][0]
        self.assertIn("52,755,000", text)
        self.assertNotIn("60,000,000", text)

    @patch("apps.telegram_bot.routers.ensure_fresh_data_and_get_timestamp", return_value=("30.07.2026 12:00:00", False))
    async def test_missing_snapshot_renders_not_saved_message(self, _mock_ts):
        callback = MagicMock()
        callback.from_user.id = 12345678
        callback.data = "xm_card:otkaz:2026-05-01"
        callback.message.edit_text = AsyncMock()
        callback.answer = AsyncMock()

        await handle_xizmatlar_callback(callback)
        text = callback.message.edit_text.call_args[0][0]
        self.assertIn("Bu oy uchun ma'lumot saqlanmagan.", text)


