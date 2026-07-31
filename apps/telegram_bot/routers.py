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

from aiogram.exceptions import TelegramBadRequest
from apps.accounts.models import TelegramAccount
from apps.accounts.services.binding import TelegramBindingService, is_rop_session_valid
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
from apps.groups.services.rop_service import RopService
from apps.imports.dto import normalize_employee_id
from apps.imports.models import SyncLog, SyncStatus
from apps.imports.services.sheets_sync import SheetsSyncService
from apps.statistics.services.statistics import StatisticsService
from apps.telegram_bot.services.formatting import (
    card_keyboard,
    card_text,
    format_uzbek_period,
    group_dashboard_text,
    period_selector_keyboard,
    rop_card_keyboard,
    rop_group_sales_card_text,
    rop_group_stats_card_text,
    rop_menu_keyboard,
    rop_menu_text,
    rop_salary_card_text,
    xizmatlar_menu_keyboard,
    xizmatlar_menu_text,
)



router = Router(name="sales_bot")


STALE_THRESHOLD_SECONDS = 300
SYNC_TIMEOUT_SECONDS = 3.0

_background_tasks: set[asyncio.Task] = set()
_current_sync_task: asyncio.Task | None = None
_sync_lock = asyncio.Lock()


class RegistrationStates(StatesGroup):
    select_role = State()
    enter_id = State()
    enter_password = State()
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
        except TimeoutError:
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
        await ensure_fresh_data_and_get_timestamp()
        info_prefix = f"Siz allaqachon <b>{account.employee.full_name}</b> (<code>{account.employee.employee_id}</code>) sifatida ro'yxatdan o'tgansiz.\n\n"

        if account.role == "ROP":
            is_leader = await sync_to_async(
                lambda: SalesGroup.objects.filter(leader=account.employee, is_active=True).exists()
            )()
            if is_leader:
                if not is_rop_session_valid(account):
                    await state.update_data(employee_id=account.employee.employee_id)
                    await state.set_state(RegistrationStates.enter_password)
                    await message.answer("Sessiyangiz eskirgan. Qayta kirish uchun parolingizni kiriting:")
                    return

                groups = await sync_to_async(
                    lambda: list(SalesGroup.objects.filter(leader=account.employee, is_active=True))
                )()
                group = groups[0]
                text = info_prefix + rop_menu_text(account.employee.full_name, group.code, account.employee.employee_id)
                reply_markup = rop_menu_keyboard()
                await message.answer(text, reply_markup=reply_markup)
                return

        text = info_prefix + xizmatlar_menu_text()
        reply_markup = xizmatlar_menu_keyboard()
        await message.answer(text, reply_markup=reply_markup)
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

    data = await state.get_data()
    role = data.get("role", "MOP")
    await state.update_data(employee_id=user_id, sheet_name=employee.full_name)


    if role == "ROP":
        await state.set_state(RegistrationStates.enter_password)
        await message.answer("Parolingizni kiriting:")
    else:
        await state.set_state(RegistrationStates.enter_name)
        await message.answer("Iltimos, ism va familiyangizni kiriting:")


