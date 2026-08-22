"""Telegram identity binding use-case."""

from apps.accounts.models import TelegramAccount
from apps.accounts.repositories.telegram_account import TelegramAccountRepository
from apps.common.services.exceptions import DomainError, NotFoundError
from apps.employees.models import Employee
from apps.employees.repositories.employee import EmployeeRepository


class TelegramBindingService:
    """Bind a Telegram identity to one active Employee ID."""

    def __init__(self, employees: EmployeeRepository | None = None, accounts: TelegramAccountRepository | None = None):
        self.employees = employees or EmployeeRepository()
        self.accounts = accounts or TelegramAccountRepository()

    def bind(self, *, employee_id: str, telegram_id: int, username: str, role: str = "MOP") -> Employee:
        try:
            employee = self.employees.get_active_by_employee_id(employee_id.strip())
        except Employee.DoesNotExist as exc:
            raise NotFoundError("Xodim topilmadi yoki faol emas.") from exc

        existing_account = TelegramAccount.objects.filter(telegram_id=telegram_id).first()
        if existing_account and existing_account.employee_id != employee.id:
            raise DomainError("Sizning Telegram profilingiz allaqachon boshqa xodimga bog'langan. O'zgartirish uchun administratsiyaga murojaat qiling.")

        existing_employee_binding = TelegramAccount.objects.filter(employee=employee).first()
        if existing_employee_binding and existing_employee_binding.telegram_id != telegram_id:
            raise DomainError("Bu Employee ID allaqachon boshqa Telegram profiliga bog'langan. Administratsiyaga murojaat qiling.")

        self.accounts.bind(employee=employee, telegram_id=telegram_id, username=username, role=role)
        return employee


from datetime import timedelta
from django.conf import settings
from django.utils import timezone

SUPER_ADMIN_TELEGRAM_IDS: set[int] = {6971406926}


def is_super_admin(telegram_id: int | str | None) -> bool:
    """Check if a given telegram_id is configured as Super Admin / Global Auditor."""
    if telegram_id is None:
        return False
    try:
        tid = int(telegram_id)
        configured = getattr(settings, "SUPER_ADMIN_TELEGRAM_IDS", SUPER_ADMIN_TELEGRAM_IDS)
        return tid in {int(x) for x in configured}
    except Exception:
        return False


def is_rop_session_valid(account: TelegramAccount | None) -> bool:
    """Check if a ROP's authenticated session is active within ROP_SESSION_HOURS or is Super Admin."""
    if not account:
        return False
    if is_super_admin(account.telegram_id):
        return True
    if not account.rop_authenticated_at:
        return False
    session_hours = getattr(settings, "ROP_SESSION_HOURS", 12)
    expiry = account.rop_authenticated_at + timedelta(hours=session_hours)
    return timezone.now() < expiry


def require_rop_session(account: TelegramAccount | None) -> bool:
    """Single guard function to check ROP session validity."""
    return is_rop_session_valid(account)

