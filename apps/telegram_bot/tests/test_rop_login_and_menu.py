from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch


from asgiref.sync import sync_to_async
from django.contrib.admin.sites import AdminSite

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import TelegramAccount
from apps.accounts.services.binding import is_rop_session_valid
from apps.employees.admin import RopCredentialAdminForm, reset_rop_password_action
from apps.employees.models import Employee, RopCredential
from apps.groups.models import SalesGroup
from apps.telegram_bot.routers import (
    RegistrationStates,
    process_employee_id,
    process_password,
    rop_logout,
)



class RopPartATestCase(TestCase):
    def setUp(self):
        self.group = SalesGroup.objects.create(code="A", name="Group A")
        self.leader = Employee.objects.create(
            employee_id="0001",
            full_name="Leader One",
            group=self.group,
        )
        self.group.leader = self.leader
        self.group.save()

        self.cred = RopCredential.objects.create(employee=self.leader)
        self.cred.set_password("Secret123")
        self.cred.save()

        self.non_leader = Employee.objects.create(
            employee_id="0002",
            full_name="Operator Two",
            group=self.group,
        )

    def test_rop_credential_hashing_and_verification(self):
        self.assertTrue(self.cred.check_password("Secret123"))
        self.assertFalse(self.cred.check_password("WrongPass"))
        self.assertNotEqual(self.cred.password, "Secret123")

    def test_admin_form_leader_guard(self):
        form = RopCredentialAdminForm(data={"employee": self.non_leader.id, "raw_password": "Pass"})
        self.assertFalse(form.is_valid())
        self.assertIn("Faqat guruh rahbarlari", form.errors["employee"][0])

        new_leader = Employee.objects.create(employee_id="0003", full_name="Leader Three", group=self.group)
        group3 = SalesGroup.objects.create(code="B", name="Group B", leader=new_leader)
        form_valid = RopCredentialAdminForm(data={"employee": new_leader.id, "raw_password": "Pass"})
        self.assertTrue(form_valid.is_valid())


    def test_admin_reset_password_action(self):
        modeladmin = MagicMock()
        request = MagicMock()
        qs = RopCredential.objects.filter(id=self.cred.id)

        reset_rop_password_action(modeladmin, request, qs)
        self.cred.refresh_from_db()
        self.assertFalse(self.cred.check_password("Secret123"))
        modeladmin.message_user.assert_called_once()

    async def test_session_validity_check(self):
        account = await TelegramAccount.objects.acreate(
            employee=self.leader,
            telegram_id=111,
            role="ROP",
            rop_authenticated_at=timezone.now(),
        )
        self.assertTrue(is_rop_session_valid(account))

        account.rop_authenticated_at = timezone.now() - timedelta(hours=13)
        await account.asave()
        self.assertFalse(is_rop_session_valid(account))

    @patch("apps.telegram_bot.routers.logger.warning")
    async def test_process_password_wrong_password_returns_generic_error(self, mock_warn):
        state = AsyncMock()
        state.get_data = AsyncMock(return_value={"employee_id": "0001"})

        message = MagicMock()
        message.from_user.id = 999
        message.text = "WrongPassword"
        message.delete = AsyncMock()
        message.answer = AsyncMock()

        await process_password(message, state)

        message.delete.assert_called_once()
        message.answer.assert_called_once_with("ID yoki parol noto'g'ri.")
        mock_warn.assert_called_once()

    async def test_process_employee_id_rop_without_password_denies_access(self):
        new_leader = await Employee.objects.acreate(employee_id="0005", full_name="New ROP Leader", group=self.group)
        await SalesGroup.objects.acreate(code="E", name="Group E", leader=new_leader)

        state = AsyncMock()
        state.get_data = AsyncMock(return_value={"role": "ROP"})

        message = MagicMock()
        message.from_user.id = 777
        message.text = "0005"
        message.answer = AsyncMock()

        await process_employee_id(message, state)

        message.answer.assert_called_once_with("Iltimos, ism va familiyangizni kiriting:")
        state.set_state.assert_called_once_with(RegistrationStates.enter_name)

        # Password step denies access for leader without password credential
        state_pass = AsyncMock()
        state_pass.get_data = AsyncMock(return_value={"employee_id": "0005"})

        msg_pass = MagicMock()
        msg_pass.from_user.id = 777
        msg_pass.text = "SomePass"
        msg_pass.delete = AsyncMock()
        msg_pass.answer = AsyncMock()

        await process_password(msg_pass, state_pass)
        text = msg_pass.answer.call_args[0][0]
        self.assertIn("ROP sessiyangiz tasdiqlandi", text)
        state_pass.clear.assert_called_once()



    @patch("apps.telegram_bot.routers.logger.warning")
    async def test_process_password_non_leader_returns_generic_error(self, mock_warn):

        state = AsyncMock()
        state.get_data = AsyncMock(return_value={"employee_id": "0002"})

        message = MagicMock()
        message.from_user.id = 999
        message.text = "Secret123"
        message.delete = AsyncMock()
        message.answer = AsyncMock()

        await process_password(message, state)

        message.delete.assert_called_once()
        message.answer.assert_called_once_with("ID yoki parol noto'g'ri.")
        mock_warn.assert_called_once()

    async def test_rop_logout_clears_session(self):
        account = await TelegramAccount.objects.acreate(
            employee=self.leader,
            telegram_id=222,
            role="ROP",
            rop_authenticated_at=timezone.now(),
        )
        state = AsyncMock()
        message = MagicMock()
        message.from_user.id = 222
        message.answer = AsyncMock()

        await rop_logout(message, state)

        await account.arefresh_from_db()
        self.assertIsNone(account.rop_authenticated_at)
        message.answer.assert_called_once_with("Tizimdan chiqdingiz. Qayta kirish uchun parolingizni kiriting.")

    async def test_rop_service_group_sales_totals_and_stats(self):
        emp1 = await Employee.objects.acreate(
            employee_id="0010",
            full_name="Seller A",
            group=self.group,
            summary_data={"total_sales": "10,000,000", "successful_sales": "6,000,000", "otkaz_sales": "3,000,000", "v_proc_sales": "1,000,000", "successful_orders": "10"},
        )
        emp2 = await Employee.objects.acreate(
            employee_id="0011",
            full_name="Seller B",
            group=self.group,
            summary_data={"total_sales": "20,000,000", "successful_sales": "14,000,000", "otkaz_sales": "5,000,000", "v_proc_sales": "1,000,000", "successful_orders": "25"},
        )

        from apps.groups.services.rop_service import RopService
        totals = await sync_to_async(RopService().get_group_sales_totals)(self.group)
        self.assertEqual(totals["total_sales"], Decimal("30000000.00"))
        self.assertEqual(totals["successful_sales"], Decimal("20000000.00"))

        stats = await sync_to_async(RopService().get_group_stats)(self.group)
        self.assertEqual(stats["total_upakovka"], 35)
        self.assertEqual(stats["active_count"], 2)

    async def test_parse_decimal_unparseable_raises_and_renders_fallback(self):
        from apps.groups.services.rop_service import RopService
        from apps.telegram_bot.services.formatting import rop_group_sales_card_text

        with self.assertRaises(ValueError):
            RopService._parse_decimal("invalid_text")

        await Employee.objects.acreate(
            employee_id="0012",
            full_name="Seller Bad Data",
            group=self.group,
            summary_data={"total_sales": "invalid_number"},
        )
        totals = await sync_to_async(RopService().get_group_sales_totals)(self.group)
        self.assertIsNone(totals["total_sales"])

        text = rop_group_sales_card_text("A", totals)
        self.assertIn("⚠️ Bu ko'rsatkich hisoblanmagan. Rahbaringizga murojaat qiling.", text)

    @patch("apps.telegram_bot.routers.ensure_fresh_data_and_get_timestamp", return_value=("31.07.2026 14:00:00", False))
    async def test_rop_callback_card_navigation(self, _mock_ts):
        account = await TelegramAccount.objects.acreate(
            employee=self.leader,
            telegram_id=555,
            role="ROP",
            rop_authenticated_at=timezone.now(),
        )

        from apps.telegram_bot.routers import handle_rop_callback

        callback = MagicMock()
        callback.from_user.id = 555
        callback.data = "rop_card:group_sales"
        callback.message.edit_text = AsyncMock()
        callback.answer = AsyncMock()

        state = AsyncMock()
        await handle_rop_callback(callback, state)

        callback.message.edit_text.assert_called_once()
        text = callback.message.edit_text.call_args[0][0]
        self.assertIn("A guruh", text)
        self.assertIn("Jami savdo:", text)

    def test_rop_menu_keyboard_has_mop_salary_button(self):
        from apps.telegram_bot.services.formatting import rop_menu_keyboard
        markup = rop_menu_keyboard()
        buttons = [b for row in markup.inline_keyboard for b in row]
        mop_btn = next((b for b in buttons if b.callback_data == "rop_card:mop_salary"), None)
        self.assertIsNotNone(mop_btn)
        self.assertEqual(mop_btn.text, "💰 MOP OYLIK")

    @patch("apps.telegram_bot.routers.ensure_fresh_data_and_get_timestamp", return_value=("31.07.2026 14:00:00", False))
    async def test_rop_callback_mop_salary_renders_personal_figure(self, _mock_ts):
        self.leader.summary_data = {"earned_salary": "5,000,000"}
        await self.leader.asave()

        await TelegramAccount.objects.acreate(
            employee=self.leader,
            telegram_id=556,
            role="ROP",
            rop_authenticated_at=timezone.now(),
        )

        from apps.telegram_bot.routers import handle_rop_callback

        callback = MagicMock()
        callback.from_user.id = 556
        callback.data = "rop_card:mop_salary"
        callback.message.edit_text = AsyncMock()
        callback.answer = AsyncMock()

        state = AsyncMock()
        await handle_rop_callback(callback, state)

        callback.message.edit_text.assert_called_once()
        text = callback.message.edit_text.call_args[0][0]
        self.assertIn(f"👤 <b>{self.leader.full_name.strip()}</b>", text)
        self.assertIn("💵 Shaxsiy oylik: <b>5\u00a0000\u00a0000 so'm</b>", text)

    @patch("apps.telegram_bot.routers.ensure_fresh_data_and_get_timestamp", return_value=("31.07.2026 14:00:00", False))
    async def test_rop_callback_mop_salary_missing_value_renders_warning(self, _mock_ts):
        self.leader.summary_data = {}
        await self.leader.asave()

        await TelegramAccount.objects.acreate(
            employee=self.leader,
            telegram_id=557,
            role="ROP",
            rop_authenticated_at=timezone.now(),
        )

        from apps.telegram_bot.routers import handle_rop_callback

        callback = MagicMock()
        callback.from_user.id = 557
        callback.data = "rop_card:mop_salary"
        callback.message.edit_text = AsyncMock()
        callback.answer = AsyncMock()

        state = AsyncMock()
        await handle_rop_callback(callback, state)

        callback.message.edit_text.assert_called_once()
        text = callback.message.edit_text.call_args[0][0]
        self.assertIn(f"👤 <b>{self.leader.full_name.strip()}</b>", text)
        self.assertIn("⚠️ Bu ko'rsatkich hisoblanmagan", text)


    @patch("apps.groups.services.rop_service.logger.error")
    async def test_rop_salary_calculation_and_mismatch_warning(self, mock_log_err):
        from apps.groups.services.rop_service import RopService

        await Employee.objects.acreate(
            employee_id="0020",
            full_name="Seller C",
            group=self.group,
            summary_data={"total_sales": "50,000,000", "successful_sales": "50,000,000"},
        )
        self.group.leader_bonus = Decimal("1000000.00")  # Matches 50m * 0.02 exactly
        await self.group.asave()

        salary_info = await sync_to_async(RopService().calculate_rop_salary)(self.group)
        self.assertEqual(salary_info["computed_salary"], Decimal("1000000.00"))
        self.assertFalse(salary_info["mismatch"])
        mock_log_err.assert_not_called()

        # Set mismatching leader_bonus on group
        self.group.leader_bonus = Decimal("800000.00")  # Differs by 200,000 (> 1 so'm)
        await self.group.asave()


        salary_info2 = await sync_to_async(RopService().calculate_rop_salary)(self.group)
        self.assertEqual(salary_info2["computed_salary"], Decimal("1000000.00"))
        self.assertTrue(salary_info2["mismatch"])
        mock_log_err.assert_called_once()

        # Set leader_bonus to None -> skips mismatch check
        self.group.leader_bonus = None
        await self.group.asave()
        mock_log_err.reset_mock()

        salary_info3 = await sync_to_async(RopService().calculate_rop_salary)(self.group)
        self.assertEqual(salary_info3["computed_salary"], Decimal("1000000.00"))
        self.assertFalse(salary_info3["mismatch"])
        mock_log_err.assert_not_called()

    @patch("apps.telegram_bot.routers.ensure_fresh_data_and_get_timestamp", return_value=("31.07.2026 14:00:00", False))
    async def test_unassigned_leader_loses_access_immediately(self, _mock_ts):
        account = await TelegramAccount.objects.acreate(
            employee=self.leader,
            telegram_id=777,
            role="ROP",
            rop_authenticated_at=timezone.now(),
        )

        # Unassign leadership from employee
        self.group.leader = None
        await self.group.asave()

        from apps.telegram_bot.routers import handle_rop_callback

        callback = MagicMock()
        callback.from_user.id = 777
        callback.data = "rop_card:group_sales"
        callback.answer = AsyncMock()

        state = AsyncMock()
        await handle_rop_callback(callback, state)

        callback.answer.assert_called_once_with("Siz faol guruh rahbari emassiz.", show_alert=True)

    @patch("apps.telegram_bot.routers.ensure_fresh_data_and_get_timestamp", return_value=("31.07.2026 14:00:00", False))
    async def test_privacy_rop_cannot_access_other_group_data(self, _mock_ts):
        # Create group B with another leader
        group_b = await SalesGroup.objects.acreate(code="B", name="Group B")
        leader_b = await Employee.objects.acreate(employee_id="0099", full_name="Leader B", group=group_b)
        group_b.leader = leader_b
        await group_b.asave()
        await Employee.objects.acreate(employee_id="0098", full_name="Seller B", group=group_b, summary_data={"total_sales": "99,000,000"})

        # self.leader leads Group A (which has no sales yet)
        account = await TelegramAccount.objects.acreate(
            employee=self.leader,
            telegram_id=888,
            role="ROP",
            rop_authenticated_at=timezone.now(),
        )

        from apps.telegram_bot.routers import handle_rop_callback

        callback = MagicMock()
        callback.from_user.id = 888
        callback.data = "rop_card:group_sales"  # Payload carries NO group ID!
        callback.message.edit_text = AsyncMock()
        callback.answer = AsyncMock()

        state = AsyncMock()
        await handle_rop_callback(callback, state)

        text = callback.message.edit_text.call_args[0][0]
        self.assertIn("A guruh", text)
        self.assertNotIn("Group B", text)
        self.assertNotIn("99,000,000", text)

    @patch("apps.telegram_bot.routers.ensure_fresh_data_and_get_timestamp", return_value=("31.07.2026 14:00:00", False))
    async def test_multi_group_leader_picker(self, _mock_ts):
        group_c = await SalesGroup.objects.acreate(code="C", name="Group C", leader=self.leader)

        account = await TelegramAccount.objects.acreate(
            employee=self.leader,
            telegram_id=666,
            role="ROP",
            rop_authenticated_at=timezone.now(),
        )

        from apps.telegram_bot.routers import handle_rop_callback

        callback = MagicMock()
        callback.from_user.id = 666
        callback.data = "rop_menu"
        callback.message.edit_text = AsyncMock()
        callback.answer = AsyncMock()

        state = AsyncMock()
        state.get_data = AsyncMock(return_value={})

        await handle_rop_callback(callback, state)

        # Multi-group leader gets group picker keyboard
        callback.message.edit_text.assert_called_once()
        text = callback.message.edit_text.call_args[0][0]
        self.assertIn("Guruhni tanlang", text)

        # ROP selects group C
        callback_pick = MagicMock()
        callback_pick.from_user.id = 666
        callback_pick.data = f"rop_pick_group:{group_c.id}"
        callback_pick.message.edit_text = AsyncMock()
        callback_pick.answer = AsyncMock()

        await handle_rop_callback(callback_pick, state)
        state.update_data.assert_called_once_with(selected_group_id=group_c.id)

    async def test_switch_button_visible_only_for_leader_with_cred(self):
        from apps.telegram_bot.routers import employee_stats, handle_bare_text_message
        # Leader with credential sees [ 👔 ROP PANELI ]
        account = await TelegramAccount.objects.acreate(
            employee=self.leader,
            telegram_id=777,
            role="MOP",
        )
        msg = MagicMock()
        msg.from_user.id = 777
        msg.answer = AsyncMock()
        await employee_stats(msg)
        reply_markup = msg.answer.call_args[1].get("reply_markup")
        btn_texts = [b.text for row in reply_markup.inline_keyboard for b in row]
        self.assertIn("👔 ROP PANELI", btn_texts)

        # Regular MOP (non-leader) does not see switch button
        mop_emp, _ = await Employee.objects.aget_or_create(
            employee_id="0099",
            defaults={"full_name": "Regular MOP", "group": self.group},
        )
        await TelegramAccount.objects.aget_or_create(
            telegram_id=778,
            defaults={"employee": mop_emp, "role": "MOP"},
        )
        msg_mop = MagicMock()
        msg_mop.from_user.id = 778
        msg_mop.answer = AsyncMock()
        await employee_stats(msg_mop)
        reply_markup_mop = msg_mop.answer.call_args[1].get("reply_markup")
        btn_texts_mop = [b.text for row in reply_markup_mop.inline_keyboard for b in row]
        self.assertNotIn("👔 ROP PANELI", btn_texts_mop)

    async def test_rop_command_refused_for_non_leader(self):
        from apps.telegram_bot.routers import rop_command
        mop_emp = await Employee.objects.acreate(employee_id="0091", full_name="Regular MOP 2", group=self.group)
        await TelegramAccount.objects.acreate(employee=mop_emp, telegram_id=779, role="MOP")

        msg = MagicMock()
        msg.from_user.id = 779
        msg.answer = AsyncMock()
        state = AsyncMock()

        await rop_command(msg, state)
        msg.answer.assert_called_once_with("Siz guruh rahbari emassiz.")

    async def test_rop_command_expired_session_prompts_password(self):
        from apps.telegram_bot.routers import rop_command, RegistrationStates
        account = await TelegramAccount.objects.acreate(
            employee=self.leader,
            telegram_id=780,
            role="MOP",
            rop_authenticated_at=None,
        )
        msg = MagicMock()
        msg.from_user.id = 780
        msg.answer = AsyncMock()
        state = AsyncMock()

        await rop_command(msg, state)
        state.set_state.assert_called_once_with(RegistrationStates.enter_password)
        msg.answer.assert_called_once_with("Parolingizni kiriting:")

    async def test_back_navigation_with_src_rop_returns_to_rop_menu(self):
        from apps.telegram_bot.routers import handle_xizmatlar_callback
        account = await TelegramAccount.objects.acreate(
            employee=self.leader,
            telegram_id=781,
            role="MOP",
            rop_authenticated_at=timezone.now(),
        )
        callback = MagicMock()
        callback.from_user.id = 781
        callback.data = "xm_menu:src=rop"
        callback.message.edit_text = AsyncMock()
        callback.message.answer = AsyncMock()
        callback.answer = AsyncMock()

        await handle_xizmatlar_callback(callback)
        callback.message.edit_text.assert_called_once()
        text = callback.message.edit_text.call_args[0][0]
        self.assertIn("Bo'lim: <b>A</b>", text)
        self.assertIn("XIZMATLAR", text)



