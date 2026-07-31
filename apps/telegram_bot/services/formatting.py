"""Telegram message rendering. Contains no business calculations."""

from datetime import date
from decimal import Decimal
from typing import Any

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from django.utils import timezone

from apps.statistics.services.statistics import GroupDashboard

UZBEK_MONTH_NAMES = {
    1: "Yanvar",
    2: "Fevral",
    3: "Mart",
    4: "Aprel",
    5: "May",
    6: "Iyun",
    7: "Iyul",
    8: "Avgust",
    9: "Sentabr",
    10: "Oktabr",
    11: "Noyabr",
    12: "Dekabr",
}

MISSING_VALUE_TEXT = "⚠️ Bu ko'rsatkich hisoblanmagan. Rahbaringizga murojaat qiling."


def format_uzbek_period(period_date: date) -> str:
    """Format a date as 'Iyun 2026' using Uzbek month names."""
    month_name = UZBEK_MONTH_NAMES.get(period_date.month, "")
    return f"{month_name} {period_date.year}"


def xizmatlar_menu_text(period_label: str | None = None) -> str:
    """Render the header text for XIZMATLAR menu."""
    if period_label:
        return f"<b>XIZMATLAR — {period_label}</b>"
    return "<b>XIZMATLAR</b>"


def xizmatlar_menu_keyboard(period_iso: str | None = None, is_rop: bool = False) -> InlineKeyboardMarkup:
    """Render the XIZMATLAR inline keyboard matching the required layout."""
    builder = InlineKeyboardBuilder()
    suffix = f":{period_iso}" if period_iso else ""

    if is_rop:
        builder.button(text="👔 R.O.P PANELI (🔑 Parol kiritish)", callback_data="rop_prompt_password")

    builder.button(text="💵 JAMI OYLIK", callback_data=f"xm_card:earned_salary{suffix}")
    builder.button(text="📊 JAMI SAVDO", callback_data=f"xm_card:total_sales{suffix}")
    builder.button(text="✅ Uspeshka", callback_data=f"xm_card:uspeshka{suffix}")
    builder.button(text="❌ Otkaz", callback_data=f"xm_card:otkaz{suffix}")
    builder.button(text="⏳ Jarayonda", callback_data=f"xm_card:v_proc{suffix}")
    builder.button(text="🗓 AVVALGI OYLIKLAR", callback_data="xm_months")

    if period_iso:
        builder.button(text="⬅️ Oylarni tanlash", callback_data="xm_months")
        if is_rop:
            builder.adjust(1, 1, 1, 3, 1, 1)
        else:
            builder.adjust(1, 1, 3, 1, 1)
    else:
        if is_rop:
            builder.adjust(1, 1, 1, 3, 1)
        else:
            builder.adjust(1, 1, 3, 1)

    return builder.as_markup()



def _parse_decimal_val(raw: Any) -> Decimal | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, Decimal):
        return raw
    if isinstance(raw, (int, float)):
        return Decimal(str(raw))
    val_str = str(raw).replace(",", "").strip()
    if not val_str:
        return None
    try:
        return Decimal(val_str)
    except Exception:
        return None


