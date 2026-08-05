from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import TestCase

from apps.accounts.models import TelegramAccount
from apps.employees.models import Employee, EmployeeMonthlyStat
from apps.groups.models import SalesGroup
from apps.telegram_bot.routers import (
    employee_stats,
    handle_bare_text_message,
    handle_xizmatlar_callback,
)
from apps.telegram_bot.services import formatting
from apps.telegram_bot.services.formatting import MISSING_VALUE_TEXT, card_text, format_uzbek_period, money


class XizmatlarMenuTest(TestCase):
    def setUp(self):
        self.group = SalesGroup.objects.create(code="A", name="Group A")
        self.emp = Employee.objects.create(
            employee_id="0191",
            full_name="Amir Karimov",
            group=self.group,
            monthly_salary=Decimal("5000000.00"),
            summary_data={
                "earned_salary": "5000000.00",
                "total_sales": "92570000.00",
                "successful_sales": "41000000.00",
                "otkaz_sales": "52755000.00",
                "v_proc_sales": "0.00",
                "successful_orders": 47,
                "conversion_rate": 0.4429,
                "real_conversion_rate": 0.4429,
            },
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
                "earned_salary": "4800000.00",
                "total_sales": "80000000.00",
                "successful_sales": "40000000.00",
                "otkaz_sales": "40000000.00",
                "v_proc_sales": "0.00",
                "successful_orders": 40,
                "conversion_rate": 0.50,
                "real_conversion_rate": 0.50,
            },
        )

    def test_format_uzbek_period(self):
        self.assertEqual(format_uzbek_period(date(2026, 6, 1)), "Iyun 2026")
        self.assertEqual(format_uzbek_period(date(2026, 7, 1)), "Iyul 2026")

    def test_money_large_sum(self):
        self.assertEqual(money(Decimal("92570000")), "<b>92\u00a0570\u00a0000 so'm</b>")
        self.assertEqual(money(Decimal("92570000"), bold=False), "92\u00a0570\u00a0000 so'm")

    def test_money_zero(self):
        self.assertEqual(money(Decimal("0")), "<b>0 so'm</b>")
        self.assertEqual(money(Decimal("0"), bold=False), "0 so'm")

    def test_money_none(self):
        self.assertEqual(money(None), MISSING_VALUE_TEXT)
        self.assertEqual(money(None, bold=False), MISSING_VALUE_TEXT)

    def test_no_inline_money_formatting_remaining(self):
        import inspect

        source = inspect.getsource(formatting)
        self.assertNotIn(":,.0f", source)

    def test_card_text_earned_salary(self):
        text = card_text("earned_salary", "Amir Karimov", "A", self.emp.summary_data)
        self.assertIn("Amir Karimov", text)
        self.assertIn("Bo'lim: <b>A</b>", text)
        self.assertIn("Shaxsiy oylik: <b>5\u00a0000\u00a0000 so'm</b>", text)

    def test_card_text_total_sales(self):
        text = card_text("total_sales", "Amir Karimov", "A", self.emp.summary_data)
        self.assertIn("Jami savdo: <b>92\u00a0570\u00a0000 so'm</b>", text)

    def test_card_text_uspeshka(self):
        text = card_text("uspeshka", "Amir Karimov", "A", self.emp.summary_data)
        self.assertIn("Uspeshka summasi: <b>41\u00a0000\u00a0000 so'm</b>", text)
        self.assertIn("Upakovka soni: <b>47 ta</b>", text)
        self.assertIn("Konversiya: <b>44.29%</b>", text)

    def test_card_text_otkaz(self):
        text = card_text("otkaz", "Amir Karimov", "A", self.emp.summary_data)
        self.assertIn("Otkaz summasi: <b>52\u00a0755\u00a0000 so'm</b>", text)

    def test_card_text_v_proc(self):
        text = card_text("v_proc", "Amir Karimov", "A", self.emp.summary_data)
        self.assertIn("Jarayondagi summa: <b>0 so'm</b>", text)

    def test_card_text_missing_value_renders_warning(self):
        incomplete_data = {"earned_salary": None, "total_sales": ""}
        text = card_text("total_sales", "Amir Karimov", "A", incomplete_data)
        self.assertIn("⚠️ Bu ko'rsatkich hisoblanmagan. Rahbaringizga murojaat qiling.", text)

    @patch("apps.telegram_bot.routers.ensure_fresh_data_and_get_timestamp", return_value=("31.07.2026 14:00:00", False))
    async def test_stats_command_sends_xizmatlar_menu(self, _mock_ts):
        message = MagicMock()
        message.from_user.id = 12345678
        message.answer = AsyncMock()

        await employee_stats(message)
        message.answer.assert_called_once()
        text = message.answer.call_args[0][0]
        self.assertIn("XIZMATLAR", text)
        reply_markup = message.answer.call_args[1].get("reply_markup")
        self.assertIsNotNone(reply_markup)

    @patch("apps.telegram_bot.routers.ensure_fresh_data_and_get_timestamp", return_value=("31.07.2026 14:00:00", False))
    async def test_bare_text_message_sends_xizmatlar_menu(self, _mock_ts):
        state = AsyncMock()
        state.get_state = AsyncMock(return_value=None)
        message = MagicMock()
        message.from_user.id = 12345678
        message.text = "0191"
        message.answer = AsyncMock()

        await handle_bare_text_message(message, state)
        message.answer.assert_called_once()
        text = message.answer.call_args[0][0]
        self.assertIn("XIZMATLAR", text)

    @patch("apps.telegram_bot.routers.ensure_fresh_data_and_get_timestamp", return_value=("31.07.2026 14:00:00", False))
    async def test_unbound_callback_returns_error(self, _mock_ts):
        callback = MagicMock()
        callback.from_user.id = 99999999
        callback.data = "xm_menu"
        callback.answer = AsyncMock()

        await handle_xizmatlar_callback(callback)
        callback.answer.assert_called_once_with("Avval Employee ID orqali profilingizni bog'lang.", show_alert=True)

    @patch("apps.telegram_bot.routers.ensure_fresh_data_and_get_timestamp", return_value=("31.07.2026 14:00:00", False))
    async def test_callback_card_navigation(self, _mock_ts):
        callback = MagicMock()
        callback.from_user.id = 12345678
        callback.data = "xm_card:earned_salary"
        callback.message.edit_text = AsyncMock()
        callback.answer = AsyncMock()

        await handle_xizmatlar_callback(callback)
        callback.message.edit_text.assert_called_once()
        text = callback.message.edit_text.call_args[0][0]
        self.assertIn("Shaxsiy oylik: <b>5\u00a0000\u00a0000 so'm</b>", text)
        callback.answer.assert_called_once()

    @patch("apps.telegram_bot.routers.ensure_fresh_data_and_get_timestamp", return_value=("31.07.2026 14:00:00", False))
    async def test_callback_historical_period_selection(self, _mock_ts):
        callback = MagicMock()
        callback.from_user.id = 12345678
        callback.data = "xm_period:2026-06-01"
        callback.message.edit_text = AsyncMock()
        callback.answer = AsyncMock()

        await handle_xizmatlar_callback(callback)
        callback.message.edit_text.assert_called_once()
        text = callback.message.edit_text.call_args[0][0]
        self.assertIn("XIZMATLAR — Iyun 2026", text)

    @patch("apps.telegram_bot.routers.ensure_fresh_data_and_get_timestamp", return_value=("31.07.2026 14:00:00", False))
    async def test_callback_historical_card(self, _mock_ts):
        callback = MagicMock()
        callback.from_user.id = 12345678
        callback.data = "xm_card:earned_salary:2026-06-01"
        callback.message.edit_text = AsyncMock()
        callback.answer = AsyncMock()

        await handle_xizmatlar_callback(callback)
        callback.message.edit_text.assert_called_once()
        text = callback.message.edit_text.call_args[0][0]
        self.assertIn("Oy: <b>Iyun 2026</b>", text)
        self.assertIn("Shaxsiy oylik: <b>4\u00a0800\u00a0000 so'm</b>", text)

    @patch("apps.telegram_bot.routers.ensure_fresh_data_and_get_timestamp", return_value=("31.07.2026 14:00:00", False))
    async def test_half_month_salary_buttons_and_card_rendering(self, _mock_ts):
        self.emp.summary_data["earned_salary_1_15"] = "2500000.00"
        self.emp.summary_data["earned_salary_16_31"] = "2500000.00"
        await self.emp.asave()

        callback = MagicMock()
        callback.from_user.id = 12345678
        callback.data = "xm_card:salary_1_15"
        callback.message.edit_text = AsyncMock()
        callback.answer = AsyncMock()

        await handle_xizmatlar_callback(callback)
        callback.message.edit_text.assert_called_once()
        text = callback.message.edit_text.call_args[0][0]
        self.assertIn("1 - 15 kunlik oylik hisoboti", text)
        self.assertIn("1-15 kunlik oylik: <b>2\u00a0500\u00a0000 so'm</b>", text)

        reply_markup = callback.message.edit_text.call_args[1]["reply_markup"]
        button_texts = [b.text for row in reply_markup.inline_keyboard for b in row]
        self.assertIn("📅 1-15 kunlik oylik", button_texts)
        self.assertIn("📅 16-31 kunlik oylik", button_texts)
        self.assertIn("💵 Jami oylik", button_texts)


