"""Employee and group reporting use-cases."""

from dataclasses import asdict, dataclass
from decimal import Decimal

from apps.accounts.models import TelegramAccount
from apps.accounts.repositories.telegram_account import TelegramAccountRepository
from apps.common.services.exceptions import AccessDeniedError, NotFoundError, ValidationError
from apps.employees.models import Employee
from apps.employees.repositories.employee import EmployeeRepository
from apps.groups.models import SalesGroup
from apps.groups.repositories.group import SalesGroupRepository
from apps.statistics.repositories.statistics import StatisticsRepository



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
        s = employee.summary_data
        if not s:
            raise ValidationError("Ma'lumotlaringiz hali hisoblanmagan. Rahbaringizga murojaat qiling.")

        required_keys = [
            "total_sales",
            "perv_sales",
            "baza_sales",
            "otkaz_sales",
            "v_proc_sales",
            "earned_salary",
            "successful_orders",
        ]
        for key in required_keys:
            if key not in s or s[key] is None or s[key] == "":
                raise ValidationError("Ma'lumotlaringiz hali hisoblanmagan. Rahbaringizga murojaat qiling.")

        try:
            total_sales = Decimal(str(s["total_sales"]))
            perv_sales = Decimal(str(s["perv_sales"]))
            baza_sales = Decimal(str(s["baza_sales"]))
            otkaz_sales = Decimal(str(s["otkaz_sales"]))
            v_proc_sales = Decimal(str(s["v_proc_sales"]))
            earned_salary = Decimal(str(s["earned_salary"]))
            successful_orders = int(s["successful_orders"])
            successful_sales = Decimal(str(s.get("successful_sales", perv_sales + baza_sales)))
            conversion_rate = float(s.get("conversion_rate", 0.0))
            real_conversion_rate = float(s.get("real_conversion_rate", 0.0))
        except (ValueError, TypeError, ArithmeticError) as exc:
            raise ValidationError("Ma'lumotlaringiz hali hisoblanmagan. Rahbaringizga murojaat qiling.") from exc

        return EmployeeDashboard(
            full_name=employee.full_name,
            employee_id=employee.employee_id,
            group_code=employee.group.code if employee.group else None,
            total_orders=int(s.get("total_orders", 0)),
            successful_orders=successful_orders,
            cancelled_orders=int(s.get("cancelled_orders", 0)),
            pending_orders=int(s.get("pending_orders", 0)),
            total_sales=total_sales,
            successful_sales=successful_sales,
            perv_sales=perv_sales,
            baza_sales=baza_sales,
            otkaz_sales=otkaz_sales,
            v_proc_sales=v_proc_sales,
            total_profit=Decimal(str(s.get("total_profit", "0.00"))),
            monthly_salary=employee.monthly_salary,
            earned_salary=earned_salary,
            conversion_rate=conversion_rate,
            real_conversion_rate=real_conversion_rate,
            sources=self.statistics.employee_sources(employee.pk),
            month_str=self.statistics.get_active_month_str(),
        )


    def _group_dashboard(self, group: SalesGroup, leader: Employee) -> GroupDashboard:
        if not group.synced_at and group.group_profit == Decimal("0.00") and group.leader_bonus == Decimal("0.00"):
            raise ValidationError("Guruh ma'lumotlari sozlanmagan. Administratorga murojaat qiling.")

        return GroupDashboard(
            group_code=group.code,
            group_name=group.name,
            successful_orders=0,
            total_profit=group.group_profit,
            leader_bonus=group.leader_bonus,
            leader_personal_profit=Decimal("0.00"),
            month_str=self.statistics.get_active_month_str(),
        )