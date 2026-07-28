"""Employee and group reporting use-cases."""

from dataclasses import asdict, dataclass
from decimal import Decimal

from apps.accounts.models import TelegramAccount
from apps.accounts.repositories.telegram_account import TelegramAccountRepository
from apps.common.services.exceptions import AccessDeniedError, NotFoundError
from apps.employees.models import Employee
from apps.employees.repositories.employee import EmployeeRepository
from apps.groups.models import SalesGroup
from apps.groups.repositories.group import SalesGroupRepository
from apps.statistics.repositories.statistics import StatisticsRepository

LEADER_BONUS_RATE = Decimal("0.02")


@dataclass(frozen=True, slots=True)
class EmployeeDashboard:
    full_name: str
    employee_id: str
    group_code: str | None
    total_orders: int
    successful_orders: int
    cancelled_orders: int
    pending_orders: int
    total_sales: Decimal
    successful_sales: Decimal
    perv_sales: Decimal
    baza_sales: Decimal
    otkaz_sales: Decimal
    v_proc_sales: Decimal
    total_profit: Decimal
    monthly_salary: Decimal
    earned_salary: Decimal
    conversion_rate: float
    real_conversion_rate: float
    sources: list[dict[str, object]]
    month_str: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class GroupDashboard:
    group_code: str
    group_name: str
    successful_orders: int
    total_profit: Decimal
    leader_bonus: Decimal
    leader_personal_profit: Decimal
    month_str: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class StatisticsService:
    """Enforce data scope and return precomputed dashboard DTOs."""

    def __init__(
        self,
        employees: EmployeeRepository | None = None,
        accounts: TelegramAccountRepository | None = None,
        groups: SalesGroupRepository | None = None,
        statistics: StatisticsRepository | None = None,
    ) -> None:
        self.employees = employees or EmployeeRepository()
        self.accounts = accounts or TelegramAccountRepository()
        self.groups = groups or SalesGroupRepository()
        self.statistics = statistics or StatisticsRepository()

    def employee_dashboard_for_telegram(self, telegram_id: int) -> EmployeeDashboard:
        employee = self._employee_for_telegram(telegram_id)
        return self._employee_dashboard(employee)

    def employee_dashboard_for_employee(self, employee_id: str) -> EmployeeDashboard:
        try:
            employee = self.employees.get_active_by_employee_id(employee_id)
        except Employee.DoesNotExist:
            try:
                from apps.imports.services.sheets_sync import SheetsSyncService
                SheetsSyncService().sync_if_needed(force=True)
                employee = self.employees.get_active_by_employee_id(employee_id)
            except Exception as exc:
                raise NotFoundError("Xodim topilmadi.") from exc
        return self._employee_dashboard(employee)

    def group_dashboard_for_telegram(self, telegram_id: int) -> GroupDashboard:
        employee = self._employee_for_telegram(telegram_id)
        try:
            group = self.groups.get_for_leader(leader_id=employee.pk)
        except SalesGroup.DoesNotExist as exc:
            raise AccessDeniedError("Siz guruh rahbari emassiz.") from exc
        return self._group_dashboard(group, employee)

    def _employee_for_telegram(self, telegram_id: int) -> Employee:
        try:
            return self.accounts.get_by_telegram_id(telegram_id).employee
        except TelegramAccount.DoesNotExist as exc:
            raise AccessDeniedError("Avval Employee ID orqali profilingizni bog'lang.") from exc

    def _employee_dashboard(self, employee: Employee) -> EmployeeDashboard:
        totals = self.statistics.employee_totals(employee.pk)

        # If employee has pre-calculated summary_data from List2, always use it directly for 100% exact Google Sheets match
        if employee.summary_data:
            s = employee.summary_data
            total_sales = Decimal(str(s.get("total_sales", totals["total_sales"])))
            perv_sales = Decimal(str(s.get("perv_sales", totals["perv_sales"])))
            baza_sales = Decimal(str(s.get("baza_sales", totals["baza_sales"])))
            otkaz_sales = Decimal(str(s.get("otkaz_sales", totals["otkaz_sales"])))
            v_proc_sales = Decimal(str(s.get("v_proc_sales", totals["v_proc_sales"])))
            earned_salary = Decimal(str(s.get("earned_salary", employee.monthly_salary)))
            successful_orders = int(s.get("successful_orders", totals["successful_orders"]))
            
            successful_sales = perv_sales + baza_sales

            conversion_rate = float(s.get("conversion_rate", 0.0))
            real_conversion_rate = float(s.get("real_conversion_rate", 0.0))

            return EmployeeDashboard(
                full_name=employee.full_name,
                employee_id=employee.employee_id,
                group_code=employee.group.code if employee.group else None,
                total_orders=int(totals["total_orders"]),
                successful_orders=successful_orders,
                cancelled_orders=int(totals["cancelled_orders"]),
                pending_orders=int(totals["pending_orders"]),
                total_sales=total_sales,
                successful_sales=successful_sales,
                perv_sales=perv_sales,
                baza_sales=baza_sales,
                otkaz_sales=otkaz_sales,
                v_proc_sales=v_proc_sales,
                total_profit=Decimal(str(totals["total_profit"])),
                monthly_salary=employee.monthly_salary,
                earned_salary=earned_salary.quantize(Decimal("0.01")),
                conversion_rate=round(conversion_rate, 4),
                real_conversion_rate=round(real_conversion_rate, 4),
                sources=self.statistics.employee_sources(employee.pk),
                month_str=self.statistics.get_active_month_str(),
            )

        perv_sales = Decimal(str(totals["perv_sales"]))
        baza_sales = Decimal(str(totals["baza_sales"]))
        otkaz_sales = Decimal(str(totals["otkaz_sales"]))
        v_proc_sales = Decimal(str(totals["v_proc_sales"]))
        total_sales = Decimal(str(totals["total_sales"]))
        earned_salary = employee.monthly_salary

        successful_sales = perv_sales + baza_sales
        successful_sales_sum = successful_sales
        conversion_rate = float(successful_sales_sum / total_sales) if total_sales > 0 else 0.0
        denom = total_sales - v_proc_sales
        real_conversion_rate = float(successful_sales_sum / denom) if denom > 0 else 0.0

        return EmployeeDashboard(
            full_name=employee.full_name,
            employee_id=employee.employee_id,
            group_code=employee.group.code if employee.group else None,
            total_orders=int(totals["total_orders"]),
            successful_orders=int(totals["successful_orders"]),
            cancelled_orders=int(totals["cancelled_orders"]),
            pending_orders=int(totals["pending_orders"]),
            total_sales=total_sales,
            successful_sales=successful_sales,
            perv_sales=perv_sales,
            baza_sales=baza_sales,
            otkaz_sales=otkaz_sales,
            v_proc_sales=v_proc_sales,
            total_profit=Decimal(str(totals["total_profit"])),
            monthly_salary=employee.monthly_salary,
            earned_salary=earned_salary.quantize(Decimal("0.01")),
            conversion_rate=round(conversion_rate, 4),
            real_conversion_rate=round(real_conversion_rate, 4),
            sources=self.statistics.employee_sources(employee.pk),
            month_str=self.statistics.get_active_month_str(),
        )

    def _group_dashboard(self, group: SalesGroup, leader: Employee) -> GroupDashboard:
        totals = self.statistics.group_totals(group.pk)
        leader_totals = self.statistics.employee_totals(leader.pk)
        total_profit = Decimal(totals["total_profit"])
        return GroupDashboard(
            group_code=group.code,
            group_name=group.name,
            successful_orders=int(totals["successful_orders"]),
            total_profit=total_profit,
            leader_bonus=total_profit * LEADER_BONUS_RATE,
            leader_personal_profit=Decimal(leader_totals["total_profit"]),
            month_str=self.statistics.get_active_month_str(),
        )