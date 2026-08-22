import logging
from decimal import Decimal
from typing import Any
from django.utils import timezone
from apps.employees.models import Employee
from apps.groups.models import SalesGroup
from apps.groups.services.rop_service import RopService
from apps.statistics.repositories.statistics import StatisticsRepository

logger = logging.getLogger(__name__)


class SuperAdminService:
    """Service to aggregate company-wide metrics and provide drill-down data for Super Admin."""

    def get_company_global_dashboard(self) -> dict[str, Any]:
        """Aggregate company-wide sales, orders, and salary metrics across all active groups & employees."""
        groups = list(SalesGroup.objects.filter(is_active=True).order_by("code"))
        employees = list(Employee.objects.filter(is_active=True))

        company_total_sales = Decimal("0.00")
        company_successful_sales = Decimal("0.00")
        company_otkaz_sales = Decimal("0.00")
        company_v_proc_sales = Decimal("0.00")
        company_earned_salary = Decimal("0.00")
        company_upakovka = 0
        active_sellers_count = 0

        stats_repo = StatisticsRepository()

        for emp in employees:
            s = emp.summary_data or {}
            emp_tot = stats_repo.employee_totals(emp.id)

            if emp_tot and emp_tot.get("total_orders", 0) > 0:
                ts = emp_tot.get("total_sales") or Decimal("0.00")
                ss = (emp_tot.get("perv_sales") or Decimal("0.00")) + (emp_tot.get("baza_sales") or Decimal("0.00"))
                os = emp_tot.get("otkaz_sales") or Decimal("0.00")
                vp = emp_tot.get("v_proc_sales") or Decimal("0.00")
                upk = emp_tot.get("successful_orders") or 0
            else:
                ts = self._parse_decimal(s.get("total_sales"))
                ss = self._parse_decimal(s.get("successful_sales"))
                os = self._parse_decimal(s.get("otkaz_sales"))
                vp = self._parse_decimal(s.get("v_proc_sales"))
                upk = self._parse_int(s.get("successful_orders"))

            es = self._parse_decimal(s.get("earned_salary"))

            company_total_sales += ts
            company_successful_sales += ss
            company_otkaz_sales += os
            company_v_proc_sales += vp
            company_earned_salary += es
            company_upakovka += upk

            if ts > Decimal("0"):
                active_sellers_count += 1

        return {
            "groups_count": len(groups),
            "total_employees": len(employees),
            "active_sellers_count": active_sellers_count,
            "company_total_sales": company_total_sales,
            "company_successful_sales": company_successful_sales,
            "company_otkaz_sales": company_otkaz_sales,
            "company_v_proc_sales": company_v_proc_sales,
            "company_earned_salary": company_earned_salary,
            "company_upakovka": company_upakovka,
        }

    def get_all_groups_summary(self) -> list[dict[str, Any]]:
        """Return summary of each active sales group."""
        groups = SalesGroup.objects.filter(is_active=True).order_by("code")
        rop_service = RopService()
        result = []

        for group in groups:
            totals = rop_service.get_group_sales_totals(group)
            stats = rop_service.get_group_stats(group)
            leader_name = group.leader.full_name if group.leader else "Tayinlanmagan"

            result.append({
                "id": group.id,
                "code": group.code,
                "name": group.name,
                "leader_name": leader_name,
                "total_sales": totals.get("total_sales") or Decimal("0.00"),
                "successful_sales": totals.get("successful_sales") or Decimal("0.00"),
                "total_count": stats.get("total_count", 0),
                "active_count": stats.get("active_count", 0),
            })

        return result

    def get_company_employees_sorted(self) -> list[dict[str, Any]]:
        """Return all active company employees sorted by sales descending."""
        employees = Employee.objects.filter(is_active=True).select_related("group")
        stats_repo = StatisticsRepository()
        items = []

        for emp in employees:
            s = emp.summary_data or {}
            emp_tot = stats_repo.employee_totals(emp.id)

            if emp_tot and emp_tot.get("total_orders", 0) > 0:
                sales_val = emp_tot.get("total_sales") or Decimal("0.00")
                orders_val = emp_tot.get("successful_orders") or 0
            else:
                sales_val, orders_val, _ = RopService.parse_employee_sales_data(s)
                sales_val = sales_val or Decimal("0.00")
                orders_val = orders_val or 0

            salary_val = self._parse_decimal(s.get("earned_salary"))
            group_code = emp.group.code if emp.group else "—"

            items.append({
                "employee_id": emp.employee_id,
                "full_name": emp.full_name,
                "group_code": group_code,
                "sales_val": sales_val,
                "orders_val": orders_val,
                "salary_val": salary_val,
            })

        items.sort(key=lambda x: (x["sales_val"], x["salary_val"]), reverse=True)
        return items

    def search_employees(self, query: str) -> list[dict[str, Any]]:
        """Search active employees by name or employee_id."""
        q = query.strip().lower()
        all_emps = self.get_company_employees_sorted()
        return [
            e for e in all_emps
            if q in e["employee_id"].lower() or q in e["full_name"].lower()
        ]

    @staticmethod
    def _parse_decimal(raw: Any) -> Decimal:
        if raw is None or str(raw).strip() == "":
            return Decimal("0.00")
        try:
            return Decimal(str(raw).replace(",", "").strip())
        except Exception:
            return Decimal("0.00")

    @staticmethod
    def _parse_int(raw: Any) -> int:
        if raw is None or str(raw).strip() == "":
            return 0
        try:
            return int(Decimal(str(raw).replace(",", "").strip()))
        except Exception:
            return 0
