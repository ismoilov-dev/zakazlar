"""Telegram message rendering. Contains no business calculations."""

import html
import logging
from datetime import date
from decimal import Decimal
from typing import Any

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from django.utils import timezone

logger = logging.getLogger(__name__)

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


def xizmatlar_menu_keyboard(
    period_iso: str | None = None,
    show_rop_switch: bool = False,
    src: str | None = None,
) -> InlineKeyboardMarkup:
    """Render the XIZMATLAR inline keyboard matching the required layout."""
    builder = InlineKeyboardBuilder()
    suffix = f":{period_iso}" if period_iso else ""
    src_suffix = f":src={src}" if src else ""

    builder.button(text="💵 JAMI OYLIK", callback_data=f"xm_card:earned_salary{suffix}{src_suffix}")
    builder.button(text="📊 JAMI SAVDO", callback_data=f"xm_card:total_sales{suffix}{src_suffix}")
    builder.button(text="✅ Uspeshka", callback_data=f"xm_card:uspeshka{suffix}{src_suffix}")
    builder.button(text="❌ Otkaz", callback_data=f"xm_card:otkaz{suffix}{src_suffix}")
    builder.button(text="⏳ Jarayonda", callback_data=f"xm_card:v_proc{suffix}{src_suffix}")
    builder.button(text="📋 ZAKAZLAR", callback_data=f"xm_orders{suffix}{src_suffix}")
    builder.button(text="🗓 AVVALGI OYLIKLAR", callback_data=f"xm_months{src_suffix}")

    if show_rop_switch:
        builder.button(text="👔 ROP PANELI", callback_data="xm_switch_rop")

    if period_iso:
        builder.button(text="⬅️ Oylarni tanlash", callback_data=f"xm_months{src_suffix}")
        if show_rop_switch:
            builder.adjust(1, 1, 3, 1, 1, 1, 1)
        else:
            builder.adjust(1, 1, 3, 1, 1, 1)
    else:
        if show_rop_switch:
            builder.adjust(1, 1, 3, 1, 1, 1)
        else:
            builder.adjust(1, 1, 3, 1, 1)

    return builder.as_markup()


STATUS_EMOJI_MAP = {
    "successful": "✅ Muvaffaqiyatli",
    "cancelled": "❌ Otkaz",
    "pending": "⏳ Jarayonda",
}


def order_status_picker_text() -> str:
    return "📋 <b>Zakazlar</b>"