@router.message(RegistrationStates.enter_password)
async def process_password(message: Message, state: FSMContext) -> None:
    """Validate ROP password, deleting the plaintext password message immediately."""
    if message.from_user is None or message.text is None:
        return

    telegram_id = message.from_user.id

    try:
        await message.delete()
    except Exception:
        pass

    if await sync_to_async(is_rate_limited)(telegram_id):
        await message.answer("Siz juda ko'p Noto'g'ri urinish qildingiz. Administrator bilan bog'laning.")
        await state.clear()
        return

    data = await state.get_data()
    employee_id = data.get("employee_id", "")
    if not employee_id:
        account = await sync_to_async(
            lambda: TelegramAccount.objects.select_related("employee").filter(telegram_id=telegram_id).first()
        )()
        if account and account.employee:
            employee_id = account.employee.employee_id
            await state.update_data(employee_id=employee_id)
        else:
            await message.answer("Sessiya eskirgan. Qayta boshlash uchun /start bosing.")
            await state.clear()
            return

    raw_password = message.text.strip()

    async def fail_login(reason: str):
        await sync_to_async(record_failed_attempt)(telegram_id, employee_id, "[FAILED_ROP_PASSWORD]")
        logger.warning("ROP login failed for telegram_id %s, employee_id %s: %s", telegram_id, employee_id, reason)
        await message.answer("ID yoki parol noto'g'ri.")

    try:
        employee = await sync_to_async(EmployeeRepository().get_active_by_employee_id)(employee_id)
    except Employee.DoesNotExist:
        await fail_login("Employee ID not in roster")
        return

    is_leader = await sync_to_async(
        lambda: SalesGroup.objects.filter(leader=employee, is_active=True).exists()
    )()
    if not is_leader:
        await fail_login("Employee is not a group leader")
        return

    has_credential = await sync_to_async(
        lambda: hasattr(employee, "rop_credential") and employee.rop_credential is not None
    )()
    if not has_credential:
        await fail_login("Leader has no password credential set")
        return

    password_matches = await sync_to_async(
        lambda: employee.rop_credential.check_password(raw_password)
    )()
    if not password_matches:
        await fail_login("Password mismatch")
        return

    existing_binding = await sync_to_async(
        lambda: TelegramAccount.objects.filter(telegram_id=telegram_id).first()
    )()
    if existing_binding and existing_binding.role == "ROP":
        existing_binding.rop_authenticated_at = timezone.now()
        await sync_to_async(existing_binding.save)(update_fields=["rop_authenticated_at"])
        await sync_to_async(clear_failed_attempts)(telegram_id)
        await state.clear()
        await message.answer("ROP sessiyangiz muvaffaqiyatli yangilandi! (12 soat amal qiladi)")
        return

    await state.update_data(sheet_name=employee.full_name)
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

    if role == "ROP":
        await sync_to_async(
            lambda: TelegramAccount.objects.filter(telegram_id=telegram_id).update(rop_authenticated_at=timezone.now())
        )()

    await sync_to_async(clear_failed_attempts)(telegram_id)
    await state.clear()

    if role == "ROP":
        welcome_prefix = (
            f"Muvaffaqiyatli bog'landi! Xush kelibsiz, <b>{employee.full_name}</b>!\n\n"
            "🔑 ROP sessiyangiz 12 soat davomida amal qiladi.\n\n"
        )
    else:
        welcome_prefix = f"Muvaffaqiyatli bog'landi! Xush kelibsiz, <b>{employee.full_name}</b>!\n\n"

    if callback.message:
        await callback.message.answer(welcome_prefix + xizmatlar_menu_text(), reply_markup=xizmatlar_menu_keyboard())
    await callback.answer()




@router.message(Command("chiqish"))
async def rop_logout(message: Message, state: FSMContext) -> None:
    """Log out ROP session immediately."""
    await state.clear()
    if message.from_user is None:
        return

    account = await sync_to_async(
        lambda: TelegramAccount.objects.filter(telegram_id=message.from_user.id).first()
    )()
    if account:
        account.rop_authenticated_at = None
        await sync_to_async(account.save)(update_fields=["rop_authenticated_at"])

    await message.answer("Tizimdan chiqdingiz. Qayta kirish uchun parolingizni kiriting.")


@router.message(Command("stats"))
async def employee_stats(message: Message, state: FSMContext | None = None) -> None:

    """Return bound employee's menu (ROP or MOP)."""
    if message.from_user is None:
        return

    account = await sync_to_async(
        lambda: TelegramAccount.objects.select_related("employee").filter(telegram_id=message.from_user.id).first()
    )()
    if not account or not account.employee:
        await message.answer("Avval Employee ID orqali profilingizni bog'lang.")
        return

    await ensure_fresh_data_and_get_timestamp()

    if account.role == "ROP":
        is_leader = await sync_to_async(
            lambda: SalesGroup.objects.filter(leader=account.employee, is_active=True).exists()
        )()
        if is_leader:
            if not is_rop_session_valid(account):
                if state is not None:
                    await state.update_data(employee_id=account.employee.employee_id)
                    await state.set_state(RegistrationStates.enter_password)
                await message.answer("Sessiyangiz eskirgan. Qayta kirish uchun parolingizni kiriting:")
                return


            groups = await sync_to_async(
                lambda: list(SalesGroup.objects.filter(leader=account.employee, is_active=True))
            )()
            group = groups[0]
            text = rop_menu_text(account.employee.full_name, group.code, account.employee.employee_id)
            reply_markup = rop_menu_keyboard()
            await message.answer(text, reply_markup=reply_markup)
            return

    text = xizmatlar_menu_text()
    reply_markup = xizmatlar_menu_keyboard()
    await message.answer(text, reply_markup=reply_markup)


