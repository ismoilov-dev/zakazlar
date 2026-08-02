"""ORM repository for employee monthly stat records."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from django.db import transaction

from apps.common.repositories.base import DjangoRepository
from apps.common.services.exceptions import ValidationError
from apps.employees.models import Employee, EmployeeMonthlyStat

logger = logging.getLogger(__name__)


class ClosedPeriodError(ValidationError):
    """Raised when attempting to modify a closed period snapshot without force."""


class EmployeeMonthlyStatRepository(DjangoRepository[EmployeeMonthlyStat]):
    """Encapsulate persistence and immutability guards for monthly stats."""

    model = EmployeeMonthlyStat

    @transaction.atomic
    def upsert_snapshot(
        self,
        *,
        employee: Employee,
        period: date,
        summary_data: dict[str, Any],
        source_spreadsheet_id: str = "",
        force: bool = False,
    ) -> tuple[EmployeeMonthlyStat, bool]:
        """Upsert a monthly stat snapshot.

        If the record already exists and is_closed=True, updates are rejected unless force=True.
        """
        stat = self.model.objects.filter(employee=employee, period=period).first()
        if stat:
            if stat.is_closed and not force:
                logger.warning(
                    "Xodim %s uchun %s davri yopilgan (is_closed=True), oylik snapshot yangilanishi rad etildi.",
                    employee.employee_id,
                    period,
                )
                raise ClosedPeriodError(
                    f"Xodim {employee.employee_id} uchun {period.strftime('%Y-%m')} davri yopilgan (is_closed=True). Snapshot o'zgartirilmadi."
                )

            stat.summary_data = summary_data or {}
            if source_spreadsheet_id:
                stat.source_spreadsheet_id = source_spreadsheet_id
            stat.save(update_fields=["summary_data", "source_spreadsheet_id", "updated_at"])
            return stat, False

        stat = self.model.objects.create(
            employee=employee,
            period=period,
            summary_data=summary_data or {},
            source_spreadsheet_id=source_spreadsheet_id,
        )
        return stat, True