def order_status_picker_keyboard(
    counts: dict[str, int] | None = None,
    period_iso: str | None = None,
    src: str | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    counts = counts or {}

    succ_cnt = counts.get("successful")
    canc_cnt = counts.get("cancelled")
    pend_cnt = counts.get("pending")

    succ_text = f"✅ Muvaffaqiyatli ({succ_cnt})" if succ_cnt is not None else "✅ Muvaffaqiyatli"
    canc_text = f"❌ Otkaz ({canc_cnt})" if canc_cnt is not None else "❌ Otkaz"
    pend_text = f"⏳ Jarayonda ({pend_cnt})" if pend_cnt is not None else "⏳ Jarayonda"

    suffix = f":{period_iso}" if period_iso else ""
    src_suffix = f":src={src}" if src else ""

    builder.button(text=succ_text, callback_data=f"ord_status:successful{suffix}{src_suffix}")
    builder.button(text=canc_text, callback_data=f"ord_status:cancelled{suffix}{src_suffix}")
    builder.button(text=pend_text, callback_data=f"ord_status:pending{suffix}{src_suffix}")

    back_target = f"xm_menu{suffix}{src_suffix}"
    builder.button(text="⬅️ Xizmatlarga qaytish", callback_data=back_target)

    builder.adjust(2, 1, 1)
    return builder.as_markup()


def order_list_text(
    orders: list[Any],
    status: str,
    total_count: int,
    page: int,
    total_pages: int,
    period_label: str,
) -> str:
    if total_count == 0 or not orders:
        return "Bu holatda zakazlar yo'q."

    status_title = STATUS_EMOJI_MAP.get(status, status)
    header = f"{status_title} — {total_count} ta\n📅 {period_label}"

    offset = (page - 1) * 5
    items = []

    for idx, sale in enumerate(orders, start=offset + 1):
        lines = [f"{idx})"]

        raw_ord_id = getattr(sale, "external_order_id", "") or ""
        if raw_ord_id:
            parts = str(raw_ord_id).split("_")
            order_num = parts[-1] if len(parts) >= 3 else str(raw_ord_id)
        else:
            order_num = ""

        if order_num:
            lines.append(f"🆔 Raqam: {order_num}")

        c_name = sale.client_name.strip() if getattr(sale, "client_name", None) else ""
        if c_name:
            lines.append(f"👤 Mijoz: {c_name}")

        amt_str = money(getattr(sale, "sale_amount", None), bold=False)
        lines.append(f"💰 Narxi: {amt_str}")

        p_name_1 = sale.product_name.strip() if getattr(sale, "product_name", None) else ""
        qty_val_1 = getattr(sale, "quantity", None)
        if p_name_1 and qty_val_1 is not None:
            lines.append(f"💊 Tovar: {p_name_1} — {qty_val_1} ta")
        elif p_name_1:
            lines.append(f"💊 Tovar: {p_name_1}")
        elif qty_val_1 is not None:
            lines.append(f"💊 Tovar: {qty_val_1} ta")

        p_name_2 = sale.product_name_2.strip() if getattr(sale, "product_name_2", None) else ""
        qty_val_2 = getattr(sale, "quantity_2", None)
        if p_name_2 and qty_val_2 is not None:
            lines.append(f"💊 Tovar 2: {p_name_2} — {qty_val_2} ta")
        elif p_name_2:
            lines.append(f"💊 Tovar 2: {p_name_2}")
        elif qty_val_2 is not None:
            lines.append(f"💊 Tovar 2: {qty_val_2} ta")

        dt = getattr(sale, "ordered_at", None)
        if dt:
            dt_str = timezone.localtime(dt).strftime("%d.%m.%Y")
            lines.append(f"📅 Vaqti: {dt_str}")

        items.append("\n".join(lines))

    return header + "\n\n" + "\n\n".join(items)


def order_list_keyboard(
    status: str,
    page: int,
    total_pages: int,
    period_iso: str | None = None,
    src: str | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    suffix = f":{period_iso}" if period_iso else ""
    src_suffix = f":src={src}" if src else ""

    nav_count = 0
    if page > 1:
        builder.button(text="⬅️ Oldingi", callback_data=f"ord_list:{status}:p={page - 1}{suffix}{src_suffix}")
        nav_count += 1
    if page < total_pages:
        builder.button(text="Keyingi ➡️", callback_data=f"ord_list:{status}:p={page + 1}{suffix}{src_suffix}")
        nav_count += 1

    picker_target = f"xm_orders{suffix}{src_suffix}"
    builder.button(text="⬅️ Zakaz holatlariga qaytish", callback_data=picker_target)

    back_target = f"xm_menu{suffix}{src_suffix}"
    builder.button(text="⬅️ Xizmatlarga qaytish", callback_data=back_target)

    adjust_spec = []
    if nav_count > 0:
        adjust_spec.append(nav_count)
    adjust_spec.append(1)
    adjust_spec.append(1)

    builder.adjust(*adjust_spec)
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


def money(value: Decimal | None, *, bold: bool = True) -> str:
    """Render a sum for Telegram. Returns the missing-value text for None."""
    if value is None:
        return MISSING_VALUE_TEXT
    val_int = int(round(value))
    formatted = f"{val_int:,}".replace(",", "\u00A0")
    formatted_str = f"{formatted} so'm"
    if bold:
        return f"<b>{formatted_str}</b>"
    return formatted_str


def calculate_sal_1_15_from_sales(
    employee_id: str | None,
    period_date: date | None = None,
    group_code: str = "A",
) -> Decimal | None:
    """Calculate 1-15 day salary dynamically from parsed Sale records for the target period."""
    if not employee_id:
        return None
    try:
        from apps.imports.models import SpreadsheetPeriod
        from apps.sales.models import Sale, SaleSource, SaleStatus
        from django.utils import timezone

        if period_date is None:
            active_sp = SpreadsheetPeriod.objects.filter(is_active=True).first()
            target_date = active_sp.period if active_sp else timezone.localtime().date()
        else:
            target_date = period_date

        sales_1_15 = Sale.objects.filter(
            employee__employee_id=employee_id,
            status=SaleStatus.SUCCESSFUL,
            ordered_at__year=target_date.year,
            ordered_at__month=target_date.month,
            ordered_at__day__lte=15,
        )

        if not sales_1_15.exists():
            return None

        perv_sum = Decimal("0")
        baza_sum = Decimal("0")
        for s in sales_1_15:
            amt = s.sale_amount or Decimal("0")
            if s.source == SaleSource.BAZA:
                baza_sum += amt
            else:
                perv_sum += amt

        grp_upper = (group_code or "").strip().upper()
        if grp_upper == "BAZA":
            return (perv_sum * Decimal("0.12")) + (baza_sum * Decimal("0.12"))
        return (perv_sum * Decimal("0.12")) + (baza_sum * Decimal("0.16"))
    except Exception as exc:
        logger.warning("Failed to calculate 1-15 salary from sales for %s: %s", employee_id, exc)
        return None


def calculate_sal_16_31_from_sales(
    employee_id: str | None,
    period_date: date | None = None,
    group_code: str = "A",
) -> Decimal | None:
    """Calculate 16-31 day salary dynamically from parsed Sale records for the target period."""
    if not employee_id:
        return None
    try:
        from apps.imports.models import SpreadsheetPeriod
        from apps.sales.models import Sale, SaleSource, SaleStatus
        from django.utils import timezone

        if period_date is None:
            active_sp = SpreadsheetPeriod.objects.filter(is_active=True).first()
            target_date = active_sp.period if active_sp else timezone.localtime().date()
        else:
            target_date = period_date

        sales_16_31 = Sale.objects.filter(
            employee__employee_id=employee_id,
            status=SaleStatus.SUCCESSFUL,
            ordered_at__year=target_date.year,
            ordered_at__month=target_date.month,
            ordered_at__day__gte=16,
        )

        if not sales_16_31.exists():
            return None

        perv_sum = Decimal("0")
        baza_sum = Decimal("0")
        for s in sales_16_31:
            amt = s.sale_amount or Decimal("0")
            if s.source == SaleSource.BAZA:
                baza_sum += amt
            else:
                perv_sum += amt

        grp_upper = (group_code or "").strip().upper()
        if grp_upper == "BAZA":
            return (perv_sum * Decimal("0.12")) + (baza_sum * Decimal("0.12"))
        return (perv_sum * Decimal("0.12")) + (baza_sum * Decimal("0.16"))
    except Exception as exc:
        logger.warning("Failed to calculate 16-31 salary from sales for %s: %s", employee_id, exc)
        return None


def card_text(
    card_type: str,
    full_name: str,
    group_code: str,
    summary_data: dict[str, Any] | None,
    period_label: str | None = None,
    fallback_salary: Decimal | None = None,
    employee_id: str | None = None,
    period_date: date | None = None,
    db_totals: dict[str, Any] | None = None,
) -> str:
    """Render focused card text for an employee figure."""
    data = summary_data or {}
    safe_name = html.escape(full_name.strip())
    safe_group = html.escape(str(group_code))
    lines = [f"👤 <b>{safe_name}</b>", f"🏢 Bo'lim: <b>{safe_group}</b>"]
    if period_label:
        lines.append(f"📅 Oy: <b>{html.escape(str(period_label))}</b>")
    lines.append("")

    if period_label and (summary_data is None or not summary_data):
        lines.append("Bu oy uchun ma'lumot saqlanmagan.")
        return "\n".join(lines)

    db_sales_total: Decimal | None = None
    db_sales_successful: Decimal | None = None
    db_sales_pending: Decimal | None = None
    db_sales_cancelled: Decimal | None = None

    totals = db_totals
    if totals is None and employee_id:
        try:
            from apps.employees.models import Employee
            from apps.statistics.repositories.statistics import StatisticsRepository
            from asgiref.sync import async_to_sync, sync_to_async

            def _fetch():
                emp = Employee.objects.filter(employee_id=employee_id).first()
                if emp:
                    return StatisticsRepository().employee_totals(emp.id, target_date=period_date)
                return None

            try:
                totals = _fetch()
            except Exception:
                totals = async_to_sync(sync_to_async(_fetch))()
        except Exception as exc:
            logger.warning("Could not calculate employee totals for employee_id=%s: %s", employee_id, exc)

    if totals and totals.get("total_orders", 0) > 0:
        db_sales_total = totals.get("total_sales")
        perv = totals.get("perv_sales") or Decimal("0")
        baza = totals.get("baza_sales") or Decimal("0")
        db_sales_successful = perv + baza
        db_sales_pending = totals.get("v_proc_sales")
        db_sales_cancelled = totals.get("otkaz_sales")

    if card_type in ("earned_salary", "salary_1_15", "salary_16_31"):
        raw_sal = data.get("earned_salary")
        sal = _parse_decimal_val(raw_sal)
        if sal is None and fallback_salary is not None and not period_label:
            sal = fallback_salary

        perv = _parse_decimal_val(data.get("perv_sales"))
        baza = _parse_decimal_val(data.get("baza_sales"))
        if perv is not None or baza is not None:
            p_val = perv or Decimal("0")
            b_val = baza or Decimal("0")
            grp_upper = (group_code or "").strip().upper()
            if grp_upper == "BAZA":
                calc_sal = (p_val * Decimal("0.12")) + (b_val * Decimal("0.12"))
            else:
                calc_sal = (p_val * Decimal("0.12")) + (b_val * Decimal("0.16"))

            if calc_sal > Decimal("0") and (sal is None or calc_sal > sal):
                sal = calc_sal

        sal_1_15 = _parse_decimal_val(data.get("earned_salary_1_15") or data.get("salary_1_15"))
        sal_16_31 = _parse_decimal_val(data.get("earned_salary_16_31") or data.get("salary_16_31"))

        if sal_1_15 is None and employee_id:
            sal_1_15 = calculate_sal_1_15_from_sales(employee_id, period_date, group_code)

        if sal_16_31 is None and employee_id:
            sal_16_31 = calculate_sal_16_31_from_sales(employee_id, period_date, group_code)

        import calendar
        from decimal import ROUND_HALF_UP

        target_dt = period_date or timezone.localtime().date()
        num_days = calendar.monthrange(target_dt.year, target_dt.month)[1]

        if sal_1_15 is not None and sal_16_31 is not None and (sal_1_15 > Decimal("0") or sal_16_31 > Decimal("0")):
            calc_sum = sal_1_15 + sal_16_31
            if sal is None or calc_sum > sal:
                sal = calc_sum
            elif sal > calc_sum:
                sal_16_31 = sal - sal_1_15
        elif sal is not None and sal > Decimal("0"):
            if sal_1_15 is not None and sal_1_15 > Decimal("0") and sal_1_15 < sal:
                sal_16_31 = sal - sal_1_15
            elif sal_16_31 is not None and sal_16_31 > Decimal("0") and sal_16_31 < sal:
                sal_1_15 = sal - sal_16_31
            else:
                sal_1_15 = (sal * Decimal("15") / Decimal(str(num_days))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                sal_16_31 = sal - sal_1_15
        elif sal_1_15 is not None or sal_16_31 is not None:
            s1 = sal_1_15 or Decimal("0")
            s2 = sal_16_31 or Decimal("0")
            sal = s1 + s2
            sal_1_15 = s1
            sal_16_31 = s2

        if card_type == "earned_salary":
            lines.append(f"💵 Shaxsiy oylik: {money(sal)}")

        elif card_type == "salary_1_15":
            lines.append("🗓 <b>1 - 15 kunlik oylik hisoboti</b>\n")
            val = sal_1_15 if sal_1_15 is not None else sal
            lines.append(f"💵 1-15 kunlik oylik: {money(val)}")

        elif card_type == "salary_16_31":
            lines.append("🗓 <b>16 - 31 kunlik oylik hisoboti</b>\n")
            lines.append(f"💵 16-31 kunlik oylik: {money(sal_16_31)}")

    elif card_type == "total_sales":
        l2_ts = _parse_decimal_val(data.get("total_sales"))
        ts = l2_ts if (l2_ts is not None and l2_ts > Decimal("0")) else db_sales_total
        lines.append(f"📊 Jami savdo: {money(ts)}")

    elif card_type == "uspeshka":
        l2_ss = _parse_decimal_val(data.get("successful_sales"))
        ss = l2_ss if (l2_ss is not None and l2_ss > Decimal("0")) else db_sales_successful

        so_raw = data.get("successful_orders")
        conv_raw = data.get("conversion_rate")
        rconv_raw = data.get("real_conversion_rate")

        lines.append(f"✅ Uspeshka summasi: {money(ss)}")

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
        l2_otkaz = _parse_decimal_val(data.get("otkaz_sales"))
        otkaz = l2_otkaz if (l2_otkaz is not None and l2_otkaz > Decimal("0")) else db_sales_cancelled
        lines.append(f"❌ Otkaz summasi: {money(otkaz)}")

    elif card_type == "v_proc":
        l2_vp = _parse_decimal_val(data.get("v_proc_sales"))
        vp = l2_vp if (l2_vp is not None and l2_vp > Decimal("0")) else db_sales_pending
        lines.append(f"⏳ Jarayondagi summa: {money(vp)}")

    return "\n".join(lines)


def card_keyboard(
    period_iso: str | None = None,
    src: str | None = None,
    card_type: str | None = None,
) -> InlineKeyboardMarkup:
    """Render inline keyboard for focused card navigation."""
    builder = InlineKeyboardBuilder()
    suffix = f":{period_iso}" if period_iso else ""
    src_suffix = f":src={src}" if src else ""

    if card_type in ("earned_salary", "salary_1_15", "salary_16_31"):
        builder.button(text="📅 1-15 kunlik oylik", callback_data=f"xm_card:salary_1_15{suffix}{src_suffix}")
        builder.button(text="📅 16-31 kunlik oylik", callback_data=f"xm_card:salary_16_31{suffix}{src_suffix}")
        if card_type != "earned_salary":
            builder.button(text="💵 Jami oylik", callback_data=f"xm_card:earned_salary{suffix}{src_suffix}")

    back_target = f"xm_menu:{period_iso}{src_suffix}" if period_iso else f"xm_menu{src_suffix}"
    builder.button(text="⬅️ Xizmatlarga qaytish", callback_data=back_target)

    if period_iso:
        builder.button(text="⬅️ Oylarni tanlash", callback_data=f"xm_months{src_suffix}")

    if card_type in ("earned_salary", "salary_1_15", "salary_16_31"):
        if period_iso:
            if card_type != "earned_salary":
                builder.adjust(2, 1, 1, 1)
            else:
                builder.adjust(2, 1, 1)
        else:
            if card_type != "earned_salary":
                builder.adjust(2, 1, 1)
            else:
                builder.adjust(2, 1)
    else:
        if period_iso:
            builder.adjust(1, 1)
        else:
            builder.adjust(1)

    return builder.as_markup()


def period_selector_keyboard(periods: list[tuple[date, str]], src: str | None = None) -> InlineKeyboardMarkup:
    """Render inline keyboard for selecting historical period."""
    builder = InlineKeyboardBuilder()
    src_suffix = f":src={src}" if src else ""
    for period_date, period_label in periods:
        builder.button(
            text=f"📅 {period_label}",
            callback_data=f"xm_period:{period_date.isoformat()}{src_suffix}",
        )
    builder.button(text="⬅️ Xizmatlarga qaytish", callback_data=f"xm_menu{src_suffix}")
    builder.adjust(2)
    return builder.as_markup()


def group_dashboard_text(dashboard: GroupDashboard) -> str:
    """Render a group-leader dashboard without performing calculations."""
    month_str = dashboard.month_str or timezone.localtime().strftime("%m.%Y")

    return (
        f"👥 <b>Guruh ko'rsatkichlari: {dashboard.group_name} ({dashboard.group_code})</b>\n"
        f"📅 Oy: <b>{month_str}</b>\n\n"
        f"📊 Guruh umumiy zakaz summasi: {money(dashboard.total_sales)}\n"
        f"💰 Guruh foydasi (Muvaffaqiyatli): {money(dashboard.total_profit)}\n"
        f"💰 Rahbar bonusi (2%): {money(dashboard.leader_bonus)}"
    )


def rop_menu_text(full_name: str, group_code: str, employee_id: str) -> str:
    """Render ROP main menu text."""
    safe_name = html.escape(full_name.strip())
    safe_group = html.escape(str(group_code))
    safe_id = html.escape(str(employee_id))
    return (
        f"👤 <b>{safe_name}</b>\n"
        f"🏢 Bo'lim: <b>{safe_group}</b>\n"
        f"🆔 ID: <code>{safe_id}</code>\n\n"
        f"<b>XIZMATLAR</b>"
    )


def rop_menu_keyboard() -> InlineKeyboardMarkup:
    """Render ROP main menu inline keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 GURUH SAVDOSI", callback_data="rop_card:group_sales")
    builder.button(text="📈 GURUH STATS", callback_data="rop_card:group_stats")
    builder.button(text="💵 ROP OYLIK", callback_data="rop_card:rop_salary")
    builder.button(text="💰 MOP OYLIK", callback_data="rop_card:mop_salary")
    builder.button(text="👥 XODIMLAR RO'YXATI", callback_data="rop_card:employee_list")
    builder.button(text="👤 SHAXSIY XIZMATLAR", callback_data="rop_card:mop_xizmatlar")
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()


def rop_employee_filter_menu_keyboard() -> InlineKeyboardMarkup:
    """Render filter selection keyboard for ROP employee list."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Sotuvi bor", callback_data="rop_emp_filter:has_sales:1")
    builder.button(text="⭕ Sotuvi yo'q", callback_data="rop_emp_filter:no_sales:1")
    builder.button(text="📋 Barchasi", callback_data="rop_emp_filter:all:1")
    builder.button(text="⬅️ Xizmatlarga qaytish", callback_data="rop_menu")
    builder.adjust(2, 1, 1)
    return builder.as_markup()


def rop_employee_list_keyboard(filter_key: str, page: int, total_pages: int) -> InlineKeyboardMarkup:
    """Render pagination and back buttons for ROP employee list."""
    builder = InlineKeyboardBuilder()

    if total_pages > 1:
        if page > 1:
            builder.button(text="⬅️ Oldingi", callback_data=f"rop_emp_filter:{filter_key}:{page - 1}")
        if page < total_pages:
            builder.button(text="Keyingi ➡️", callback_data=f"rop_emp_filter:{filter_key}:{page + 1}")

    builder.button(text="⬅️ Filtrlashga qaytish", callback_data="rop_card:employee_list")
    builder.button(text="⬅️ Xizmatlarga qaytish", callback_data="rop_menu")

    if total_pages > 1:
        if page > 1 and page < total_pages:
            builder.adjust(2, 1, 1)
        else:
            builder.adjust(1, 1, 1)
    else:
        builder.adjust(1, 1)

    return builder.as_markup()


FILTER_LABELS = {
    "has_sales": "Sotuvi bor",
    "no_sales": "Sotuvi yo'q",
    "all": "Barchasi",
}


def rop_employee_list_card_text(
    group_code: str,
    filter_key: str,
    employees: list[dict[str, Any]],
    page: int,
    total_count: int,
    page_size: int = 20,
) -> str:
    """Render formatted employee list text for ROP card."""
    filter_label = FILTER_LABELS.get(filter_key, "Barchasi")
    lines = [f"👥 <b>{group_code} guruh — {filter_label} ({total_count} ta)</b>\n"]

    start_idx = (page - 1) * page_size
    page_items = employees[start_idx : start_idx + page_size]

    uncalculated_count = sum(1 for e in employees if e["has_error"])

    if not page_items:
        lines.append("<i>Birorta ham xodim topilmadi.</i>")
    else:
        for idx, emp in enumerate(page_items, start=start_idx + 1):
            emp_id = emp["employee_id"]
            name = emp["full_name"]
            sales_val = emp["sales_val"]
            orders_val = emp["orders_val"]
            has_error = emp["has_error"]

            lines.append(f"{idx}. {emp_id} {name}")

            if has_error:
                lines.append("   📊 —")
            elif filter_key == "no_sales" and (sales_val is None or sales_val == Decimal("0")):
                pass
            elif sales_val is not None and sales_val > Decimal("0"):
                sales_str = money(sales_val, bold=False)
                if orders_val is not None:
                    orders_str = f"📦 {orders_val} ta"
                else:
                    orders_str = "📦 —"
                lines.append(f"   📊 {sales_str} · {orders_str}")

    if uncalculated_count > 0:
        lines.append(f"\n⚠️ {uncalculated_count} ta xodimning ma'lumoti hisoblanmagan.")

    return "\n".join(lines)


def rop_card_keyboard() -> InlineKeyboardMarkup:
    """Render back button for ROP cards."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Xizmatlarga qaytish", callback_data="rop_menu")
    builder.adjust(1)
    return builder.as_markup()


def rop_group_sales_card_text(group_code: str, totals: dict[str, Decimal | None]) -> str:
    """Render GURUH SAVDOSI card text."""
    lines = [f"🏢 <b>{group_code} guruh</b>\n"]
    for label, key in [
        ("📊 Jami savdo", "total_sales"),
        ("✅ Uspeshka", "successful_sales"),
        ("❌ Otkaz", "otkaz_sales"),
        ("⏳ Jarayonda", "v_proc_sales"),
    ]:
        val = totals.get(key)
        lines.append(f"{label}: {money(val)}")
    return "\n".join(lines)


def rop_group_stats_card_text(group_code: str, stats: dict[str, int | None]) -> str:
    """Render GURUH STATS card text."""
    lines = [
        f"🏢 <b>{group_code} guruh</b>\n",
        f"👥 Xodimlar soni: <b>{stats['total_count']} ta</b>",
    ]
    if stats.get("total_upakovka") is not None:
        lines.append(f"📦 Jami upakovka: <b>{stats['total_upakovka']} ta</b>")
    else:
        lines.append(f"📦 Jami upakovka: {MISSING_VALUE_TEXT}")
    lines.append(f"🟢 Faol xodimlar: <b>{stats['active_count']} ta</b>")
    return "\n".join(lines)


def rop_salary_card_text(group_code: str, salary_info: dict[str, Any]) -> str:
    """Render ROP OYLIK card text with inputs, calculated salary, and mismatch warning if present."""
    lines = [
        f"🏢 <b>{group_code} guruh</b>\n",
        f"📊 Guruh jami savdosi: {money(salary_info.get('group_total_sales'))}",
        f"✅ Guruh uspeshka summasi: {money(salary_info.get('group_successful_sales'))}",
        f"📐 Foiz: <b>{salary_info['rate_pct_str']}</b>",
        f"💵 ROP oyligi: {money(salary_info.get('computed_salary'))}",
    ]

    uncalc_count = salary_info.get("uncalculated_uspeshka_count", 0)
    if uncalc_count > 0:
        lines.append(f"\n⚠️ {uncalc_count} ta xodimning uspeshka summasi hisoblanmagan.")

    if salary_info.get("mismatch"):
        lines.append(
            "\n⚠️ Diqqat: bu raqam Google Sheets'dagi qiymatdan farq qilmoqda.\nAdministratorga murojaat qiling."
        )
    return "\n".join(lines)