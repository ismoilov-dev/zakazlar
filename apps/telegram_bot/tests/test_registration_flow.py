from unittest.mock import AsyncMock

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from asgiref.sync import sync_to_async
from django.core.cache import cache
from django.test import TestCase

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
        state = self._get_fsm_context(10001)

        await start(message, state)

        self.assertEqual(await state.get_state(), RegistrationStates.select_role.state)
        message.answer.assert_called_once()
        args, _ = message.answer.call_args
        self.assertIn("rolingizni tanlang", args[0])

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
        self.assertEqual(await state.get_state(), RegistrationStates.enter_id.state)

    async def test_rate_limit_blocks_after_three_failures(self) -> None:
        user_id = 10007
        state = self._get_fsm_context(user_id)
        await state.update_data(employee_id="0001", sheet_name="Elbek Xaydarov")

        for i in range(3):
            msg = AsyncMock()
            msg.from_user.id = user_id
            msg.text = f"Wrong Name {i}"
            await state.set_state(RegistrationStates.enter_name)
            await process_name(msg, state)

        msg4 = AsyncMock()
        msg4.from_user.id = user_id
        msg4.text = "Wrong Name 4"
        await process_name(msg4, state)

        msg4.answer.assert_called_once()
        args, _ = msg4.answer.call_args
        self.assertIn("Administrator bilan bog'laning", args[0])
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

        acct = await sync_to_async(TelegramAccount.objects.get)(telegram_id=10010)
        self.assertEqual(acct.employee_id, self.employee1.id)
        self.assertEqual(acct.role, "ROP")
        args, _ = callback.message.answer.call_args
        self.assertIn("XIZMATLAR", args[0])


    async def test_confirm_yes_rop_who_leads_none(self) -> None:
        callback = AsyncMock()
        callback.from_user.id = 10011
        callback.from_user.username = "rop_no_leader"
        state = self._get_fsm_context(10011)
        await state.set_state(RegistrationStates.confirm)
        await state.update_data(employee_id="0002", sheet_name="Shuhrat Karimov", role="ROP")

        await confirm_yes(callback, state)

        acct = await sync_to_async(TelegramAccount.objects.get)(telegram_id=10011)
        self.assertEqual(acct.employee_id, self.employee2.id)
        self.assertEqual(acct.role, "ROP")
        args, _ = callback.message.answer.call_args
        self.assertIn("ROP paneli tugmasi menyuga qo'shildi", args[0])


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
