"""Importer layer that persists parsed DTOs into PostgreSQL.

This is the ONLY code that touches the database during imports.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import NamedTuple

from django.db import transaction

logger = logging.getLogger(__name__)

from django.utils import timezone

from apps.employees.models import Employee
from apps.employees.repositories.employee import EmployeeRepository
from apps.groups.repositories.group import SalesGroupRepository
from apps.imports.dto import GroupSummaryDTO, OrderDTO, PayrollDTO
from apps.imports.models import ImportJob
from apps.sales.models import Sale
from apps.sales.repositories.sale import SaleRepository


class ImportResult(NamedTuple):
    processed_rows: int
    created_sales: int
    updated_sales: int


class DataImporter:
    """Writes clean DTO lists transactionally to database."""

    def __init__(self) -> None:
        self.groups = SalesGroupRepository()
        self.employees = EmployeeRepository()
        self.sales = SaleRepository()

    def import_dto_lists(
        self,
        *,
        orders: list[OrderDTO],
        payroll: list[PayrollDTO],
        group_summaries: list[GroupSummaryDTO] | None = None,
        job: ImportJob | None = None,
        period: date | None = None,
        sheet_id: str = "",
    ) -> ImportResult:
        """Persist payroll, groups, monthly stats and orders inside a single atomic transaction."""
        from apps.employees.models import EmployeeMonthlyStat

        with transaction.atomic():
            payroll_employee_ids = {row.employee_id for row in payroll}

            # 1. Upsert payroll & employees & monthly stats
            for row in payroll:
                group = self.groups.get_or_create(code=row.group_code)
                emp = self.employees.upsert(
                    employee_id=row.employee_id,
                    full_name=row.employee_name,
                    group=group,
                    monthly_salary=row.monthly_salary,
                    summary_data=row.summary_data or {},
                )

                if period:
                    stat, created = EmployeeMonthlyStat.objects.get_or_create(
                        employee=emp,
                        period=period,
                        defaults={
                            "summary_data": row.summary_data or {},
                            "source_spreadsheet_id": sheet_id,
                        },
                    )
                    if not created:
                        if stat.is_closed:
                            logger.info(
                                "Xodim %s uchun %s davri yopilgan (is_closed=True), oylik snapshot yangilanishi o'tkazib yuborildi.",
                                emp.employee_id,
                                period,
                            )
                        else:
                            stat.summary_data = row.summary_data or {}
                            stat.source_spreadsheet_id = sheet_id
                            stat.save(update_fields=["summary_data", "source_spreadsheet_id"])


            # Upsert group summaries
            if group_summaries:
                for g_dto in group_summaries:
                    group = self.groups.get_or_create(code=g_dto.group_code)
                    group.group_total_sales = g_dto.group_total_sales
                    group.group_profit = g_dto.group_profit
                    group.leader_bonus = g_dto.leader_bonus
                    group.synced_at = timezone.now()
                    group.save(update_fields=["group_total_sales", "group_profit", "leader_bonus", "synced_at"])


            # Clear stale summary_data and monthly_salary for active employees no longer in List2
            Employee.objects.filter(is_active=True).exclude(employee_id__in=payroll_employee_ids).update(
                summary_data={},
                monthly_salary=Decimal("0.00"),
            )


            # Pre-load all employees into a map to eliminate N+1 queries
            employee_map = {
                emp.employee_id: emp
                for emp in Employee.objects.select_related("group").all()
            }
            group_cache = {}

            def get_group(code: str):
                clean_code = code.strip().upper()
                if clean_code not in group_cache:
                    group_cache[clean_code] = self.groups.get_or_create(code=clean_code)
                return group_cache[clean_code]

            # Delete only stale Sale records for the affected month(s) in the current import batch
            if orders:
                imported_order_ids = {row.order_id for row in orders if row.order_id}
                year_months = {(row.ordered_at.year, row.ordered_at.month) for row in orders if row.ordered_at}
                if year_months:
                    from django.db.models import Q
                    month_filter = Q()
                    for yr, mth in year_months:
                        month_filter |= Q(ordered_at__year=yr, ordered_at__month=mth)
                    Sale.objects.filter(month_filter).exclude(external_order_id__in=imported_order_ids).delete()

            # 2. Upsert sales
            sales_to_upsert: list[Sale] = []
            for row in orders:
                employee = employee_map.get(row.employee_id)
                if employee is None:
                    logger.warning("Rejecting order %s: employee ID %s not in payroll roster", row.order_id, row.employee_id)
                    continue

                sales_to_upsert.append(
                    Sale(
                        external_order_id=row.order_id,
                        employee=employee,
                        import_job=job,
                        status=row.status,
                        source=row.source,
                        sale_amount=row.sale_amount,
                        profit_amount=Decimal("0"),
                        ordered_at=row.ordered_at,
                    )
                )


            created, updated = self.sales.bulk_upsert(sales_to_upsert)
            return ImportResult(
                processed_rows=len(orders),
                created_sales=created,
                updated_sales=updated,
            )
