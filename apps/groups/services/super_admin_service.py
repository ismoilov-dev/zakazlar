import logging
from decimal import Decimal
from typing import Any

from django.core.cache import cache
from django.utils import timezone

from apps.employees.models import Employee
from apps.groups.models import SalesGroup
from apps.groups.services.rop_service import RopService
from apps.statistics.repositories.statistics import StatisticsRepository

logger = logging.getLogger(__name__)

CACHE_TTL = 30


class SuperAdminService:
    """Service to aggregate company-wide metrics and provide drill-down data for Super Admin."""

    def get_company_global_dashboard(self, force_refresh: bool = False) -> dict[str, Any]:
        """Aggregate company-wide sales, orders, and salary metrics across all active groups & employees."""
        cache_key = "sa_global_dashboard"
        if not force_refresh:
            cached = cache.get(cache_key)
            if cached:
                return cached

        groups = list(SalesGroup.objects.filter(is_active=True).order_by("code"))
        employees = list(Employee.objects.filter(is_active=True))

        stats_repo = StatisticsRepository()
        all_db_totals = stats_repo.all_employees_totals_dict()

        company_total_sales = Decimal("0.00")
        company_successful_sales = Decimal("0.00")
        company_otkaz_sales = Decimal("0.00")
        company_v_proc_sales = Decimal("0.00")
        company_earned_salary = Decimal("0.00")
        company_upakovka = 0
        active_sellers_count = 0

        for emp in employees:
            s = emp.summary_data or {}
            emp_tot = all_db_totals.get(emp.id)

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

        data = {
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
        cache.set(cache_key, data, CACHE_TTL)
        return data

    def get_all_groups_summary(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        """Return summary of each active sales group."""
        cache_key = "sa_groups_summary"
        if not force_refresh:
            cached = cache.get(cache_key)
            if cached:
                return cached

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

        cache.set(cache_key, result, CACHE_TTL)
        return result

    def get_company_employees_sorted(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        """Return all active company employees sorted by sales descending."""
        cache_key = "sa_employees_sorted"
        if not force_refresh:
            cached = cache.get(cache_key)
            if cached:
                return cached

        employees = Employee.objects.filter(is_active=True).select_related("group")
        stats_repo = StatisticsRepository()
        all_db_totals = stats_repo.all_employees_totals_dict()
        items = []

        for emp in employees:
            s = emp.summary_data or {}
            emp_tot = all_db_totals.get(emp.id)

            if emp_tot and emp_tot.get("total_orders", 0) > 0:
                sales_val = emp_tot.get("total_sales") or Decimal("0.00")
                orders_val = emp_tot.get("successful_orders") or 0
                successful_sales = (emp_tot.get("perv_sales") or Decimal("0.00")) + (emp_tot.get("baza_sales") or Decimal("0.00"))
                otkaz_sales = emp_tot.get("otkaz_sales") or Decimal("0.00")
                v_proc_sales = emp_tot.get("v_proc_sales") or Decimal("0.00")
            else:
                sales_val, orders_val, _ = RopService.parse_employee_sales_data(s)
                sales_val = sales_val or Decimal("0.00")
                orders_val = orders_val or 0
                successful_sales = self._parse_decimal(s.get("successful_sales"))
                otkaz_sales = self._parse_decimal(s.get("otkaz_sales"))
                v_proc_sales = self._parse_decimal(s.get("v_proc_sales"))

            sal_1_15 = self._parse_decimal(s.get("salary_1_15"))
            sal_16_31 = self._parse_decimal(s.get("salary_16_31"))
            earned_sal = self._parse_decimal(s.get("earned_salary"))

            import calendar
            from decimal import ROUND_HALF_UP

            target_dt = timezone.localtime().date()
            num_days = calendar.monthrange(target_dt.year, target_dt.month)[1]

            if (sal_1_15 is None or sal_1_15 == Decimal("0.00")) and (sal_16_31 is None or sal_16_31 == Decimal("0.00")):
                if earned_sal > Decimal("0.00"):
                    sal_1_15 = (earned_sal * Decimal("15") / Decimal(str(num_days))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                    sal_16_31 = earned_sal - sal_1_15
            elif sal_1_15 is not None and sal_1_15 > Decimal("0.00") and (sal_16_31 is None or sal_16_31 == Decimal("0.00")):
                if earned_sal > sal_1_15:
                    sal_16_31 = earned_sal - sal_1_15
            elif sal_16_31 is not None and sal_16_31 > Decimal("0.00") and (sal_1_15 is None or sal_1_15 == Decimal("0.00")):
                if earned_sal > sal_16_31:
                    sal_1_15 = earned_sal - sal_16_31

            bw = stats_repo.employee_biweekly_totals(emp.id)
            p1_tot = bw["period1"]
            p2_tot = bw["period2"]

            if p1_tot.get("total_orders", 0) > 0 or p2_tot.get("total_orders", 0) > 0:
                p1_sales = p1_tot.get("total_sales") or Decimal("0.00")
                p1_successful = (p1_tot.get("perv_sales") or Decimal("0.00")) + (p1_tot.get("baza_sales") or Decimal("0.00"))
                p1_otkaz = p1_tot.get("otkaz_sales") or Decimal("0.00")
                p1_vproc = p1_tot.get("v_proc_sales") or Decimal("0.00")
                p1_upakovka = p1_tot.get("successful_orders") or 0

                p2_sales = p2_tot.get("total_sales") or Decimal("0.00")
                p2_successful = (p2_tot.get("perv_sales") or Decimal("0.00")) + (p2_tot.get("baza_sales") or Decimal("0.00"))
                p2_otkaz = p2_tot.get("otkaz_sales") or Decimal("0.00")
                p2_vproc = p2_tot.get("v_proc_sales") or Decimal("0.00")
                p2_upakovka = p2_tot.get("successful_orders") or 0
            else:
                p1_sales = (sales_val * Decimal("15") / Decimal(str(num_days))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                p2_sales = sales_val - p1_sales

                p1_successful = (successful_sales * Decimal("15") / Decimal(str(num_days))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                p2_successful = successful_sales - p1_successful

                p1_otkaz = (otkaz_sales * Decimal("15") / Decimal(str(num_days))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                p2_otkaz = otkaz_sales - p1_otkaz

                p1_vproc = (v_proc_sales * Decimal("15") / Decimal(str(num_days))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                p2_vproc = v_proc_sales - p1_vproc

                p1_upakovka = int(orders_val * 15 // num_days)
                p2_upakovka = orders_val - p1_upakovka

            group_code = emp.group.code if emp.group else "—"

            items.append({
                "employee_id": emp.employee_id,
                "full_name": emp.full_name,
                "group_code": group_code,
                "group_name": emp.group.name if emp.group else "",
                "sales_val": sales_val,
                "successful_sales": successful_sales,
                "otkaz_sales": otkaz_sales,
                "v_proc_sales": v_proc_sales,
                "orders_val": orders_val,
                "salary_val": earned_sal,
                "salary_1_15": sal_1_15,
                "salary_16_31": sal_16_31,
                "earned_salary": earned_sal,
                "p1_sales": p1_sales,
                "p1_successful": p1_successful,
                "p1_otkaz": p1_otkaz,
                "p1_vproc": p1_vproc,
                "p1_upakovka": p1_upakovka,
                "p2_sales": p2_sales,
                "p2_successful": p2_successful,
                "p2_otkaz": p2_otkaz,
                "p2_vproc": p2_vproc,
                "p2_upakovka": p2_upakovka,
            })

        items.sort(key=lambda x: (x["sales_val"], x["salary_val"]), reverse=True)
        cache.set(cache_key, items, CACHE_TTL)
        return items

    def search_employees(self, query: str) -> list[dict[str, Any]]:
        """Search active employees by name or employee_id."""
        from apps.imports.dto import normalize_employee_id

        q = query.strip().lower()
        norm_q = normalize_employee_id(q)
        all_emps = self.get_company_employees_sorted()
        return [
            e
            for e in all_emps
            if q in e["employee_id"].lower()
            or (norm_q and norm_q in normalize_employee_id(e["employee_id"]))
            or q in e["full_name"].lower()
        ]

    def get_employee_detail(self, query: str) -> dict[str, Any] | None:
        """Fetch complete detailed metrics for a single employee matching query ID or name."""
        from django.db.models import Q
        from apps.imports.dto import normalize_employee_id
        import calendar
        from decimal import ROUND_HALF_UP

        q = query.strip()
        norm_q = normalize_employee_id(q)

        emp = (
            Employee.objects.filter(is_active=True)
            .select_related("group")
            .filter(
                Q(employee_id__iexact=q)
                | Q(employee_id__iexact=norm_q)
                | Q(full_name__icontains=q)
            )
            .first()
        )
        if not emp:
            emp = (
                Employee.objects.filter(is_active=True)
                .select_related("group")
                .filter(Q(employee_id__icontains=q) | Q(employee_id__endswith=norm_q))
                .first()
            )
        if not emp:
            return None

        stats_repo = StatisticsRepository()
        emp_tot = stats_repo.employee_totals(emp.id)
        s = emp.summary_data or {}

        # 1. Total monthly sales & orders
        if emp_tot and emp_tot.get("total_orders", 0) > 0:
            ts = emp_tot.get("total_sales") or Decimal("0.00")
            ss = (emp_tot.get("perv_sales") or Decimal("0.00")) + (emp_tot.get("baza_sales") or Decimal("0.00"))
            os = emp_tot.get("otkaz_sales") or Decimal("0.00")
            vp = emp_tot.get("v_proc_sales") or Decimal("0.00")
            upk = emp_tot.get("successful_orders") or 0
        else:
            ts = self._parse_decimal(s.get("total_sales") or s.get("total_sales_sum"))
            ss = self._parse_decimal(s.get("successful_sales") or s.get("successful_sales_sum") or s.get("uspeshka"))
            os = self._parse_decimal(s.get("otkaz_sales") or s.get("otkaz"))
            vp = self._parse_decimal(s.get("v_proc_sales") or s.get("v_proc"))
            upk = self._parse_int(s.get("successful_orders") or s.get("upakovka"))

            if ss == Decimal("0.00") and ts > Decimal("0.00"):
                ss = ts

        # 2. Earned Salary & 1-15 / 16-31 Breakdown
        sal_1_15 = self._parse_decimal(s.get("salary_1_15") or s.get("earned_salary_1_15"))
        sal_16_31 = self._parse_decimal(s.get("salary_16_31") or s.get("earned_salary_16_31"))
        earned_sal = self._parse_decimal(s.get("earned_salary") or s.get("earned_salary_total") or s.get("monthly_salary"))

        if earned_sal == Decimal("0.00") and ss > Decimal("0.00"):
            grp_code = emp.group.code.upper() if emp.group else "A"
            if grp_code == "BAZA":
                earned_sal = (ss * Decimal("0.12")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            else:
                earned_sal = (ss * Decimal("0.12")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)

        target_dt = timezone.localtime().date()
        num_days = calendar.monthrange(target_dt.year, target_dt.month)[1]

        if sal_1_15 == Decimal("0.00") and sal_16_31 == Decimal("0.00"):
            if earned_sal > Decimal("0.00"):
                sal_1_15 = (earned_sal * Decimal("15") / Decimal(str(num_days))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                sal_16_31 = earned_sal - sal_1_15
        elif sal_1_15 > Decimal("0.00") and sal_16_31 == Decimal("0.00"):
            if earned_sal > sal_1_15:
                sal_16_31 = earned_sal - sal_1_15
        elif sal_16_31 > Decimal("0.00") and sal_1_15 == Decimal("0.00"):
            if earned_sal > sal_16_31:
                sal_1_15 = earned_sal - sal_16_31

        # 3. Bi-weekly Period 1 and Period 2 breakdown
        bw = stats_repo.employee_biweekly_totals(emp.id)
        p1_tot = bw["period1"]
        p2_tot = bw["period2"]

        if p1_tot.get("total_orders", 0) > 0 or p2_tot.get("total_orders", 0) > 0:
            p1_sales = p1_tot.get("total_sales") or Decimal("0.00")
            p1_successful = (p1_tot.get("perv_sales") or Decimal("0.00")) + (p1_tot.get("baza_sales") or Decimal("0.00"))
            p1_otkaz = p1_tot.get("otkaz_sales") or Decimal("0.00")
            p1_vproc = p1_tot.get("v_proc_sales") or Decimal("0.00")
            p1_upakovka = p1_tot.get("successful_orders") or 0

            p2_sales = p2_tot.get("total_sales") or Decimal("0.00")
            p2_successful = (p2_tot.get("perv_sales") or Decimal("0.00")) + (p2_tot.get("baza_sales") or Decimal("0.00"))
            p2_otkaz = p2_tot.get("otkaz_sales") or Decimal("0.00")
            p2_vproc = p2_tot.get("v_proc_sales") or Decimal("0.00")
            p2_upakovka = p2_tot.get("successful_orders") or 0
        else:
            p1_sales = (ts * Decimal("15") / Decimal(str(num_days))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            p2_sales = ts - p1_sales

            p1_successful = (ss * Decimal("15") / Decimal(str(num_days))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            p2_successful = ss - p1_successful

            p1_otkaz = (os * Decimal("15") / Decimal(str(num_days))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            p2_otkaz = os - p1_otkaz

            p1_vproc = (vp * Decimal("15") / Decimal(str(num_days))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            p2_vproc = vp - p1_vproc

            p1_upakovka = int(upk * 15 // num_days)
            p2_upakovka = upk - p1_upakovka

        source_label = "DB_SALE_RECORDS" if (emp_tot and emp_tot.get("total_orders", 0) > 0) else "EMPLOYEE_SUMMARY_JSON"
        logger.info(
            "SuperAdmin lookup for employee %s (ID: %s, Group: %s) via %s: total_sales=%s, successful_sales=%s, earned_sal=%s, sal_1_15=%s, sal_16_31=%s",
            emp.full_name,
            emp.employee_id,
            emp.group.code if emp.group else "—",
            source_label,
            ts,
            ss,
            earned_sal,
            sal_1_15,
            sal_16_31,
        )

        return {
            "employee_id": emp.employee_id,
            "full_name": emp.full_name,
            "group_code": emp.group.code if emp.group else "—",
            "group_name": emp.group.name if emp.group else "",
            "total_sales": ts,
            "successful_sales": ss,
            "otkaz_sales": os,
            "v_proc_sales": vp,
            "upakovka": upk,
            "earned_salary": earned_sal,
            "salary_1_15": sal_1_15,
            "salary_16_31": sal_16_31,
            "p1_sales": p1_sales,
            "p1_successful": p1_successful,
            "p1_otkaz": p1_otkaz,
            "p1_vproc": p1_vproc,
            "p1_upakovka": p1_upakovka,
            "p2_sales": p2_sales,
            "p2_successful": p2_successful,
            "p2_otkaz": p2_otkaz,
            "p2_vproc": p2_vproc,
            "p2_upakovka": p2_upakovka,
        }

    @staticmethod
    def _parse_decimal(raw: Any) -> Decimal:
        if raw is None:
            return Decimal("0.00")
        clean_str = (
            str(raw)
            .replace("\xa0", "")
            .replace(" ", "")
            .replace(",", "")
            .replace("so'm", "")
            .replace("som", "")
            .replace("UZS", "")
            .strip()
        )
        if not clean_str:
            return Decimal("0.00")
        try:
            return Decimal(clean_str)
        except Exception:
            return Decimal("0.00")

    @staticmethod
    def _parse_int(raw: Any) -> int:
        if raw is None:
            return 0
        clean_str = (
            str(raw)
            .replace("\xa0", "")
            .replace(" ", "")
            .replace(",", "")
            .replace("ta", "")
            .strip()
        )
        if not clean_str:
            return 0
        try:
            return int(float(clean_str))
        except Exception:
            return 0
