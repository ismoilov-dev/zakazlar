"""Telegram message rendering. Contains no business calculations."""

from django.utils import timezone

from apps.statistics.services.statistics import EmployeeDashboard, GroupDashboard


def employee_dashboard_text(dashboard: EmployeeDashboard) -> str:
    """Render an employee dashboard: salary, packaging count, successful, cancelled and pending sums plus conversion."""
    month_str = dashboard.month_str or timezone.localtime().strftime("%m.%Y")
    conv_pct = f"{dashboard.conversion_rate * 100:.2f}%"
    real_conv_pct = f"{dashboard.real_conversion_rate * 100:.2f}%"

    return (
        f"👤 <b>{dashboard.full_name.strip()}</b>\n"
        f"🆔 ID: <code>{dashboard.employee_id}</code>\n"
        f"📅 Oy: <b>{month_str}</b>\n\n"
        f"📦 Upakovka soni: <b>{dashboard.successful_orders}</b>\n"
        f"💵 Oylik ish haqi: <b>{dashboard.earned_salary:,.0f} so'm</b>\n\n"
        f"✅ Uspeshka summasi: <b>{dashboard.successful_sales:,.0f} so'm</b>\n"
        f"❌ Otkaz summasi: <b>{dashboard.otkaz_sales:,.0f} so'm</b>\n"
        f"⏳ V protsess summasi: <b>{dashboard.v_proc_sales:,.0f} so'm</b>\n\n"
        f"📈 Konversiya: <b>{conv_pct}</b>\n"
        f"📊 Real konversiya: <b>{real_conv_pct}</b>"
    )



def group_dashboard_text(dashboard: GroupDashboard) -> str:
    """Render a group-leader dashboard without performing calculations."""
    month_str = dashboard.month_str or timezone.localtime().strftime("%m.%Y")
    profit_text = f"<b>{dashboard.total_profit:,.0f} so'm</b>"
    bonus_text = f"<b>{dashboard.leader_bonus:,.0f} so'm</b>"

    return (
        f"👥 <b>Guruh ko'rsatkichlari: {dashboard.group_name} ({dashboard.group_code})</b>\n"
        f"📅 Oy: <b>{month_str}</b>\n\n"
        f"💰 Guruh foydasi: {profit_text}\n"
        f"💵 Rahbar bonusi: {bonus_text}"
    )