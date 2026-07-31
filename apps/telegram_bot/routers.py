"""Aiogram routers; handlers delegate sync & data access to application services."""

from __future__ import annotations

import asyncio
import logging
from datetime import date

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from asgiref.sync import sync_to_async
from django.utils import timezone

logger = logging.getLogger(__name__)

from apps.accounts.models import TelegramAccount
from apps.accounts.services.binding import TelegramBindingService
from apps.accounts.services.name_match import names_match
from apps.accounts.services.rate_limiter import (
    clear_failed_attempts,
    is_rate_limited,
    record_failed_attempt,
)
from apps.common.services.exceptions import DomainError
from apps.employees.models import Employee
from apps.employees.repositories.employee import EmployeeRepository
from apps.groups.models import SalesGroup
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


class RegistrationStates(StatesGroup):
    select_role = State()
    enter_id = State()
    enter_name = State()
    confirm = State()


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
async def start(message: Message, state: FSMContext) -> None:
    """Handle /start command.

    If already bound, inform user and list commands.
    If unbound, present role selection keyboard.
    """
    await state.clear()

    if message.from_user is None:
        return

    account = await sync_to_async(
        lambda: TelegramAccount.objects.select_related("employee").filter(telegram_id=message.from_user.id).first()
    )()

    if account:
        text = (
            f"Siz allaqachon <b>{account.employee.full_name}</b> (<code>{account.employee.employee_id}</code>) "
            f"sifatida ro'yxatdan o'tgansiz.\n\n"
            f"Mavjud buyruqlar:\n"
            f"📊 /stats — Shaxsiy ko'rsatkichlar\n"
            f"👥 /group_stats — Guruh ko'rsatkichlari (faqat ROP uchun)\n"
            f"📅 /tarix — Oylik hisobotlar tarixi"
        )
        await message.answer(text)
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="👔 R.O.P", callback_data="role_ROP")
    builder.button(text="👤 M.O.P", callback_data="role_MOP")
    builder.adjust(2)

    text = (
        "Xush kelibsiz! Botdan foydalanish uchun rolingizni tanlang:\n\n"
        "👔 <b>R.O.P</b> — Bo'lim boshlig'i\n"
        "👤 <b>M.O.P</b> — Sotuv operatori"
    )
    await state.set_state(RegistrationStates.select_role)
    await message.answer(text, reply_markup=builder.as_markup())


@router.callback_query(F.data.in_({"role_ROP", "role_MOP"}))
async def role_selected(callback: CallbackQuery, state: FSMContext) -> None:
    """Store chosen role and prompt for employee ID."""
    if callback.from_user is None or callback.data is None:
        return

    if await sync_to_async(is_rate_limited)(callback.from_user.id):
        await callback.answer("Siz juda ko'p Noto'g'ri urinish qildingiz. Administrator bilan bog'laning.", show_alert=True)
        await state.clear()
        return

    role = "ROP" if callback.data == "role_ROP" else "MOP"
    await state.update_data(role=role)
    await state.set_state(RegistrationStates.enter_id)

    text = "Employee ID raqamingizni yuboring. Masalan: <code>0191</code>"
    if callback.message:
        await callback.message.answer(text)
    await callback.answer()


@router.callback_query(F.data == "retry_registration")
async def retry_registration(callback: CallbackQuery, state: FSMContext) -> None:
    """Return user to step 2 (ID entry prompt)."""
    if callback.from_user is None:
        return

    if await sync_to_async(is_rate_limited)(callback.from_user.id):
        await callback.answer("Siz juda ko'p Noto'g'ri urinish qildingiz. Administrator bilan bog'laning.", show_alert=True)
        await state.clear()
        return

    await state.set_state(RegistrationStates.enter_id)
    text = "Employee ID raqamingizni yuboring. Masalan: <code>0191</code>"
    if callback.message:
        await callback.message.answer(text)
    await callback.answer()


@router.message(RegistrationStates.enter_id)
async def process_employee_id(message: Message, state: FSMContext) -> None:
    """Look up employee ID silently without displaying employee name."""
    if message.from_user is None or message.text is None:
        return

    if await sync_to_async(is_rate_limited)(message.from_user.id):
        await message.answer("Siz juda ko'p Noto'g'ri urinish qildingiz. Administrator bilan bog'laning.")
        await state.clear()
        return

    try:
        user_id = normalize_employee_id(message.text)
    except DomainError as exc:
        await message.answer(str(exc))
        return
    except Exception:
        await message.answer("ID formatida xatolik mavjud. Iltimos tekshirib qayta yuboring.")
        return

    try:
        employee = await sync_to_async(EmployeeRepository().get_active_by_employee_id)(user_id)
    except Employee.DoesNotExist:
        builder = InlineKeyboardBuilder()
        builder.button(text="🔄 Qayta urinish", callback_data="retry_registration")
        text = "Joriy oy ro'yxatida bunday IDga ega xodim topilmadi. Rahbaringiz bilan tekshiring."
        await message.answer(text, reply_markup=builder.as_markup())
        return

    existing_binding = await sync_to_async(
        lambda: TelegramAccount.objects.filter(employee=employee).first()
    )()
    if existing_binding and existing_binding.telegram_id != message.from_user.id:
        text = "Bu Employee ID allaqachon boshqa Telegram profiliga bog'langan. Administratsiyaga murojaat qiling."
        await message.answer(text)
        await state.clear()
        return

    await state.update_data(employee_id=user_id, sheet_name=employee.full_name)
    await state.set_state(RegistrationStates.enter_name)

    await message.answer("Iltimos, ism va familiyangizni kiriting:")