@router.callback_query(F.data.startswith("rop_"))
async def handle_rop_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle ROP menu & card callbacks with DB-enforced leadership and session validation."""
    if callback.from_user is None or callback.data is None:
        return

    telegram_id = callback.from_user.id
    account = await sync_to_async(
        lambda: TelegramAccount.objects.select_related("employee").filter(telegram_id=telegram_id).first()
    )()
    if not account or not account.employee or account.role != "ROP":
        await callback.answer("Avval ROP profili orqali tizimga kiring.", show_alert=True)
        return

    is_leader = await sync_to_async(
        lambda: SalesGroup.objects.filter(leader=account.employee, is_active=True).exists()
    )()
    if not is_leader:
        await callback.answer("Siz faol guruh rahbari emassiz.", show_alert=True)
        return

    if not is_rop_session_valid(account):
        await callback.answer("Sessiyangiz eskirgan. Parolingizni qayta kiriting.", show_alert=True)
        if callback.message:
            await state.update_data(employee_id=account.employee.employee_id)
            await state.set_state(RegistrationStates.enter_password)
            await callback.message.answer("Parolingizni kiriting:")
        return

    groups = await sync_to_async(
        lambda: list(SalesGroup.objects.filter(leader=account.employee, is_active=True).order_by("code"))
    )()

    if len(groups) > 1 and callback.data.startswith("rop_pick_group:"):
        group_id_str = callback.data.split(":", 1)[1]
        selected = next((g for g in groups if str(g.id) == group_id_str), None)
        if selected:
            await state.update_data(selected_group_id=selected.id)
            group = selected
        else:
            await callback.answer("Ruxsat berilmagan guruh.", show_alert=True)
            return
    elif len(groups) > 1 and not callback.data.startswith("rop_card:"):
        data = await state.get_data()
        selected_id = data.get("selected_group_id")
        selected = next((g for g in groups if g.id == selected_id), None)
        if selected:
            group = selected
        else:
            builder = InlineKeyboardBuilder()
            for g in groups:
                builder.button(text=f"🏢 {g.name} ({g.code})", callback_data=f"rop_pick_group:{g.id}")
            builder.adjust(1)
            if callback.message:
                await callback.message.edit_text("<b>Guruhni tanlang:</b>", reply_markup=builder.as_markup())
            await callback.answer()
            return
    else:
        data = await state.get_data()
        selected_id = data.get("selected_group_id")
        selected = next((g for g in groups if g.id == selected_id), None)
        group = selected if selected else groups[0]


    action = callback.data
    ts_str, is_stale = await ensure_fresh_data_and_get_timestamp()
    footer = format_footer(ts_str, is_stale)

    if action == "rop_menu":
        text = rop_menu_text(account.employee.full_name, group.code, account.employee.employee_id)
        keyboard = rop_menu_keyboard()
    elif action == "rop_card:group_sales":
        totals = await sync_to_async(RopService().get_group_sales_totals)(group)
        text = rop_group_sales_card_text(group.code, totals) + footer
        keyboard = rop_card_keyboard()
    elif action == "rop_card:group_stats":
        stats = await sync_to_async(RopService().get_group_stats)(group)
        text = rop_group_stats_card_text(group.code, stats) + footer
        keyboard = rop_card_keyboard()
    elif action == "rop_card:rop_salary":
        salary_info = await sync_to_async(RopService().calculate_rop_salary)(group)
        text = rop_salary_card_text(group.code, salary_info) + footer
        keyboard = rop_card_keyboard()
    elif action == "rop_card:mop_xizmatlar":

        text = xizmatlar_menu_text()
        keyboard = xizmatlar_menu_keyboard()
    else:
        text = rop_menu_text(account.employee.full_name, group.code, account.employee.employee_id)
        keyboard = rop_menu_keyboard()

    if callback.message:
        try:
            await callback.message.edit_text(text, reply_markup=keyboard)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                logger.warning("Failed to edit ROP message: %s", exc)

    await callback.answer()



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
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Xizmatlarga qaytish", callback_data="xm_menu")
        await message.answer("Sizda hali saqlangan oylik ma'lumotlari yo'q.", reply_markup=builder.as_markup())
        return

    reply_markup = period_selector_keyboard(periods)
    await message.answer("<b>📅 Kerakli oy hisobotini tanlang:</b>", reply_markup=reply_markup)


@router.message(F.text & ~F.text.startswith("/"))
async def handle_bare_text_message(message: Message, state: FSMContext) -> None:
    """Handle bare text or ID messages for bound users by sending XIZMATLAR menu."""
    current_state = await state.get_state()
    if current_state is not None:
        return

    if message.from_user is None:
        return

    account = await sync_to_async(
        lambda: TelegramAccount.objects.select_related("employee").filter(telegram_id=message.from_user.id).first()
    )()
    if not account or not account.employee:
        await message.answer("Avval Employee ID orqali profilingizni bog'lang.")
        return

    await ensure_fresh_data_and_get_timestamp()
    text = xizmatlar_menu_text()
    reply_markup = xizmatlar_menu_keyboard()
    await message.answer(text, reply_markup=reply_markup)


@router.callback_query(F.data.startswith("xm_"))
async def handle_xizmatlar_callback(callback: CallbackQuery) -> None:
    """Unified handler for XIZMATLAR menu, focused cards, and historical period navigation."""
    if callback.from_user is None or callback.data is None:
        return

    telegram_id = callback.from_user.id
    account = await sync_to_async(
        lambda: TelegramAccount.objects.select_related("employee", "employee__group").filter(telegram_id=telegram_id).first()
    )()
    if not account or not account.employee:
        await callback.answer("Avval Employee ID orqali profilingizni bog'lang.", show_alert=True)
        return

    employee = account.employee
    parts = callback.data.split(":")
    action = parts[0]

    period_iso: str | None = None
    period_date: date | None = None
    is_closed = False
    period_label: str | None = None

    if action == "xm_period" and len(parts) > 1:
        period_iso = parts[1]
    elif action in ("xm_menu", "xm_card") and len(parts) > 2:
        period_iso = parts[2]

    summary_data = employee.summary_data or {}
    fallback_salary = employee.monthly_salary

    if period_iso:
        try:
            period_date = date.fromisoformat(period_iso)
        except Exception:
            await callback.answer("Noto'g'ri oy formati.", show_alert=True)
            return

        from apps.employees.models import EmployeeMonthlyStat
        stat = await sync_to_async(
            lambda: EmployeeMonthlyStat.objects.filter(employee=employee, period=period_date).first()
        )()
        if not stat:
            await callback.answer("Ushbu oy uchun ma'lumot topilmadi.", show_alert=True)
            return

        summary_data = stat.summary_data or {}
        is_closed = stat.is_closed
        period_label = format_uzbek_period(period_date)

    ts_str, is_stale = await ensure_fresh_data_and_get_timestamp()
    footer = "\n\n🔒 <b>Oy yopilgan</b>" if is_closed else format_footer(ts_str, is_stale)

    text = ""
    reply_markup = None

    if action in ("xm_menu", "xm_period"):
        text = xizmatlar_menu_text(period_label)
        reply_markup = xizmatlar_menu_keyboard(period_iso)

    elif action == "xm_card":
        card_type = parts[1]
        group_code = employee.group.code if employee.group else "A"
        body = card_text(
            card_type=card_type,
            full_name=employee.full_name,
            group_code=group_code,
            summary_data=summary_data,
            period_label=period_label,
            fallback_salary=fallback_salary,
        )
        text = body + footer
        reply_markup = card_keyboard(period_iso)

    elif action == "xm_months":
        try:
            periods = await sync_to_async(StatisticsService().available_periods_for_telegram)(telegram_id)
        except Exception:
            periods = []

        if not periods:
            text = "Sizda hali saqlangan oylik ma'lumotlari yo'q."
            builder = InlineKeyboardBuilder()
            builder.button(text="⬅️ Xizmatlarga qaytish", callback_data="xm_menu")
            reply_markup = builder.as_markup()
        else:
            text = "<b>📅 Kerakli oy hisobotini tanlang:</b>"
            reply_markup = period_selector_keyboard(periods)

    if text and callback.message:
        try:
            await callback.message.edit_text(text, reply_markup=reply_markup)
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                pass
            else:
                logger.warning("Callback edit error: %s", exc)

    await callback.answer()

