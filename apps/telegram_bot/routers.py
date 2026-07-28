"""Aiogram routers; handlers delegate sync & data access to application services."""

from __future__ import annotations

import asyncio
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from asgiref.sync import sync_to_async
from django.utils import timezone

from apps.accounts.services.binding import TelegramBindingService
from apps.common.services.exceptions import DomainError
from apps.imports.dto import normalize_employee_id
from apps.imports.models import SyncLog
from apps.imports.services.sheets_sync import SheetsSyncService
from apps.statistics.services.statistics import StatisticsService
from apps.telegram_bot.services.formatting import employee_dashboard_text, group_dashboard_text

router = Router(name="sales_bot")


def _run_background_sync() -> None:
    try:
        SheetsSyncService().sync_if_needed(force=False)
    except Exception:
        pass


async def ensure_fresh_data_and_get_timestamp() -> tuple[str, bool]:
    """Get DB sync timestamp instantly (0.001s) and trigger non-blocking background sync if needed."""
    log = await sync_to_async(SyncLog.get_last_successful)()
    now = timezone.now()

    # Trigger background sync if last sync was > 45 seconds ago or never
    if not log or not log.finished_at or (now - log.finished_at).total_seconds() > 45:
        asyncio.create_task(asyncio.to_thread(_run_background_sync))

    is_stale = False
    if log and log.finished_at:
        formatted_ts = log.finished_at.strftime("%d.%m.%Y %H:%M:%S")
    elif log and log.started_at:
        formatted_ts = log.started_at.strftime("%d.%m.%Y %H:%M:%S")
    else:
        formatted_ts = "Hozirgina"

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
    """Bind the sender Telegram identity and return full employee calculations instantly."""
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
    """Return requested or bound employee's dashboard instantly."""
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
    """Return a group dashboard only when the sender is that group's leader instantly."""
    if message.from_user is None:
        return

    ts_str, is_stale = await ensure_fresh_data_and_get_timestamp()

    try:
        dashboard = await sync_to_async(StatisticsService().group_dashboard_for_telegram)(message.from_user.id)
        text = group_dashboard_text(dashboard) + format_footer(ts_str, is_stale)
        await message.answer(text)
    except DomainError as exc:
        await message.answer(str(exc) + format_footer(ts_str, is_stale))
