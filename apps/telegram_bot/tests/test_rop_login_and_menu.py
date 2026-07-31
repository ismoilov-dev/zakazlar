from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

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
