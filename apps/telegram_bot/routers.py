"""Aiogram routers; handlers delegate sync & data access to application services."""

from __future__ import annotations

import asyncio
import logging

from datetime import date
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
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

STALE_THRESHOLD_SECONDS = 300
SYNC_TIMEOUT_SECONDS = 3.0

_background_tasks: set[asyncio.Task] = set()
_current_sync_task: asyncio.Task | None = None
_sync_lock = asyncio.Lock()


async def _do_sync() -> None:
    try:
        await sync_to_async(SheetsSyncService().sync_if_needed)(force=False)
    except Exception as exc:
        logger.warning("Single-flight background sync error: %s", exc)


async def ensure_fresh_data_and_get_timestamp() -> tuple[str, bool]:
    """Single-flight background sync; awaits sync with 3s timeout before returning timestamp."""
    global _current_sync_task
    now = timezone.now()
    last_successful = await sync_to_async(SyncLog.get_last_successful)()

    should_sync = False
    if not last_successful or not last_successful.finished_at or (now - last_successful.finished_at).total_seconds() > 15:
        should_sync = True

    if should_sync:
        async with _sync_lock:
            if _current_sync_task is None or _current_sync_task.done():
                task = asyncio.create_task(_do_sync())
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)
                _current_sync_task = task
            sync_task = _current_sync_task

        try:
            await asyncio.wait_for(asyncio.shield(sync_task), timeout=SYNC_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.warning("Sync timed out after %s seconds; serving existing snapshot", SYNC_TIMEOUT_SECONDS)

    last_attempt = await sync_to_async(lambda: SyncLog.objects.order_by("-started_at").first())()
    last_successful = await sync_to_async(SyncLog.get_last_successful)()

    is_stale = False
    if last_attempt and last_attempt.status == SyncStatus.FAILED:
        is_stale = True
    elif not last_successful:
        is_stale = True
    elif last_successful and last_successful.finished_at:
        if (now - last_successful.finished_at).total_seconds() > STALE_THRESHOLD_SECONDS:
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
    """Bind the sender Telegram identity and return full employee calculations instantly."""
    if message.from_user is None or message.text is None:
        return

    try:
        user_id = normalize_employee_id(message.text)
    except DomainError as exc:
        await message.answer(str(exc))
        return
    except Exception as exc:
        logger.exception("ID normalization error: %s", exc)
        await message.answer("ID formatida xatolik mavjud. Iltimos tekshirib qayta yuboring.")
        return

    ts_str, is_stale = await ensure_fresh_data_and_get_timestamp()

    try:
        await sync_to_async(TelegramBindingService().bind)(
            employee_id=user_id,
            telegram_id=message.from_user.id,
            username=message.from_user.username or "",
        )
    except DomainError as exc:
        await message.answer(str(exc))
        return
    except Exception as exc:
        logger.exception("Binding error: %s", exc)
        await message.answer("Bog'lanishda xatolik yuz berdi. Iltimos administratsiyaga murojaat qiling.")
        return

    try:
        dashboard = await sync_to_async(StatisticsService().employee_dashboard_for_employee)(user_id)
        text = employee_dashboard_text(dashboard) + format_footer(ts_str, is_stale)
        await message.answer(text)
    except DomainError as exc:
        await message.answer(str(exc) + format_footer(ts_str, is_stale))
    except Exception as exc:
        logger.exception("Dashboard error: %s", exc)
        await message.answer("Ma'lumotlarni yuklashda xatolik yuz berdi." + format_footer(ts_str, is_stale))


@router.message(Command("stats"))
async def employee_stats(message: Message) -> None:
    """Return bound employee's dashboard instantly (privacy protected: no ID arguments allowed)."""
    if message.from_user is None:
        return

    ts_str, is_stale = await ensure_fresh_data_and_get_timestamp()

    try:
        dashboard = await sync_to_async(StatisticsService().employee_dashboard_for_telegram)(message.from_user.id)
        text = employee_dashboard_text(dashboard) + format_footer(ts_str, is_stale)
        await message.answer(text)
    except DomainError as exc:
        await message.answer(str(exc))
    except Exception as exc:
        logger.exception("Employee stats error: %s", exc)
        await message.answer("Ma'lumotlarni yuklashda xatolik yuz berdi." + format_footer(ts_str, is_stale))


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
    except Exception as exc:
        logger.exception("Group stats error: %s", exc)
        await message.answer("Guruh ma'lumotlarini yuklashda xatolik yuz berdi." + format_footer(ts_str, is_stale))


@router.message(Command("tarix"))
async def employee_tarix(message: Message) -> None:
    """List available monthly periods for the bound employee (max 6)."""
    if message.from_user is None:
        return

    try:
        periods = await sync_to_async(StatisticsService().available_periods_for_telegram)(message.from_user.id)
    except DomainError as exc:
        await message.answer(str(exc))
        return
    except Exception as exc:
        logger.exception("Tarix error: %s", exc)
        await message.answer("Ma'lumotlarni yuklashda xatolik yuz berdi.")
        return

    if not periods:
        await message.answer("Sizda hali saqlangan oylik ma'lumotlari yo'q.")
        return

    builder = InlineKeyboardBuilder()
    for period_date, period_label in periods:
        builder.button(
            text=f"📅 {period_label}",
            callback_data=f"hist_{period_date.isoformat()}",
        )
    builder.adjust(2)

    await message.answer("📅 Kerakli oy hisobotini tanlang:", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("hist_"))
async def show_historical_stat(callback: CallbackQuery) -> None:
    """Render historical monthly stat for sender (strictly validated against sender's Telegram ID)."""
    if callback.from_user is None or callback.data is None:
        return

    try:
        iso_str = callback.data.removeprefix("hist_")
        period_date = date.fromisoformat(iso_str)
    except Exception:
        await callback.answer("Noto'g'ri so'rov.", show_alert=True)
        return

    ts_str, is_stale = await ensure_fresh_data_and_get_timestamp()

    try:
        dashboard, is_closed = await sync_to_async(
            StatisticsService().employee_historical_dashboard_for_telegram
        )(callback.from_user.id, period_date)

        footer = "\n\n🔒 <b>Oy yopilgan</b>" if is_closed else format_footer(ts_str, is_stale)
        text = employee_dashboard_text(dashboard) + footer
        if callback.message:
            await callback.message.answer(text)

        await callback.answer()
    except DomainError as exc:
        await callback.answer(str(exc), show_alert=True)
    except Exception as exc:
        logger.exception("Tarix callback error: %s", exc)
        await callback.answer("Ma'lumotni yuklashda xatolik yuz berdi.", show_alert=True)