@router.message(RegistrationStates.enter_name)
async def process_name(message: Message, state: FSMContext) -> None:
    """Validate typed name against stored List2 record name."""
    if message.from_user is None or message.text is None:
        return

    telegram_id = message.from_user.id
    if await sync_to_async(is_rate_limited)(telegram_id):
        await message.answer("Siz juda ko'p Noto'g'ri urinish qildingiz. Administrator bilan bog'laning.")
        await state.clear()
        return

    data = await state.get_data()
    employee_id = data.get("employee_id", "")
    sheet_name = data.get("sheet_name", "")

    if not employee_id or not sheet_name:
        await message.answer("Sessiya eskirgan. Qayta boshlash uchun /start bosing.")
        await state.clear()
        return

    if not names_match(message.text, sheet_name):
        await sync_to_async(record_failed_attempt)(telegram_id, employee_id, message.text)
        builder = InlineKeyboardBuilder()
        builder.button(text="🔄 Qayta urinish", callback_data="retry_registration")
        text = "Kiritilgan ism-familiya ushbu ID ma'lumotlariga mos kelmadi."
        await message.answer(text, reply_markup=builder.as_markup())
        await state.set_state(RegistrationStates.enter_id)
        return

    await state.set_state(RegistrationStates.confirm)

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Ha, bu men", callback_data="confirm_yes")
    builder.button(text="❌ Yo'q", callback_data="confirm_no")
    builder.adjust(2)

    text = (
        f"🆔 ID: {employee_id}\n\n"
        "⚠️ Diqqat: bu ID sizga tegishli bo'lmasa, tasdiqlamang.\n"
        "Boshqa xodimning ma'lumotlariga kirish taqiqlanadi va\n"
        "barcha urinishlar administratorga ko'rinadi.\n\n"
        "Ma'lumotlar to'g'rimi?"
    )
    await message.answer(text, reply_markup=builder.as_markup())


@router.callback_query(F.data == "confirm_no")
async def confirm_no(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle rejection during name/ID confirmation."""
    if callback.from_user is None:
        return

    data = await state.get_data()
    employee_id = data.get("employee_id", "")
    telegram_id = callback.from_user.id

    await sync_to_async(record_failed_attempt)(telegram_id, employee_id, "[REJECTED_ON_CONFIRMATION]")
    await state.clear()

    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Qayta urinish", callback_data="retry_registration")

    text = (
        "Bu ma'lumot boshqa shaxsga tegishli. Boshqa xodimning ID raqamidan "
        "foydalanish taqiqlanadi va bu urinish saqlandi."
    )
    if callback.message:
        await callback.message.answer(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "confirm_yes")
async def confirm_yes(callback: CallbackQuery, state: FSMContext) -> None:
    """Bind employee account upon positive confirmation."""
    if callback.from_user is None:
        return

    telegram_id = callback.from_user.id
    if await sync_to_async(is_rate_limited)(telegram_id):
        await callback.answer("Siz juda ko'p Noto'g'ri urinish qildingiz. Administrator bilan bog'laning.", show_alert=True)
        await state.clear()
        return

    data = await state.get_data()
    employee_id = data.get("employee_id", "")
    role = data.get("role", "MOP")

    if not employee_id:
        await callback.answer("Sessiya eskirgan. /start bosing.", show_alert=True)
        await state.clear()
        return

    try:
        employee = await sync_to_async(TelegramBindingService().bind)(
            employee_id=employee_id,
            telegram_id=telegram_id,
            username=callback.from_user.username or "",
            role=role,
        )
    except DomainError as exc:
        if callback.message:
            await callback.message.answer(str(exc))
        await state.clear()
        await callback.answer()
        return
    except Exception as exc:
        logger.exception("Binding error: %s", exc)
        if callback.message:
            await callback.message.answer("Bog'lanishda xatolik yuz berdi. Iltimos administratsiyaga murojaat qiling.")
        await state.clear()
        await callback.answer()
        return

    await sync_to_async(clear_failed_attempts)(telegram_id)
    await state.clear()

    is_group_leader = False
    if role == "ROP":
        is_group_leader = await sync_to_async(
            lambda: SalesGroup.objects.filter(leader=employee, is_active=True).exists()
        )()

    if role == "ROP":
        if is_group_leader:
            text = (
                f"Muvaffaqiyatli bog'landi! Xush kelibsiz, <b>{employee.full_name}</b>!\n\n"
                "Mavjud buyruqlar:\n"
                "📊 /stats — Shaxsiy ko'rsatkichlar\n"
                "👥 /group_stats — Guruh ko'rsatkichlari\n"
                "📅 /tarix — Oylik hisobotlar tarixi"
            )
        else:
            text = (
                f"Muvaffaqiyatli bog'landi! Xush kelibsiz, <b>{employee.full_name}</b>!\n\n"
                "⚠️ Sizga biror guruh biriktirilmagan. Guruh rahbari huquqini olish uchun administratorga murojaat qiling.\n\n"
                "Mavjud buyruqlar:\n"
                "📊 /stats — Shaxsiy ko'rsatkichlar\n"
                "📅 /tarix — Oylik hisobotlar tarixi"
            )
    else:
        text = (
            f"Muvaffaqiyatli bog'landi! Xush kelibsiz, <b>{employee.full_name}</b>!\n\n"
            "Mavjud buyruqlar:\n"
            "📊 /stats — Shaxsiy ko'rsatkichlar\n"
            "📅 /tarix — Oylik hisobotlar tarixi"
        )

    if callback.message:
        await callback.message.answer(text)
    await callback.answer()


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
