from django.test import TestCase

from apps.accounts.services.binding import TelegramBindingService
from apps.common.services.exceptions import DomainError
from apps.employees.models import Employee


class OneTimeBindingTest(TestCase):
    def setUp(self):
        self.emp1 = Employee.objects.create(employee_id="0191", full_name="Amir Karimov")
        self.emp2 = Employee.objects.create(employee_id="0192", full_name="Feruza Boymo'minova")
        self.service = TelegramBindingService()

    def test_telegram_account_cannot_rebind_to_second_employee(self):
        """Telegram account 111 bound to 0191 cannot re-bind to 0192."""
        self.service.bind(employee_id="0191", telegram_id=111, username="user1")

        with self.assertRaises(DomainError) as ctx:
            self.service.bind(employee_id="0192", telegram_id=111, username="user1")
        self.assertIn("boshqa xodimga bog'langan", str(ctx.exception))

    def test_employee_id_cannot_bind_to_second_telegram_account(self):
        """Employee 0191 bound to telegram 111 cannot be bound to telegram 222."""
        self.service.bind(employee_id="0191", telegram_id=111, username="user1")

        with self.assertRaises(DomainError) as ctx:
            self.service.bind(employee_id="0191", telegram_id=222, username="user2")
        self.assertIn("boshqa Telegram profiliga bog'langan", str(ctx.exception))

    def test_idempotent_rebinding_same_telegram_and_employee_succeeds(self):
        """Re-binding same Telegram 111 to same 0191 succeeds without error."""
        self.service.bind(employee_id="0191", telegram_id=111, username="user1")
        res = self.service.bind(employee_id="0191", telegram_id=111, username="user1")
        self.assertEqual(res.employee_id, "0191")
