from django.utils import timezone

from apps.statistics.services.statistics import EmployeeDashboard, GroupDashboard


def employee_dashboard_text(dashboard: EmployeeDashboard) -> str:
    """Render an employee dashboard without performing business calculations."""
    group = dashboard.group_code or "Biriktirilmagan"
    conv_pct = f"{dashboard.conversion_rate * 100:.2f}%"
    real_conv_pct = f"{dashboard.real_conversion_rate * 100:.2f}%"
    month_str = timezone.localtime().strftime("%m.%Y")
    
    sources = "\n".join(
        f"• {item['source'] or 'Noma\'lum'}: {item['successful_orders']} ta uspešno, "
        f"{item['cancelled_orders']} ta otkaz, {item['successful_sales']:,.0f} so'm"
        for item in dashboard.sources
    ) or "Ma'lumot yo'q"
    
    return (
        f"👤 <b>{dashboard.full_name.strip()}</b>\n"
        f"🆔 ID: <code>{dashboard.employee_id}</code>\n"
        f"🏢 Bo'lim: <b>{group}</b>\n"
        f"📅 Oy: <b>{month_str}</b>\n\n"
        f"📦 Upakovka (Muvaffaqiyatli): <b>{dashboard.successful_orders} ta</b>\n"
        f"❌ Otraz (Bekor qilingan): <b>{dashboard.cancelled_orders} ta</b>\n"
        f"⏳ V protsess (Jarayonda): <b>{dashboard.pending_orders} ta</b>\n"
        f"📋 Jami zakazlar: <b>{dashboard.total_orders} ta</b>\n\n"
        f"💰 <b>Finansoviy Hisob-kitob:</b>\n"
        f"• Umumiy zakaz summasi: <b>{dashboard.total_sales:,.0f} so'm</b>\n"
        f"• Первичный Заказ: <b>{dashboard.perv_sales:,.0f} so'm</b>\n"
        f"• База: <b>{dashboard.baza_sales:,.0f} so'm</b>\n"
        f"• Отказ summasi: <b>{dashboard.otkaz_sales:,.0f} so'm</b>\n"
        f"• В процесс summasi: <b>{dashboard.v_proc_sales:,.0f} so'm</b>\n\n"
        f"💵 <b>ISHLAGAN PULI (Oylik maosh):</b> <b>{dashboard.earned_salary:,.0f} so'm</b>\n"
        f"📈 Konversiya: <b>{conv_pct}</b> | Real Konversiya: <b>{real_conv_pct}</b>\n\n"
        f"<b>Manbalar bo'yicha:</b>\n{sources}"
    )



def group_dashboard_text(dashboard: GroupDashboard) -> str:
    """Render a group-leader dashboard without performing calculations."""
    month_str = timezone.localtime().strftime("%m.%Y")
    return (
        f"<b>{dashboard.group_name} ({dashboard.group_code})</b>\n"
        f"📅 Oy: <b>{month_str}</b>\n\n"
        f"Muvaffaqiyatli savdolar: <b>{dashboard.successful_orders}</b>\n"
        f"Guruh foydasi: <b>{dashboard.total_profit:,.2f}</b>\n"
        f"Rahbar 2% bonusi: <b>{dashboard.leader_bonus:,.2f}</b>\n"
        f"Shaxsiy savdo foydasi: <b>{dashboard.leader_personal_profit:,.2f}</b>"
    )
