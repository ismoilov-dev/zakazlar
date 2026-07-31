"""ORM repository for Telegram account bindings."""

from django.db import transaction

from apps.accounts.models import TelegramAccount
from apps.common.repositories.base import DjangoRepository
from apps.employees.models import Employee


class TelegramAccountRepository(DjangoRepository[TelegramAccount]):
    """Encapsulate Telegram identity persistence and lookup."""

    model = TelegramAccount

    def get_by_telegram_id(self, telegram_id: int) -> TelegramAccount:
        return self.model.objects.select_related("employee", "employee__group").get(telegram_id=telegram_id)

    @transaction.atomic
    def bind(self, *, employee: Employee, telegram_id: int, username: str, role: str = "MOP") -> TelegramAccount:
        account, _ = self.model.objects.update_or_create(
            telegram_id=telegram_id,
            defaults={"employee": employee, "username": username, "role": role},
        )
        return account
