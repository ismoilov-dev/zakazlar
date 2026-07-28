"""Aiogram routers; handlers delegate sync & data access to application services."""

from __future__ import annotations

import asyncio
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from asgiref.sync import sync_to_async

from apps.accounts.services.binding import TelegramBindingService
from apps.common.services.exceptions import DomainError
from apps.imports.dto import normalize_employee_id
from apps.imports.models import SyncLog
from apps.imports.services.sheets_sync import SheetsSyncService
from apps.statistics.services.statistics import StatisticsService
from apps.telegram_bot.services.formatting import employee_dashboard_text, group_dashboard_text

router = Router(name="sales_bot")


async def ensure_fresh_data_and_get_timestamp() -> tuple[str, bool]:
    """Trigger Google Sheets sync in background thread safely. Return (formatted_timestamp, is_stale_flag)."""
    is_stale = False
    try:
        # Run gspread sync safely in thread without blocking event loop
        log = await asyncio.to_thread(SheetsSyncService().sync_if_needed, False)
        ts = log.finished_at or log.started_at
    except Exception:
        is_stale = True
        log = await sync_to_async(SyncLog.get_last_successful)()
        ts = log.finished_at if log else None

    if ts:
        formatted_ts = ts.strftime("%d.%m.%Y %H:%M:%S")
    else:
        formatted_ts = "Noma'lum"

    return formatted_ts, is_stale


def format_footer(ts: str, is_stale: bool) -> str:
    footer = f"\n\n🕒 <b>Ma'lumotlar holati:</b> {ts}"
    if is_stale:
        footer += "\n⚠️ <i>Google Sheets bilan aloqa o'rnatilmadi. Oxirgi saqlangan ma'lumotlar ko'rsatildi.</i>"
    return footer


@router.message(CommandStart())
async def start(message: Message) -> None:
    """Explain the Employee ID binding flow."""
    await message.answer("Xush kelibsiz. Employee ID raqamingizni yuboring. Masalan: <code>0191</code>")


@router.message(F.text.regexp(r"^\d{1,32}$"))
async def bind_and_show_employee_stats(message: Message) -> None:
    """Bind the sender Telegram identity and return full employee calculations with live sync."""
    if message.from_user is None or message.text is None:
        return

    try:
        user_id = normalize_employee_id(message.text)
    except DomainError as exc:
        await message.answer(str(exc))
        return

    ts_str, is_stale = await ensure_fresh_data_and_get_timestamp()

    try:
        await sync_to_async(TelegramBindingService().bind)(
            employee_id=user_id,
            telegram_id=message.from_user.id,
            username=message.from_user.username or "",
        )
    except DomainError:
        pass  # If already bound or non-fatal, proceed to show stats

    try:
        dashboard = await sync_to_async(StatisticsService().employee_dashboard_for_employee)(user_id)
        text = employee_dashboard_text(dashboard) + format_footer(ts_str, is_stale)
        await message.answer(text)
    except DomainError as exc:
        await message.answer(str(exc) + format_footer(ts_str, is_stale))


@router.message(Command("stats"))
async def employee_stats(message: Message) -> None:
    """Return requested or bound employee's dashboard with live sync."""
    if message.from_user is None:
        return

    ts_str, is_stale = await ensure_fresh_data_and_get_timestamp()
    parts = (message.text or "").split()

    if len(parts) > 1 and parts[1].isdigit():
        try:
            user_id = normalize_employee_id(parts[1])
            dashboard = await sync_to_async(StatisticsService().employee_dashboard_for_employee)(user_id)
            text = employee_dashboard_text(dashboard) + format_footer(ts_str, is_stale)
            await message.answer(text)
            return
        except DomainError as exc:
            await message.answer(str(exc) + format_footer(ts_str, is_stale))
            return

    try:
        dashboard = await sync_to_async(StatisticsService().employee_dashboard_for_telegram)(message.from_user.id)
        text = employee_dashboard_text(dashboard) + format_footer(ts_str, is_stale)
        await message.answer(text)
    except DomainError as exc:
        await message.answer(str(exc) + format_footer(ts_str, is_stale))


@router.message(Command("group_stats"))
async def group_stats(message: Message) -> None:
    """Return a group dashboard only when the sender is that group's leader with live sync."""
    if message.from_user is None:
        return

    ts_str, is_stale = await ensure_fresh_data_and_get_timestamp()

    try:
        dashboard = await sync_to_async(StatisticsService().group_dashboard_for_telegram)(message.from_user.id)
        text = group_dashboard_text(dashboard) + format_footer(ts_str, is_stale)
        await message.answer(text)
    except DomainError as exc:
        await message.answer(str(exc) + format_footer(ts_str, is_stale))
