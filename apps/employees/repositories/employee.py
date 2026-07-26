"""ORM repository for employee records."""

from django.db import transaction

from apps.common.repositories.base import DjangoRepository
from apps.employees.models import Employee
from apps.groups.models import SalesGroup


class EmployeeRepository(DjangoRepository[Employee]):
    """Encapsulate employee lookup and import-time persistence."""

    model = Employee

    def get_active_by_employee_id(self, employee_id: str) -> Employee:
        return self.model.objects.select_related("group").get(employee_id=employee_id, is_active=True)

    def get_by_employee_id(self, employee_id: str) -> Employee:
        return self.model.objects.select_related("group").get(employee_id=employee_id)

    @transaction.atomic
    def upsert(
        self, *, employee_id: str, full_name: str, group: SalesGroup, monthly_salary: object | None = None
    ) -> Employee:
        defaults: dict[str, object] = {"full_name": full_name, "group": group, "is_active": True}
        if monthly_salary is not None:
            defaults["monthly_salary"] = monthly_salary
        employee, _ = self.model.objects.update_or_create(
            employee_id=employee_id,
            defaults=defaults,
        )
        return employee
