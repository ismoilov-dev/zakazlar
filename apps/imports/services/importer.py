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

    def update_group_sales_totals(self, period: date | None = None) -> None:
        """Audit discrepancy between Google Sheets group total sales and DB Sale aggregates."""
        from apps.groups.models import SalesGroup
        from apps.statistics.repositories.statistics import StatisticsRepository

        stats_repo = StatisticsRepository()
        for grp in SalesGroup.objects.filter(is_active=True):
            db_tot = stats_repo.group_totals(grp.id, target_date=period)
            db_ts = db_tot.get("total_sales") or Decimal("0.00") if db_tot else Decimal("0.00")

            if grp.group_total_sales is not None and db_ts > Decimal("0"):
                diff = abs(grp.group_total_sales - db_ts)
                if diff > Decimal("0.01"):
                    logger.info(
                        "Group %s total sales discrepancy: Sheets summary=%s vs DB Sale aggregate=%s (diff=%s)",
                        grp.code,
                        grp.group_total_sales,
                        db_ts,
                        diff,
                    )

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
                existing_emp = existing_employees.get(row.employee_id)
                if row.group_code and row.group_code != "UNKNOWN":
                    grp_code = row.group_code
                elif existing_emp and existing_emp.group:
                    grp_code = existing_emp.group.code
                else:
                    grp_code = "A"

                group = groups_map.get(grp_code)
                if group is None:
                    group = self.groups.get_or_create(code=grp_code)
                    groups_map[grp_code] = group

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

            # Upsert group summaries from DTOs or compute fallback from employee payroll data
            explicit_summary_codes: set[str] = set()
            if group_summaries:
                for g_dto in group_summaries:
                    grp_code = g_dto.group_code or "A"
                    group = groups_map.get(grp_code)
                    if group is None:
                        group = self.groups.get_or_create(code=grp_code)
                        groups_map[grp_code] = group

                    logger.info(
                        "GroupSummaryDTO saved for Group %s: group_total_sales=%s, group_profit=%s, leader_bonus=%s",
                        grp_code,
                        g_dto.group_total_sales,
                        g_dto.group_profit,
                        g_dto.leader_bonus,
                    )

                    if g_dto.group_total_sales and g_dto.group_total_sales > Decimal("0.00"):
                        explicit_summary_codes.add(grp_code.upper())

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

            # Compute authoritative group_total_sales by summing employee sales from List2 payroll for all groups
            from collections import defaultdict
            from apps.imports.sources.sheets import SheetsSource

            group_payroll_sales: dict[str, Decimal] = defaultdict(Decimal)
            for p_dto in payroll:
                grp_k = (p_dto.group_code or "A").strip().upper()
                if grp_k and grp_k != "UNKNOWN" and p_dto.summary_data:
                    ts_val = p_dto.summary_data.get("total_sales") or p_dto.summary_data.get("successful_sales")
                    if ts_val:
                        try:
                            group_payroll_sales[grp_k] += SheetsSource._parse_money(ts_val)
                        except Exception:
                            pass

            for grp_code, group in groups_map.items():
                code_up = grp_code.upper()
                calc_sales = group_payroll_sales.get(code_up, Decimal("0.00"))
                if calc_sales > Decimal("0.00") and group.group_total_sales != calc_sales:
                    group.group_total_sales = calc_sales
                    group.synced_at = timezone.now()
                    group.save(update_fields=["group_total_sales", "synced_at"])
                    logger.info(
                        "SalesGroup %s total sales set to %s from List2 employee payroll sales sum",
                        grp_code,
                        calc_sales,
                    )

            # Clear stale summary_data and monthly_salary for active employees no longer in List2
            Employee.objects.filter(is_active=True).exclude(employee_id__in=payroll_employee_ids).update(
                summary_data={},
                monthly_salary=Decimal("0.00"),
            )

            self.update_group_sales_totals(period=period)
            self.sync_employee_summaries_from_sales(period=period)
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
                    and existing_sale.has_sheet_error == row.has_sheet_error
                    and existing_sale.ordered_at == row.ordered_at
                    and existing_sale.client_name == row.client_name
                    and existing_sale.product_name == row.product_name
                    and existing_sale.quantity == row.quantity
                    and existing_sale.product_name_2 == row.product_name_2
                    and existing_sale.quantity_2 == row.quantity_2
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
                        has_sheet_error=row.has_sheet_error,
                        profit_amount=Decimal("0"),
                        ordered_at=row.ordered_at,
                        client_name=row.client_name,
                        product_name=row.product_name,
                        quantity=row.quantity,
                        product_name_2=row.product_name_2,
                        quantity_2=row.quantity_2,
                    )
                )

            res = (0, 0)
            if sales_to_upsert:
                res = self.sales.bulk_upsert(sales_to_upsert)

            self.update_group_sales_totals(period=period)
            self.sync_employee_summaries_from_sales(period=period)
            return res

    def sync_employee_summaries_from_sales(self, period: date | None = None) -> None:
        """Dynamically update employee summary_data JSON in DB with actual Sale aggregates from List1."""
        from django.db.models import Q, Sum
        from django.db.models.functions import Coalesce
        from apps.employees.models import Employee, EmployeeMonthlyStat
        from apps.imports.sources.sheets import SheetsSource
        from apps.sales.models import Sale, SaleStatus
        from apps.statistics.repositories.statistics import get_active_period_date

        period_dt = get_active_period_date(period)
        sales_qs = Sale.objects.filter(
            ordered_at__year=period_dt.year,
            ordered_at__month=period_dt.month,
        )

        emp_stats = (
            sales_qs.values("employee_id")
            .annotate(
                db_total_sales=Coalesce(Sum("sale_amount"), Decimal("0.00")),
                db_successful_sales=Coalesce(
                    Sum("sale_amount", filter=Q(status=SaleStatus.SUCCESSFUL)), Decimal("0.00")
                ),
            )
        )

        for stat in emp_stats:
            emp_id = stat["employee_id"]
            db_ts = stat["db_total_sales"]
            db_ss = stat["db_successful_sales"]

            try:
                emp = Employee.objects.get(id=emp_id)
            except Employee.DoesNotExist:
                continue

            summary = dict(emp.summary_data or {})
            l2_ts = SheetsSource._parse_money(summary.get("total_sales")) if summary.get("total_sales") else Decimal("0.00")
            l2_ss = SheetsSource._parse_money(summary.get("successful_sales")) if summary.get("successful_sales") else Decimal("0.00")

            new_ts = max(l2_ts, db_ts)
            new_ss = max(l2_ss, db_ss)

            changed = False
            if new_ts > l2_ts and new_ts > Decimal("0.00"):
                summary["total_sales"] = str(new_ts)
                changed = True
            if new_ss > l2_ss and new_ss > Decimal("0.00"):
                summary["successful_sales"] = str(new_ss)
                changed = True

            if changed:
                emp.summary_data = summary
                emp.save(update_fields=["summary_data"])

                if period:
                    m_stat = EmployeeMonthlyStat.objects.filter(employee=emp, period=period).first()
                    if m_stat and not m_stat.is_closed:
                        m_stat.summary_data = summary
                        m_stat.save(update_fields=["summary_data"])

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
            self.update_group_sales_totals(period=period)
            self.sync_employee_summaries_from_sales(period=period)
            return ImportResult(
                processed_rows=len(orders),
                created_sales=created,
                updated_sales=updated,
            )
