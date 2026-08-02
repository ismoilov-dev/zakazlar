"""Importer layer that persists parsed DTOs into PostgreSQL.

This is the ONLY code that touches the database during imports.
"""

from __future__ import annotations

import json
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

    def import_payroll_only(
        self,
        *,
        payroll: list[PayrollDTO],
        group_summaries: list[GroupSummaryDTO] | None = None,
        period: date | None = None,
        sheet_id: str = "",
    ) -> int:
        """Persist payroll, groups and monthly stats without touching Sale records."""
        with transaction.atomic():
            if period:
                from apps.common.services.exceptions import ValidationError
                from apps.imports.models import SpreadsheetPeriod
                active_sp = SpreadsheetPeriod.objects.filter(is_active=True).first()
                if active_sp and (active_sp.period.year != period.year or active_sp.period.month != period.month):
                    logger.error(
                        "Active SpreadsheetPeriod (%s) does not match import period (%s). Sync aborted.",
                        active_sp.period.strftime("%Y-%m"),
                        period.strftime("%Y-%m"),
                    )
                    raise ValidationError(
                        f"Active SpreadsheetPeriod ({active_sp.period.strftime('%Y-%m')}) does not match import period ({period.strftime('%Y-%m')}). Sync aborted."
                    )

            payroll_employee_ids = {row.employee_id for row in payroll}

            from apps.groups.models import SalesGroup
            groups_map = {g.code: g for g in SalesGroup.objects.all()}

            existing_employees = {
                emp.employee_id: emp
                for emp in Employee.objects.select_related("group").filter(employee_id__in=payroll_employee_ids)
            }
            existing_stats = {}
            if period:
                from apps.employees.models import EmployeeMonthlyStat
                existing_stats = {
                    (stat.employee_id, stat.period): stat
                    for stat in EmployeeMonthlyStat.objects.filter(period=period)
                }

            # 1. Upsert payroll & employees & monthly stats (only if changed)
            for row in payroll:
                grp_code = row.group_code or "A"
                group = groups_map.get(grp_code)
                if group is None:
                    group = self.groups.get_or_create(code=grp_code)
                    groups_map[grp_code] = group

                existing_emp = existing_employees.get(row.employee_id)
                summary_dict = row.summary_data or {}

                if (
                    existing_emp is None
                    or existing_emp.full_name != row.employee_name
                    or existing_emp.group_id != group.id
                    or existing_emp.monthly_salary != row.monthly_salary
                    or json.dumps(existing_emp.summary_data or {}, sort_keys=True) != json.dumps(summary_dict, sort_keys=True)
                ):
                    emp = self.employees.upsert(
                        employee_id=row.employee_id,
                        full_name=row.employee_name,
                        group=group,
                        monthly_salary=row.monthly_salary,
                        summary_data=summary_dict,
                    )
                else:
                    emp = existing_emp

                if period:
                    existing_stat = existing_stats.get((emp.id, period))
                    stat_summary_changed = (
                        existing_stat is None
                        or json.dumps(existing_stat.summary_data or {}, sort_keys=True) != json.dumps(summary_dict, sort_keys=True)
                        or (sheet_id and existing_stat.source_spreadsheet_id != sheet_id)
                    )
                    if stat_summary_changed:
                        from apps.employees.repositories.monthly_stat import ClosedPeriodError, EmployeeMonthlyStatRepository
                        try:
                            EmployeeMonthlyStatRepository().upsert_snapshot(
                                employee=emp,
                                period=period,
                                summary_data=summary_dict,
                                source_spreadsheet_id=sheet_id,
                                force=False,
                            )
                        except ClosedPeriodError:
                            logger.info(
                                "Xodim %s uchun %s davri yopilgan (is_closed=True), oylik snapshot yangilanishi o'tkazib yuborildi.",
                                emp.employee_id,
                                period,
                            )

            # Upsert group summaries only if changed
            if group_summaries:
                for g_dto in group_summaries:
                    grp_code = g_dto.group_code or "A"
                    group = groups_map.get(grp_code)
                    if group is None:
                        group = self.groups.get_or_create(code=grp_code)
                        groups_map[grp_code] = group
                    if (
                        group.group_total_sales != g_dto.group_total_sales
                        or group.group_profit != g_dto.group_profit
                        or group.leader_bonus != g_dto.leader_bonus
                    ):
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

            return len(payroll)

    def import_orders_only(
        self,
        *,
        orders: list[OrderDTO],
        job: ImportJob | None = None,
        period: date | None = None,
    ) -> tuple[int, int]:
        """Persist order sales inside an atomic transaction."""
        with transaction.atomic():
            if period:
                from apps.common.services.exceptions import ValidationError
                from apps.imports.models import SpreadsheetPeriod
                active_sp = SpreadsheetPeriod.objects.filter(is_active=True).first()
                if active_sp and (active_sp.period.year != period.year or active_sp.period.month != period.month):
                    logger.error(
                        "Active SpreadsheetPeriod (%s) does not match import period (%s). Sync aborted.",
                        active_sp.period.strftime("%Y-%m"),
                        period.strftime("%Y-%m"),
                    )
                    raise ValidationError(
                        f"Active SpreadsheetPeriod ({active_sp.period.strftime('%Y-%m')}) does not match import period ({period.strftime('%Y-%m')}). Sync aborted."
                    )

            employee_map = {
                emp.employee_id: emp
                for emp in Employee.objects.select_related("group").all()
            }

            existing_sales: dict[str, Sale] = {}
            if orders:
                imported_order_ids = {row.order_id for row in orders if row.order_id}
                year_months = {(row.ordered_at.year, row.ordered_at.month) for row in orders if row.ordered_at}
                if year_months:
                    from django.db.models import Q
                    month_filter = Q()
                    for yr, mth in year_months:
                        month_filter |= Q(ordered_at__year=yr, ordered_at__month=mth)
                    existing_sales = {
                        s.external_order_id: s
                        for s in Sale.objects.filter(month_filter)
                    }
                    stale_ids = set(existing_sales.keys()) - imported_order_ids
                    if stale_ids:
                        Sale.objects.filter(month_filter, external_order_id__in=stale_ids).delete()

            sales_to_upsert: list[Sale] = []
            for row in orders:
                employee = employee_map.get(row.employee_id)
                if employee is None:
                    logger.warning("Rejecting order %s: employee ID %s not in payroll roster", row.order_id, row.employee_id)
                    continue

                existing_sale = existing_sales.get(row.order_id)
                if (
                    existing_sale is not None
                    and existing_sale.employee_id == employee.id
                    and existing_sale.status == row.status
                    and existing_sale.source == row.source
                    and existing_sale.sale_amount == row.sale_amount
                    and existing_sale.ordered_at == row.ordered_at
                ):
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

            if not sales_to_upsert:
                return (0, 0)

            return self.sales.bulk_upsert(sales_to_upsert)

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
        with transaction.atomic():
            self.import_payroll_only(
                payroll=payroll,
                group_summaries=group_summaries,
                period=period,
                sheet_id=sheet_id,
            )
            created, updated = self.import_orders_only(
                orders=orders,
                job=job,
                period=period,
            )
            return ImportResult(
                processed_rows=len(orders),
                created_sales=created,
                updated_sales=updated,
            )
