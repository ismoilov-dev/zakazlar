import logging
from decimal import Decimal
from typing import Any

from django.conf import settings

from apps.employees.models import Employee
from apps.groups.models import SalesGroup

logger = logging.getLogger(__name__)



class RopService:
    """Calculate ROP group sales, statistics, and salary."""

    def get_group_sales_totals(self, group: SalesGroup) -> dict[str, Decimal | None]:
        """Calculate group sales totals by summing summary_data across group employees."""
        employees = Employee.objects.filter(group=group, is_active=True)

        totals: dict[str, Decimal | None] = {
            "total_sales": Decimal("0.00"),
            "successful_sales": Decimal("0.00"),
            "otkaz_sales": Decimal("0.00"),
            "v_proc_sales": Decimal("0.00"),
        }

        for emp in employees:
            s = emp.summary_data or {}
            for field in ["total_sales", "successful_sales", "otkaz_sales", "v_proc_sales"]:
                if totals[field] is not None:
                    try:
                        totals[field] += self._parse_decimal(s.get(field))
                    except ValueError:
                        totals[field] = None

        return totals

    def get_group_stats(self, group: SalesGroup) -> dict[str, int | None]:
        """Calculate group headcount, total packaging, and active sellers count."""
        employees = Employee.objects.filter(group=group, is_active=True)

        total_count = employees.count()
        total_upakovka: int | None = 0
        active_count = 0

        for emp in employees:
            s = emp.summary_data or {}
            try:
                ts = self._parse_decimal(s.get("total_sales"))
                if ts > Decimal("0"):
                    active_count += 1
            except ValueError:
                pass

            so_raw = s.get("successful_orders")
            if so_raw is not None and str(so_raw).strip() != "":
                if total_upakovka is not None:
                    try:
                        val_dec = Decimal(str(so_raw).replace(",", "").strip())
                        total_upakovka += int(val_dec)
                    except Exception:
                        total_upakovka = None

        return {
            "total_count": total_count,
            "total_upakovka": total_upakovka,
            "active_count": active_count,
        }

    def calculate_rop_salary(self, group: SalesGroup) -> dict[str, Any]:
        """Calculate ROP salary in Django as SUM(group sales) * ROP_SALARY_RATE."""
        totals = self.get_group_sales_totals(group)

        group_total_sales = totals["total_sales"]

        rate = getattr(settings, "ROP_SALARY_RATE", Decimal("0.02"))
        if group_total_sales is not None:
            computed_salary = (group_total_sales * rate).quantize(Decimal("0.01"))
        else:
            computed_salary = None

        sheet_bonus = group.leader_bonus if group.leader_bonus is not None else Decimal("0.00")

        mismatch = False
        if computed_salary is not None and group.leader_bonus is not None:
            diff = abs(computed_salary - sheet_bonus)
            mismatch = diff > Decimal("1.00")
            if mismatch:
                logger.error(
                    "ROP salary mismatch for group %s: computed=%s vs sheet=%s (diff=%s)",
                    group.code,
                    computed_salary,
                    sheet_bonus,
                    diff,
                )

        return {
            "group_total_sales": group_total_sales,
            "rate_pct_str": f"{int(rate * 100)}%",
            "computed_salary": computed_salary,
            "sheet_bonus": sheet_bonus,
            "mismatch": mismatch,
        }

    @staticmethod
    def _parse_decimal(raw: Any) -> Decimal:
        if raw is None or raw == "":
            return Decimal("0.00")
        try:
            return Decimal(str(raw).replace(",", "").strip())
        except Exception as exc:
            raise ValueError(f"Unparseable decimal value: {raw}") from exc

