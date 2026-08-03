import logging
from decimal import Decimal
from typing import Any

from django.conf import settings

from apps.employees.models import Employee
from apps.groups.models import SalesGroup

logger = logging.getLogger(__name__)



class RopService:
    """Calculate ROP group sales, statistics, and salary."""

    def get_group_sales_totals(self, group: SalesGroup) -> dict[str, Any]:
        """Calculate group sales totals by summing summary_data across group employees."""
        employees = Employee.objects.filter(group=group, is_active=True)

        totals: dict[str, Any] = {
            "total_sales": Decimal("0.00"),
            "successful_sales": Decimal("0.00"),
            "otkaz_sales": Decimal("0.00"),
            "v_proc_sales": Decimal("0.00"),
        }

        uncalculated_uspeshka_count = 0
        has_any_uspeshka = False

        for emp in employees:
            s = emp.summary_data or {}

            # Process fields other than successful_sales
            for field in ["total_sales", "otkaz_sales", "v_proc_sales"]:
                if totals[field] is not None:
                    try:
                        totals[field] += self._parse_decimal(s.get(field))
                    except ValueError:
                        totals[field] = None

            # Process successful_sales (Uspeshka summasi) specially
            raw_uspeshka = s.get("successful_sales")
            if raw_uspeshka is None or str(raw_uspeshka).strip() == "":
                uncalculated_uspeshka_count += 1
            else:
                try:
                    val = self._parse_decimal(raw_uspeshka)
                    totals["successful_sales"] += val
                    has_any_uspeshka = True
                except ValueError:
                    uncalculated_uspeshka_count += 1

        if not has_any_uspeshka and employees.exists():
            totals["successful_sales"] = None

        totals["uncalculated_uspeshka_count"] = uncalculated_uspeshka_count
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
        """Calculate ROP salary in Django as SUM(group Uspeshka summasi) * ROP_SALARY_RATE."""
        totals = self.get_group_sales_totals(group)

        group_total_sales = totals["total_sales"]
        group_successful_sales = totals["successful_sales"]
        uncalculated_uspeshka_count = totals.get("uncalculated_uspeshka_count", 0)

        rate = getattr(settings, "ROP_SALARY_RATE", Decimal("0.02"))

        if group_successful_sales is None:
            logger.warning("Group %s missing Uspeshka summasi column/data for ROP salary calculation", group.code)
            computed_salary = None
        else:
            computed_salary = (group_successful_sales * rate).quantize(Decimal("0.01"))

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
            "group_successful_sales": group_successful_sales,
            "uncalculated_uspeshka_count": uncalculated_uspeshka_count,
            "rate_pct_str": f"{int(rate * 100)}%",
            "computed_salary": computed_salary,
            "sheet_bonus": sheet_bonus,
            "mismatch": mismatch,
        }

    def get_group_employee_list(self, group: SalesGroup, filter_key: str) -> list[dict[str, Any]]:
        """Fetch active employees for group, filter by sales, and sort highest sales first."""
        employees = Employee.objects.filter(group=group, is_active=True)

        parsed_list: list[dict[str, Any]] = []
        for emp in employees:
            sales_val, orders_val, has_error = self.parse_employee_sales_data(emp.summary_data or {})
            parsed_list.append({
                "employee_id": emp.employee_id,
                "full_name": emp.full_name,
                "sales_val": sales_val,
                "orders_val": orders_val,
                "has_error": has_error,
            })

        if filter_key == "has_sales":
            filtered = [e for e in parsed_list if e["sales_val"] is not None and e["sales_val"] > Decimal("0")]
        elif filter_key == "no_sales":
            filtered = [e for e in parsed_list if e["sales_val"] == Decimal("0") or e["has_error"]]
        else:
            filtered = parsed_list

        def sort_key(item: dict[str, Any]) -> tuple[int, Decimal, str]:
            if item["sales_val"] is not None:
                return (0, -item["sales_val"], item["employee_id"])
            return (1, Decimal("0"), item["employee_id"])

        filtered.sort(key=sort_key)
        return filtered

    @staticmethod
    def parse_employee_sales_data(summary_data: dict[str, Any]) -> tuple[Decimal | None, int | None, bool]:
        s = summary_data or {}
        raw_sales = s.get("total_sales")
        raw_orders = s.get("successful_orders")

        sales_val: Decimal | None = None
        has_error = False

        if raw_sales is None or str(raw_sales).strip() == "":
            sales_val = Decimal("0")
        else:
            try:
                sales_val = Decimal(str(raw_sales).replace(",", "").strip())
            except Exception:
                sales_val = None
                has_error = True

        orders_val: int | None = None
        if raw_orders is not None and str(raw_orders).strip() != "":
            try:
                orders_val = int(Decimal(str(raw_orders).replace(",", "").strip()))
            except Exception:
                orders_val = None

        return sales_val, orders_val, has_error

    @staticmethod
    def _parse_decimal(raw: Any) -> Decimal:
        if raw is None or raw == "":
            return Decimal("0.00")
        try:
            return Decimal(str(raw).replace(",", "").strip())
        except Exception as exc:
            raise ValueError(f"Unparseable decimal value: {raw}") from exc

