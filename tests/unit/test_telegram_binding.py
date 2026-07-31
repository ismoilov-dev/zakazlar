from django.test import TestCase

from apps.accounts.models import TelegramAccount
from apps.accounts.services.binding import TelegramBindingService
from apps.employees.models import Employee


class TelegramBindingTestCase(TestCase):
    def setUp(self) -> None:
        self.employee1 = Employee.objects.create(
            employee_id="0001",
            full_name="Ali Valiyev",
            is_active=True,
        )
        self.employee2 = Employee.objects.create(
            employee_id="0002",
            full_name="Hasan Husanov",
            is_active=True,
        )
        self.service = TelegramBindingService()

    def test_multiple_users_binding_do_not_overwrite_each_other(self) -> None:
        # User 1 (telegram_id 1001) binds to Employee 0001
        self.service.bind(employee_id="0001", telegram_id=1001, username="user1")

        # User 2 (telegram_id 1002) binds to Employee 0002
        self.service.bind(employee_id="0002", telegram_id=1002, username="user2")

        # Verify BOTH accounts exist and are bound correctly
        self.assertTrue(TelegramAccount.objects.filter(telegram_id=1001, employee=self.employee1).exists())
        self.assertTrue(TelegramAccount.objects.filter(telegram_id=1002, employee=self.employee2).exists())
        self.assertEqual(TelegramAccount.objects.count(), 2)

    def test_user_rebinds_updates_own_account(self) -> None:
        from apps.common.services.exceptions import DomainError
        # User 1 binds to 0001
        self.service.bind(employee_id="0001", telegram_id=1001, username="user1")

        # User 1 attempting to change binding to 0002 is rejected
        with self.assertRaises(DomainError):
            self.service.bind(employee_id="0002", telegram_id=1001, username="user1_new")

    def test_deletion_from_admin_removes_binding(self) -> None:
        self.service.bind(employee_id="0001", telegram_id=1001, username="user1")
        self.assertEqual(TelegramAccount.objects.count(), 1)

        # Admin deletes account
        TelegramAccount.objects.filter(telegram_id=1001).delete()

        self.assertEqual(TelegramAccount.objects.count(), 0)

    def test_bind_saves_role(self) -> None:
        account1 = self.service.bind(employee_id="0001", telegram_id=1001, username="user1", role="ROP")
        acct = TelegramAccount.objects.get(telegram_id=1001)
        self.assertEqual(acct.role, "ROP")