def card_text(
    card_type: str,
    full_name: str,
    group_code: str,
    summary_data: dict[str, Any] | None,
    period_label: str | None = None,
    fallback_salary: Decimal | None = None,
) -> str:
    """Render focused card text for an employee figure."""
    data = summary_data or {}
    lines = [f"👤 <b>{full_name.strip()}</b>", f"🏢 Bo'lim: <b>{group_code}</b>"]
    if period_label:
        lines.append(f"📅 Oy: <b>{period_label}</b>")
    lines.append("")

    if card_type == "earned_salary":
        raw_sal = data.get("earned_salary")
        sal = _parse_decimal_val(raw_sal)
        if sal is None and fallback_salary is not None:
            sal = fallback_salary

        if sal is not None:
            lines.append(f"💵 Oylik ish haqi: <b>{sal:,.0f} so'm</b>")
        else:
            lines.append(MISSING_VALUE_TEXT)

    elif card_type == "total_sales":
        ts = _parse_decimal_val(data.get("total_sales"))
        if ts is not None:
            lines.append(f"📊 Jami savdo: <b>{ts:,.0f} so'm</b>")
        else:
            lines.append(MISSING_VALUE_TEXT)

    elif card_type == "uspeshka":
        ss = _parse_decimal_val(data.get("successful_sales"))
        so_raw = data.get("successful_orders")
        conv_raw = data.get("conversion_rate")
        rconv_raw = data.get("real_conversion_rate")

        if ss is not None:
            lines.append(f"✅ Uspeshka summasi: <b>{ss:,.0f} so'm</b>")
        else:
            lines.append(f"✅ Uspeshka summasi: {MISSING_VALUE_TEXT}")

        if so_raw is not None and str(so_raw).strip() != "":
            try:
                n_orders = int(float(str(so_raw)))
                lines.append(f"📦 Upakovka soni: <b>{n_orders} ta</b>")
            except Exception:
                lines.append(f"📦 Upakovka soni: {MISSING_VALUE_TEXT}")
        else:
            lines.append(f"📦 Upakovka soni: {MISSING_VALUE_TEXT}")

        if conv_raw is not None and str(conv_raw).strip() != "":
            try:
                c_val = float(str(conv_raw))
                lines.append(f"📈 Konversiya: <b>{c_val * 100:.2f}%</b>")
            except Exception:
                lines.append(f"📈 Konversiya: {MISSING_VALUE_TEXT}")
        else:
            lines.append(f"📈 Konversiya: {MISSING_VALUE_TEXT}")

        if rconv_raw is not None and str(rconv_raw).strip() != "":
            try:
                rc_val = float(str(rconv_raw))
                lines.append(f"📊 Real konversiya: <b>{rc_val * 100:.2f}%</b>")
            except Exception:
                lines.append(f"📊 Real konversiya: {MISSING_VALUE_TEXT}")
        else:
            lines.append(f"📊 Real konversiya: {MISSING_VALUE_TEXT}")

    elif card_type == "otkaz":
        otkaz = _parse_decimal_val(data.get("otkaz_sales"))
        if otkaz is not None:
            lines.append(f"❌ Otkaz summasi: <b>{otkaz:,.0f} so'm</b>")
        else:
            lines.append(MISSING_VALUE_TEXT)

    elif card_type == "v_proc":
        vp = _parse_decimal_val(data.get("v_proc_sales"))
        if vp is not None:
            lines.append(f"⏳ Jarayondagi summa: <b>{vp:,.0f} so'm</b>")
        else:
            lines.append(MISSING_VALUE_TEXT)

    return "\n".join(lines)


def card_keyboard(period_iso: str | None = None) -> InlineKeyboardMarkup:
    """Render inline keyboard for focused card navigation."""
    builder = InlineKeyboardBuilder()
    back_target = f"xm_menu:{period_iso}" if period_iso else "xm_menu"
    builder.button(text="⬅️ Xizmatlarga qaytish", callback_data=back_target)

    if period_iso:
        builder.button(text="⬅️ Oylarni tanlash", callback_data="xm_months")
        builder.adjust(1, 1)
    else:
        builder.adjust(1)

    return builder.as_markup()


def period_selector_keyboard(periods: list[tuple[date, str]]) -> InlineKeyboardMarkup:
    """Render inline keyboard for selecting historical period."""
    builder = InlineKeyboardBuilder()
    for period_date, period_label in periods:
        builder.button(
            text=f"📅 {period_label}",
            callback_data=f"xm_period:{period_date.isoformat()}",
        )
    builder.button(text="⬅️ Xizmatlarga qaytish", callback_data="xm_menu")
    builder.adjust(2)
    return builder.as_markup()


