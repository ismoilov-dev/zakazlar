from unittest.mock import AsyncMock

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from asgiref.sync import sync_to_async
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import TelegramAccount
from apps.employees.models import Employee
from apps.groups.models import SalesGroup
from apps.telegram_bot.routers import (
    RegistrationStates,
    confirm_no,
    confirm_yes,
    process_employee_id,
    process_name,
    role_selected,
    start,
)


class RegistrationFlowTestCase(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.storage = MemoryStorage()
        self.employee1 = Employee.objects.create(
            employee_id="0001",
            full_name="Elbek Xaydarov",
            is_active=True,
        )
        self.employee2 = Employee.objects.create(
            employee_id="0002",
            full_name="Shuhrat Karimov",
            is_active=True,
        )
        self.group = SalesGroup.objects.create(
            code="GRP1",
            name="Group 1",
            leader=self.employee1,
            is_active=True,
        )

    def _get_fsm_context(self, user_id: int) -> FSMContext:
        key = StorageKey(bot_id=123, chat_id=user_id, user_id=user_id)
        return FSMContext(storage=self.storage, key=key)

    async def test_start_unbound_user_shows_role_buttons(self) -> None:
        message = AsyncMock()
        message.from_user.id = 10001
        message.answer.return_value.message_id = 999
        state = self._get_fsm_context(10001)

        await start(message, state)

        self.assertEqual(await state.get_state(), RegistrationStates.select_role.state)
        message.answer.assert_called_once()
        args, _ = message.answer.call_args
        self.assertIn("rolingizni tanlang", args[0])
        self.assertEqual((await state.get_data()).get("bot_message_id"), 999)

    async def test_edit_failure_logs_warning_and_falls_back_to_new_message(self) -> None:
        from unittest.mock import patch
        state = self._get_fsm_context(10002)
        await state.update_data(bot_message_id=123)
        await state.set_state(RegistrationStates.enter_id)

        msg = AsyncMock()
        msg.from_user.id = 10002
        msg.text = "0001"
        msg.chat.id = 10002
        msg.bot.edit_message_text.side_effect = Exception("Message to edit not found")
        msg.answer.return_value.message_id = 456

        with patch("apps.telegram_bot.routers.logger.warning") as mock_warn:
            await process_employee_id(msg, state)
            mock_warn.assert_called_once()
            msg.answer.assert_called_once()
            self.assertEqual((await state.get_data()).get("bot_message_id"), 456)

    async def test_start_already_bound_user_shows_existing_info(self) -> None:
        await sync_to_async(TelegramAccount.objects.create)(
            employee=self.employee1, telegram_id=10002, username="bound_user"
        )
        message = AsyncMock()
        message.from_user.id = 10002
        state = self._get_fsm_context(10002)

        await start(message, state)

        self.assertIsNone(await state.get_state())
        message.answer.assert_called_once()
        args, _ = message.answer.call_args
        self.assertIn("Elbek Xaydarov", args[0])
        self.assertIn("0001", args[0])

    async def test_role_selected_sets_state_and_asks_for_id(self) -> None:
        callback = AsyncMock()
        callback.from_user.id = 10003
        callback.data = "role_MOP"
        state = self._get_fsm_context(10003)
        await state.set_state(RegistrationStates.select_role)

        await role_selected(callback, state)

        self.assertEqual(await state.get_state(), RegistrationStates.enter_id.state)
        data = await state.get_data()
        self.assertEqual(data.get("role"), "MOP")

    async def test_unknown_id_replies_not_found(self) -> None:
        message = AsyncMock()
        message.from_user.id = 10004
        message.text = "9999"
        state = self._get_fsm_context(10004)
        await state.set_state(RegistrationStates.enter_id)

        await process_employee_id(message, state)

        message.answer.assert_called_once()
        args, _ = message.answer.call_args
        self.assertIn("topilmadi", args[0])
        # Name MUST NOT be revealed
        self.assertNotIn("Elbek", args[0])

    async def test_id_already_bound_to_another_account(self) -> None:
        await sync_to_async(TelegramAccount.objects.create)(
            employee=self.employee1, telegram_id=8888, username="other_user"
        )
        message = AsyncMock()
        message.from_user.id = 10005
        message.text = "0001"
        state = self._get_fsm_context(10005)
        await state.set_state(RegistrationStates.enter_id)

        await process_employee_id(message, state)

        message.answer.assert_called_once()
        args, _ = message.answer.call_args
        self.assertIn("boshqa Telegram profiliga bog'langan", args[0])

    async def test_name_mismatch_increments_failure_and_prompts_retry(self) -> None:
        message = AsyncMock()
        message.from_user.id = 10006
        message.text = "Wrong Name"
        state = self._get_fsm_context(10006)
        await state.set_state(RegistrationStates.enter_name)
        await state.update_data(employee_id="0001", sheet_name="Elbek Xaydarov")

        await process_name(message, state)

        message.answer.assert_called_once()
        args, _ = message.answer.call_args
        self.assertIn("mos kelmadi", args[0])
        self.assertEqual(await state.get_state(), RegistrationStates.enter_name.state)

    async def test_rate_limit_blocks_after_three_failures(self) -> None:
        user_id = 10007
        state = self._get_fsm_context(user_id)
        await state.update_data(employee_id="0001", sheet_name="Elbek Xaydarov")

        for i in range(3):
            msg = AsyncMock()
            msg.from_user.id = user_id
            msg.text = f"Wrong Name {i}"
            msg.chat.id = user_id
            msg.answer.return_value.message_id = 100 + i
            await state.set_state(RegistrationStates.enter_name)
            await process_name(msg, state)

        msg4 = AsyncMock()
        msg4.from_user.id = user_id
        msg4.text = "Wrong Name 4"
        msg4.chat.id = user_id
        await process_name(msg4, state)

        msg4.bot.edit_message_text.assert_called_once()
        _, edit_kwargs = msg4.bot.edit_message_text.call_args
        self.assertIn("Administrator bilan bog'laning", edit_kwargs.get("text"))
        self.assertIsNone(await state.get_state())

    async def test_confirm_no_leaves_no_binding(self) -> None:
        callback = AsyncMock()
        callback.from_user.id = 10008
        state = self._get_fsm_context(10008)
        await state.set_state(RegistrationStates.confirm)
        await state.update_data(employee_id="0001", sheet_name="Elbek Xaydarov", role="MOP")

        await confirm_no(callback, state)

        exists = await sync_to_async(TelegramAccount.objects.filter(telegram_id=10008).exists)()
        self.assertFalse(exists)
        self.assertIsNone(await state.get_state())

    async def test_confirm_yes_mop_creates_binding(self) -> None:
        callback = AsyncMock()
        callback.from_user.id = 10009
        callback.from_user.username = "mop_user"
        state = self._get_fsm_context(10009)
        await state.set_state(RegistrationStates.confirm)
        await state.update_data(employee_id="0002", sheet_name="Shuhrat Karimov", role="MOP")

        await confirm_yes(callback, state)

        acct = await sync_to_async(TelegramAccount.objects.get)(telegram_id=10009)
        self.assertEqual(acct.employee_id, self.employee2.id)
        self.assertEqual(acct.role, "MOP")
        self.assertIsNone(await state.get_state())

    async def test_confirm_yes_rop_who_leads_group(self) -> None:
        callback = AsyncMock()
        callback.from_user.id = 10010
        callback.from_user.username = "rop_leader"
        state = self._get_fsm_context(10010)
        await state.set_state(RegistrationStates.confirm)
        await state.update_data(employee_id="0001", sheet_name="Elbek Xaydarov", role="ROP")

        await confirm_yes(callback, state)

        self.assertEqual(await state.get_state(), RegistrationStates.enter_password.state)
        exists = await sync_to_async(TelegramAccount.objects.filter(telegram_id=10010).exists)()
        self.assertFalse(exists)

    async def test_confirm_yes_rop_who_leads_none(self) -> None:
        callback = AsyncMock()
        callback.from_user.id = 10011
        callback.from_user.username = "rop_no_leader"
        state = self._get_fsm_context(10011)
        await state.set_state(RegistrationStates.confirm)
        await state.update_data(employee_id="0002", sheet_name="Shuhrat Karimov", role="ROP")

        await confirm_yes(callback, state)

        self.assertEqual(await state.get_state(), RegistrationStates.enter_password.state)
        exists = await sync_to_async(TelegramAccount.objects.filter(telegram_id=10011).exists)()
        self.assertFalse(exists)


    async def test_rebind_after_admin_deletion_succeeds(self) -> None:
        await sync_to_async(TelegramAccount.objects.create)(
            employee=self.employee1, telegram_id=55555, username="user55"
        )
        await sync_to_async(TelegramAccount.objects.filter(telegram_id=55555).delete)()

        message = AsyncMock()
        message.from_user.id = 55555
        state = self._get_fsm_context(55555)

        await start(message, state)

        self.assertEqual(await state.get_state(), RegistrationStates.select_role.state)
        message.answer.assert_called_once()
        args, _ = message.answer.call_args
        self.assertIn("rolingizni tanlang", args[0])

    async def test_registration_lifecycle_single_message_and_user_deletion(self) -> None:
        user_id = 90001
        state = self._get_fsm_context(user_id)

        # 1. /start
        msg_start = AsyncMock()
        msg_start.from_user.id = user_id
        msg_start.answer.return_value.message_id = 555
        await start(msg_start, state)
        self.assertEqual((await state.get_data()).get("bot_message_id"), 555)

        # 2. role_selected
        cb_role = AsyncMock()
        cb_role.from_user.id = user_id
        cb_role.data = "role_MOP"
        cb_role.message.message_id = 555
        await role_selected(cb_role, state)
        cb_role.message.edit_text.assert_called_once()

        # 3. process_employee_id (valid ID 0002)
        msg_id = AsyncMock()
        msg_id.from_user.id = user_id
        msg_id.text = "0002"
        msg_id.chat.id = user_id
        await process_employee_id(msg_id, state)
        msg_id.delete.assert_called_once()
        msg_id.bot.edit_message_text.assert_called_once()
        edit_args, edit_kwargs = msg_id.bot.edit_message_text.call_args
        self.assertEqual(edit_kwargs.get("message_id"), 555)
        self.assertIn("ism va familiyangizni kiriting", edit_kwargs.get("text"))

        # 4. process_name (matching Shuhrat Karimov)
        msg_name = AsyncMock()
        msg_name.from_user.id = user_id
        msg_name.text = "Shuhrat Karimov"
        msg_name.chat.id = user_id
        await process_name(msg_name, state)
        msg_name.delete.assert_called_once()
        msg_name.bot.edit_message_text.assert_called_once()
        edit_args2, edit_kwargs2 = msg_name.bot.edit_message_text.call_args
        self.assertEqual(edit_kwargs2.get("message_id"), 555)
        self.assertIn("Ma'lumotlar to'g'rimi", edit_kwargs2.get("text"))

        # 5. confirm_yes
        cb_confirm = AsyncMock()
        cb_confirm.from_user.id = user_id
        cb_confirm.from_user.username = "shuhrat_k"
        cb_confirm.data = "confirm_yes"
        cb_confirm.message.message_id = 555
        await confirm_yes(cb_confirm, state)
        cb_confirm.message.edit_text.assert_called_once()
        c_args, c_kwargs = cb_confirm.message.edit_text.call_args
        self.assertIn("Muvaffaqiyatli bog'landi", c_args[0])

        acct = await sync_to_async(TelegramAccount.objects.get)(telegram_id=user_id)
        self.assertEqual(acct.employee_id, self.employee2.id)

    async def test_failing_delete_message_does_not_break_flow(self) -> None:
        user_id = 90002
        state = self._get_fsm_context(user_id)
        await state.update_data(bot_message_id=777)
        await state.set_state(RegistrationStates.enter_id)

        msg_id = AsyncMock()
        msg_id.from_user.id = user_id
        msg_id.text = "0001"
        msg_id.chat.id = user_id
        msg_id.delete.side_effect = Exception("Telegram API Error: message cannot be deleted")

        await process_employee_id(msg_id, state)
        self.assertEqual(await state.get_state(), RegistrationStates.enter_name.state)
        msg_id.bot.edit_message_text.assert_called_once()

    async def test_failed_name_attempt_edits_existing_message(self) -> None:
        user_id = 90003
        state = self._get_fsm_context(user_id)
        await state.update_data(bot_message_id=888, employee_id="0001", sheet_name="Elbek Xaydarov")
        await state.set_state(RegistrationStates.enter_name)

        msg_name = AsyncMock()
        msg_name.from_user.id = user_id
        msg_name.text = "Wrong Person"
        msg_name.chat.id = user_id

        await process_name(msg_name, state)
        msg_name.delete.assert_called_once()
        msg_name.bot.edit_message_text.assert_called_once()
        _, edit_kwargs = msg_name.bot.edit_message_text.call_args
        self.assertIn("mos kelmadi", edit_kwargs.get("text"))
        self.assertEqual(await state.get_state(), RegistrationStates.enter_name.state)

    async def test_start_unbound_user_empty_fsm(self) -> None:
        """/start from an unbound user with empty FSM displays role selection menu."""
        message = AsyncMock()
        message.from_user.id = 80001
        message.answer.return_value.message_id = 101
        state = self._get_fsm_context(80001)

        await start(message, state)

        self.assertEqual(await state.get_state(), RegistrationStates.select_role.state)
        message.answer.assert_called_once()
        text = message.answer.call_args[0][0]
        self.assertIn("rolingizni tanlang", text)
        self.assertNotIn("Xatolik yuz berdi", text)

    async def test_start_bound_user(self) -> None:
        """/start from a bound user displays already registered info and services menu."""
        await sync_to_async(TelegramAccount.objects.create)(
            employee=self.employee2, telegram_id=80002, username="shuhrat"
        )
        message = AsyncMock()
        message.from_user.id = 80002
        state = self._get_fsm_context(80002)

        await start(message, state)

        self.assertIsNone(await state.get_state())
        message.answer.assert_called_once()
        text = message.answer.call_args[0][0]
        self.assertIn("Shuhrat Karimov", text)
        self.assertIn("0002", text)
        self.assertNotIn("Xatolik yuz berdi", text)

    async def test_start_stale_message_id_in_fsm(self) -> None:
        """/start with stale message_id in FSM state clears state and sends usable reply."""
        state = self._get_fsm_context(80003)
        await state.update_data(bot_message_id=99999)
        await state.set_state(RegistrationStates.enter_id)

        message = AsyncMock()
        message.from_user.id = 80003
        message.answer.return_value.message_id = 202

        await start(message, state)

        self.assertEqual(await state.get_state(), RegistrationStates.select_role.state)
        message.answer.assert_called_once()
        text = message.answer.call_args[0][0]
        self.assertIn("rolingizni tanlang", text)
        self.assertNotIn("Xatolik yuz berdi", text)

    async def test_start_employee_leads_two_groups(self) -> None:
        """/start for an employee who leads two active groups produces usable reply without error."""
        emp = await sync_to_async(Employee.objects.create)(
            employee_id="0099", full_name="Multi Group Leader", is_active=True
        )
        await sync_to_async(SalesGroup.objects.create)(code="GRP_A", name="Group A", leader=emp, is_active=True)
        await sync_to_async(SalesGroup.objects.create)(code="GRP_B", name="Group B", leader=emp, is_active=True)
        await sync_to_async(TelegramAccount.objects.create)(
            employee=emp, telegram_id=80004, username="multileader", role="ROP", rop_authenticated_at=timezone.now()
        )

        message = AsyncMock()
        message.from_user.id = 80004
        state = self._get_fsm_context(80004)

        await start(message, state)

        message.answer.assert_called_once()
        text = message.answer.call_args[0][0]
        self.assertIn("Multi Group Leader", text)
        self.assertNotIn("Xatolik yuz berdi", text)

    async def test_start_error_includes_correlation_id_and_clears_state(self) -> None:
        """When an unhandled exception occurs in /start, an 8-hex-char correlation ID is included and FSM is cleared."""
        message = AsyncMock()
        message.from_user.id = 80005
        state = self._get_fsm_context(80005)
        await state.set_state(RegistrationStates.enter_id)

        from unittest.mock import patch
        with patch("apps.telegram_bot.routers.sync_to_async", side_effect=RuntimeError("DB exploded")):
            await start(message, state)

        self.assertIsNone(await state.get_state())
        message.answer.assert_called_once()
        self.assertIn("Xatolik yuz berdi (kod: ", text)
        import re
        match = re.search(r"kod:\s*([0-9a-f]{8})\)", text)
        self.assertIsNotNone(match)

    async def test_process_name_allows_typing_new_id(self) -> None:
        """When user types a valid 4-digit ID in enter_name state, it updates ID smoothly."""
        user_id = 90010
        state = self._get_fsm_context(user_id)
        await state.update_data(employee_id="0001", sheet_name="Elbek Xaydarov")
        await state.set_state(RegistrationStates.enter_name)

        msg = AsyncMock()
        msg.from_user.id = user_id
        msg.text = "0002"
        msg.chat.id = user_id

        await process_name(msg, state)
        self.assertEqual(await state.get_state(), RegistrationStates.enter_name.state)
        data = await state.get_data()
        self.assertEqual(data.get("employee_id"), "0002")
        self.assertEqual(data.get("sheet_name"), "Shuhrat Karimov")

