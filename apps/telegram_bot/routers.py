"""Aiogram routers; handlers delegate sync & data access to application services."""

from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from asgiref.sync import sync_to_async
from django.utils import timezone

logger = logging.getLogger(__name__)

from apps.accounts.services.binding import TelegramBindingService
from apps.common.services.exceptions import DomainError
from apps.imports.dto import normalize_employee_id
from apps.imports.models import SyncLog, SyncStatus
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
    last_attempt = await sync_to_async(SyncLog.objects.order_by("-started_at").first)()
    last_successful = await sync_to_async(SyncLog.get_last_successful)()
    now = timezone.now()

    # Trigger background sync if last sync was > 10 seconds ago or never
    if not last_successful or not last_successful.finished_at or (now - last_successful.finished_at).total_seconds() > 10:
        asyncio.create_task(asyncio.to_thread(_run_background_sync))

    is_stale = False
    if last_attempt and last_attempt.status == SyncStatus.FAILED:
        is_stale = True
    elif not last_successful:
        is_stale = True
    elif last_successful and last_successful.finished_at:
        if (now - last_successful.finished_at).total_seconds() > 300:
            is_stale = True

    if last_successful and last_successful.finished_at:
        formatted_ts = timezone.localtime(last_successful.finished_at).strftime("%d.%m.%Y %H:%M:%S")
    elif last_attempt and last_attempt.started_at:
        formatted_ts = timezone.localtime(last_attempt.started_at).strftime("%d.%m.%Y %H:%M:%S")
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
    """Bind the sender Telegram identity and return full employee calculations with real-time sync."""
    if message.from_user is None or message.text is None:
        return

    try:
        user_id = normalize_employee_id(message.text)
    except DomainError as exc:
        await message.answer(str(exc))
        return
    except Exception as exc:
        await message.answer(f"ID ko'rinishida xatolik: {exc}")
        return

    # Perform real-time sync with 5 second timeout so handler never hangs
    is_stale = False
    try:
        await asyncio.wait_for(
            sync_to_async(SheetsSyncService().sync_if_needed)(force=True),
            timeout=5.0,
        )
    except Exception as exc:
        logger.warning("Real-time sync failed or timed out: %s", exc)
        is_stale = True

    last_successful = await sync_to_async(SyncLog.get_last_successful)()
    if last_successful and last_successful.finished_at:
        ts_str = timezone.localtime(last_successful.finished_at).strftime("%d.%m.%Y %H:%M:%S")
    else:
        ts_str = timezone.localtime().strftime("%d.%m.%Y %H:%M:%S")

    try:
        await sync_to_async(TelegramBindingService().bind)(
            employee_id=user_id,
            telegram_id=message.from_user.id,
            username=message.from_user.username or "",
        )
    except Exception:
        pass

    try:
        dashboard = await sync_to_async(StatisticsService().employee_dashboard_for_employee)(user_id)
        text = employee_dashboard_text(dashboard) + format_footer(ts_str, is_stale)
        await message.answer(text)
    except Exception as exc:
        await message.answer(f"Ma'lumotlarni yuklashda xatolik: {exc}" + format_footer(ts_str, is_stale))


@router.message(Command("stats"))
async def employee_stats(message: Message) -> None:
    """Return requested or bound employee's dashboard with real-time sync."""
    if message.from_user is None:
        return

    is_stale = False
    try:
        await asyncio.wait_for(
            sync_to_async(SheetsSyncService().sync_if_needed)(force=True),
            timeout=5.0,
        )
    except Exception as exc:
        logger.warning("Real-time sync failed or timed out: %s", exc)
        is_stale = True

    last_successful = await sync_to_async(SyncLog.get_last_successful)()
    if last_successful and last_successful.finished_at:
        ts_str = timezone.localtime(last_successful.finished_at).strftime("%d.%m.%Y %H:%M:%S")
    else:
        ts_str = timezone.localtime().strftime("%d.%m.%Y %H:%M:%S")

    parts = (message.text or "").split()

    if len(parts) > 1 and parts[1].isdigit():
        try:
            user_id = normalize_employee_id(parts[1])
            dashboard = await sync_to_async(StatisticsService().employee_dashboard_for_employee)(user_id)
            text = employee_dashboard_text(dashboard) + format_footer(ts_str, is_stale)
            await message.answer(text)
            return
        except Exception as exc:
            await message.answer(f"Ma'lumotlarni yuklashda xatolik: {exc}" + format_footer(ts_str, is_stale))
            return

    try:
        dashboard = await sync_to_async(StatisticsService().employee_dashboard_for_telegram)(message.from_user.id)
        text = employee_dashboard_text(dashboard) + format_footer(ts_str, is_stale)
        await message.answer(text)
    except Exception as exc:
        await message.answer(f"Ma'lumotlarni yuklashda xatolik: {exc}" + format_footer(ts_str, is_stale))


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