def group_dashboard_text(dashboard: GroupDashboard) -> str:
    """Render a group-leader dashboard without performing calculations."""
    month_str = dashboard.month_str or timezone.localtime().strftime("%m.%Y")
    total_sales_text = f"<b>{dashboard.total_sales:,.0f} so'm</b>"
    profit_text = f"<b>{dashboard.total_profit:,.0f} so'm</b>"
    bonus_text = f"<b>{dashboard.leader_bonus:,.0f} so'm</b>"

    return (
        f"👥 <b>Guruh ko'rsatkichlari: {dashboard.group_name} ({dashboard.group_code})</b>\n"
        f"📅 Oy: <b>{month_str}</b>\n\n"
        f"📦 Guruh umumiy zakaz summasi: {total_sales_text}\n"
        f"💰 Guruh foydasi (Muvaffaqiyatli): {profit_text}\n"
        f"💵 Rahbar bonusi (2%): {bonus_text}"
    )


def rop_menu_text(full_name: str, group_code: str, employee_id: str) -> str:
    """Render ROP main menu text."""
    return (
        f"👤 <b>{full_name.strip()}</b>\n"
        f"🏢 Bo'lim: <b>{group_code}</b>\n"
        f"🆔 ID: <code>{employee_id}</code>\n\n"
        f"<b>XIZMATLAR</b>"
    )


def rop_menu_keyboard() -> InlineKeyboardMarkup:
    """Render ROP main menu inline keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 GURUH SAVDOSI", callback_data="rop_card:group_sales")
    builder.button(text="📈 GURUH STATS", callback_data="rop_card:group_stats")
    builder.button(text="💵 ROP OYLIK", callback_data="rop_card:rop_salary")
    builder.button(text="👤 MOP XIZMATLAR", callback_data="rop_card:mop_xizmatlar")
    builder.adjust(2, 1, 1)
    return builder.as_markup()


def rop_card_keyboard() -> InlineKeyboardMarkup:
    """Render back button for ROP cards."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Xizmatlarga qaytish", callback_data="rop_menu")
    builder.adjust(1)
    return builder.as_markup()


def rop_group_sales_card_text(group_code: str, totals: dict[str, Decimal]) -> str:
    """Render GURUH SAVDOSI card text."""
    return (
        f"🏢 Bo'lim: <b>{group_code}</b>\n\n"
        f"📊 Jami savdo: <b>{totals['total_sales']:,.0f} so'm</b>\n"
        f"✅ Uspeshka: <b>{totals['successful_sales']:,.0f} so'm</b>\n"
        f"❌ Otkaz: <b>{totals['otkaz_sales']:,.0f} so'm</b>\n"
        f"⏳ Jarayonda: <b>{totals['v_proc_sales']:,.0f} so'm</b>"
    )


def rop_group_stats_card_text(group_code: str, stats: dict[str, int]) -> str:
    """Render GURUH STATS card text."""
    return (
        f"🏢 Bo'lim: <b>{group_code}</b>\n\n"
        f"👥 Xodimlar soni: <b>{stats['total_count']} ta</b>\n"
        f"📦 Jami upakovka: <b>{stats['total_upakovka']} ta</b>\n"
        f"🟢 Faol xodimlar: <b>{stats['active_count']} ta</b>"
    )


def rop_salary_card_text(group_code: str, salary_info: dict[str, Any]) -> str:
    """Render ROP OYLIK card text with inputs, calculated salary, and mismatch warning if present."""
    lines = [
        f"🏢 Bo'lim: <b>{group_code}</b>\n",
        f"📊 Guruh jami savdosi: <b>{salary_info['group_total_sales']:,.0f} so'm</b>",
        f"📐 Foiz: <b>{salary_info['rate_pct_str']}</b>",
        f"💵 ROP oyligi: <b>{salary_info['computed_salary']:,.0f} so'm</b>",
    ]
    if salary_info.get("mismatch"):
        lines.append(
            "\n⚠️ Diqqat: bu raqam Google Sheets'dagi qiymatdan farq qilmoqda.\nAdministratorga murojaat qiling."
        )
    return "\n".join(lines)