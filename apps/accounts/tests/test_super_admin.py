"""Unit tests for Super Admin / Global Auditor role."""
from django.test import TestCase
from apps.accounts.models import TelegramAccount
from apps.accounts.services.binding import is_super_admin, is_rop_session_valid, get_or_create_super_admin_account


class SuperAdminTestCase(TestCase):
    """Test Super Admin bypass logic."""

    def test_is_super_admin_function(self):
        self.assertTrue(is_super_admin(6971406926))
        self.assertTrue(is_super_admin("6971406926"))
        self.assertFalse(is_super_admin(123456789))
        self.assertFalse(is_super_admin(None))

    def test_get_or_create_super_admin_account(self):
        acc = get_or_create_super_admin_account(6971406926)
        self.assertIsNotNone(acc)
        self.assertIsNotNone(acc.employee)
        self.assertEqual(acc.employee.employee_id, "SUPERADMIN")
        self.assertEqual(acc.role, "ROP")

    def test_super_admin_bypasses_rop_session_expiry(self):
        emp = Employee.objects.create(employee_id="9999", full_name="UzSardorbek", is_active=True)
        acc = TelegramAccount.objects.create(
            employee=emp,
            telegram_id=6971406926,
            role="ROP",
            rop_authenticated_at=None,
        )
        self.assertTrue(is_rop_session_valid(acc))
