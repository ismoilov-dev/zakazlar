"""Telegram identity binding use-case."""

from apps.accounts.repositories.telegram_account import TelegramAccountRepository
from apps.common.services.exceptions import NotFoundError
from apps.employees.models import Employee
from apps.employees.repositories.employee import EmployeeRepository


class TelegramBindingService:
    """Bind a Telegram identity to one active Employee ID."""

    def __init__(self, employees: EmployeeRepository | None = None, accounts: TelegramAccountRepository | None = None):
        self.employees = employees or EmployeeRepository()
        self.accounts = accounts or TelegramAccountRepository()

    def bind(self, *, employee_id: str, telegram_id: int, username: str) -> Employee:
        try:
            employee = self.employees.get_active_by_employee_id(employee_id.strip())
        except Employee.DoesNotExist as exc:
            raise NotFoundError("Xodim topilmadi yoki faol emas.") from exc
        self.accounts.bind(employee=employee, telegram_id=telegram_id, username=username)
        return employee
