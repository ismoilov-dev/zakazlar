"""Aiogram routers; handlers delegate sync & data access to application services."""

from __future__ import annotations

import asyncio
import inspect
import logging
import math
import typing
from datetime import date

from django.conf import settings
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
from apps.accounts.services.binding import (
    TelegramBindingService,
    is_rop_session_valid,
    require_rop_session,
)
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
    rop_employee_filter_menu_keyboard,
    rop_employee_list_card_text,
    rop_employee_list_keyboard,
    rop_group_sales_card_text,
    rop_group_stats_card_text,
    rop_menu_keyboard,
    rop_menu_text,
    rop_salary_card_text,
    order_list_keyboard,
    order_list_text,
    order_status_picker_keyboard,
    order_status_picker_text,
    xizmatlar_menu_keyboard,
    xizmatlar_menu_text,
)



router = Router(name="sales_bot")


STALE_THRESHOLD_SECONDS = 300
SYNC_TIMEOUT_SECONDS = getattr(settings, "SYNC_TIMEOUT_SECONDS", 1.5)

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
    last_successful = await sync_to_async(SyncLog.get_last_successful)(sync_type="payroll")

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

    last_attempt = await sync_to_async(lambda: SyncLog.objects.filter(sync_type="payroll").order_by("-started_at").first())()
    last_successful = await sync_to_async(SyncLog.get_last_successful)(sync_type="payroll")

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



async def _safe_delete_user_message(message: Message) -> None:
    """Safely delete user message without raising exceptions."""
    try:
        await message.delete()
    except Exception:
        pass


async def _send_or_edit_registration_prompt(
    target: Message | CallbackQuery,
    state: FSMContext,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Edit single registration bot message in place, or send a new one if editing fails or is unavailable."""
    is_callback = isinstance(target, CallbackQuery) or isinstance(getattr(target, "data", None), str)

    async def _safe_call(func: typing.Callable[..., typing.Any], *args: typing.Any, **kwargs: typing.Any) -> typing.Any:
        res = func(*args, **kwargs)
        if inspect.isawaitable(res):
            return await res
        return res

    if is_callback:
        cb = target
        cb_msg = getattr(cb, "message", None)
        if cb_msg:
            try:
                edited_msg = await _safe_call(cb_msg.edit_text, text, reply_markup=reply_markup)
                msg_id = getattr(edited_msg, "message_id", None) or getattr(cb_msg, "message_id", None)
                if isinstance(msg_id, int):
                    await state.update_data(bot_message_id=msg_id)
                return
            except TelegramBadRequest as exc:
                if "message is not modified" in str(exc).lower():
                    return
                logger.warning("Failed to edit callback message: %s", exc)
            except Exception as exc:
                logger.warning("Failed to edit callback message: %s", exc)

            if hasattr(cb_msg, "answer"):
                try:
                    new_msg = await _safe_call(cb_msg.answer, text, reply_markup=reply_markup)
                    msg_id = getattr(new_msg, "message_id", None)
                    if isinstance(msg_id, int):
                        await state.update_data(bot_message_id=msg_id)
                    return
                except Exception as inner_exc:
                    logger.warning("Failed to send fallback answer on callback: %s", inner_exc)
                    return

    # target is Message
    msg = target
    data = await state.get_data()
    bot_message_id = data.get("bot_message_id")

    if bot_message_id and getattr(msg, "bot", None) and getattr(msg, "chat", None):
        try:
            edited_msg = await _safe_call(
                msg.bot.edit_message_text,
                chat_id=msg.chat.id,
                message_id=bot_message_id,
                text=text,
                reply_markup=reply_markup,
            )
            msg_id = getattr(edited_msg, "message_id", None) or bot_message_id
            if isinstance(msg_id, int):
                await state.update_data(bot_message_id=msg_id)
            return
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return
            logger.warning("Failed to edit message_id %s in chat %s: %s", bot_message_id, getattr(msg.chat, "id", None), exc)
        except Exception as exc:
            logger.warning("Failed to edit message_id %s in chat %s: %s", bot_message_id, getattr(msg.chat, "id", None), exc)

    if hasattr(msg, "answer"):
        try:
            new_msg = await _safe_call(msg.answer, text, reply_markup=reply_markup)
            msg_id = getattr(new_msg, "message_id", None)
            if isinstance(msg_id, int):
                await state.update_data(bot_message_id=msg_id)
        except Exception as exc:
            logger.warning("Failed to send new registration message: %s", exc)


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    """Handle /start command.

    If already bound, inform user and list commands.
    If unbound, present role selection keyboard.
    """
    try:
        await state.clear()

        if message.from_user is None:
            return

        account = await sync_to_async(
            lambda: TelegramAccount.objects.select_related("employee").filter(telegram_id=message.from_user.id).first()
        )()

        if account:
            if not account.employee:
                logger.warning("Deleting orphaned TelegramAccount without employee for telegram_id=%s", message.from_user.id)
                await sync_to_async(account.delete)()
                account = None

        if account:
            try:
                await ensure_fresh_data_and_get_timestamp()
            except Exception as exc:
                logger.warning("ensure_fresh_data_and_get_timestamp failed in start: %s", exc)

            info_prefix = f"Siz allaqachon <b>{account.employee.full_name}</b> (<code>{account.employee.employee_id}</code>) sifatida ro'yxatdan o'tgansiz.\n\n"

            is_leader = await sync_to_async(is_group_leader)(account.employee)

            if account.role == "ROP" and is_leader:
                if not require_rop_session(account):
                    await state.update_data(employee_id=account.employee.employee_id)
                    await state.set_state(RegistrationStates.enter_password)
                    res = await message.answer("Sessiyangiz eskirgan. Qayta kirish uchun parolingizni kiriting:")
                    await state.update_data(bot_message_id=res.message_id)
                    return

                groups = await sync_to_async(
                    lambda: list(SalesGroup.objects.filter(leader=account.employee, is_active=True))
                )()
                group_code = groups[0].code if groups else (account.employee.group.code if account.employee.group else "A")
                text = info_prefix + rop_menu_text(account.employee.full_name, group_code, account.employee.employee_id)
                reply_markup = rop_menu_keyboard()
                await message.answer(text, reply_markup=reply_markup)
                return

            text = info_prefix + xizmatlar_menu_text()
            reply_markup = xizmatlar_menu_keyboard(show_rop_switch=is_leader)
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
        await _send_or_edit_registration_prompt(message, state, text, reply_markup=builder.as_markup())
    except Exception as exc:
        logger.exception("Error in /start handler: %s", exc)
        await message.answer("Xatolik yuz berdi. Iltimos, /start tugmasini qayta bosing.")


@router.callback_query(F.data.in_({"role_ROP", "role_MOP"}))
async def role_selected(callback: CallbackQuery, state: FSMContext) -> None:
    """Store chosen role and prompt for employee ID."""
    if callback.from_user is None or callback.data is None:
        return

    if await sync_to_async(is_rate_limited)(callback.from_user.id):
        await _send_or_edit_registration_prompt(
            callback, state, "Siz juda ko'p Noto'g'ri urinish qildingiz. Administrator bilan bog'laning."
        )
        await callback.answer("Siz juda ko'p Noto'g'ri urinish qildingiz. Administrator bilan bog'laning.", show_alert=True)
        await state.clear()
        return

    role = "ROP" if callback.data == "role_ROP" else "MOP"
    await state.update_data(role=role)
    await state.set_state(RegistrationStates.enter_id)

    text = "Employee ID raqamingizni yuboring. Masalan: <code>0191</code>"
    await _send_or_edit_registration_prompt(callback, state, text)
    await callback.answer()


@router.callback_query(F.data == "retry_registration")
async def retry_registration(callback: CallbackQuery, state: FSMContext) -> None:
    """Return user to step 2 (ID entry prompt)."""
    if callback.from_user is None:
        return

    if await sync_to_async(is_rate_limited)(callback.from_user.id):
        await _send_or_edit_registration_prompt(
            callback, state, "Siz juda ko'p Noto'g'ri urinish qildingiz. Administrator bilan bog'laning."
        )
        await callback.answer("Siz juda ko'p Noto'g'ri urinish qildingiz. Administrator bilan bog'laning.", show_alert=True)
        await state.clear()
        return

    await state.set_state(RegistrationStates.enter_id)
    text = "Employee ID raqamingizni yuboring. Masalan: <code>0191</code>"
    await _send_or_edit_registration_prompt(callback, state, text)
    await callback.answer()


@router.message(RegistrationStates.enter_id)
async def process_employee_id(message: Message, state: FSMContext) -> None:
    """Look up employee ID silently without displaying employee name."""
    if message.from_user is None or message.text is None:
        return

    await _safe_delete_user_message(message)

    if await sync_to_async(is_rate_limited)(message.from_user.id):
        await _send_or_edit_registration_prompt(
            message, state, "Siz juda ko'p Noto'g'ri urinish qildingiz. Administrator bilan bog'laning."
        )
        await state.clear()
        return

    retry_builder = InlineKeyboardBuilder()
    retry_builder.button(text="🔄 Qayta urinish", callback_data="retry_registration")

    try:
        user_id = normalize_employee_id(message.text)
    except DomainError as exc:
        await _send_or_edit_registration_prompt(message, state, str(exc), reply_markup=retry_builder.as_markup())
        return
    except Exception:
        await _send_or_edit_registration_prompt(
            message, state, "ID formatida xatolik mavjud. Iltimos tekshirib qayta yuboring.", reply_markup=retry_builder.as_markup()
        )
        return

    try:
        employee = await sync_to_async(EmployeeRepository().get_active_by_employee_id)(user_id)
    except Employee.DoesNotExist:
        text = "Joriy oy ro'yxatida bunday IDga ega xodim topilmadi. Rahbaringiz bilan tekshiring."
        await _send_or_edit_registration_prompt(message, state, text, reply_markup=retry_builder.as_markup())
        return

    existing_binding = await sync_to_async(
        lambda: TelegramAccount.objects.filter(employee=employee).first()
    )()
    if existing_binding and existing_binding.telegram_id != message.from_user.id:
        text = "Bu Employee ID allaqachon boshqa Telegram profiliga bog'langan. Administratsiyaga murojaat qiling."
        await _send_or_edit_registration_prompt(message, state, text, reply_markup=retry_builder.as_markup())
        await state.clear()
        return

    await state.update_data(employee_id=user_id, sheet_name=employee.full_name)
    await state.set_state(RegistrationStates.enter_name)
    await _send_or_edit_registration_prompt(message, state, "Iltimos, ism va familiyangizni kiriting:")


def is_group_leader(employee: Employee | None) -> bool:
    """Check if employee is an active group leader."""
    if not employee:
        return False
    return SalesGroup.objects.filter(leader=employee, is_active=True).exists()


def verify_rop_credentials(employee_id: str, raw_password: str) -> tuple[bool, str, Employee | None]:
    """Check if employee exists, is active leader, has credential, and password matches.

    Returns (success, error_code, employee).
    """
    try:
        employee = EmployeeRepository().get_active_by_employee_id(employee_id)
    except Employee.DoesNotExist:
        return False, "NOT_FOUND", None

    is_leader = SalesGroup.objects.filter(leader=employee, is_active=True).exists()
    if not is_leader:
        return False, "NOT_LEADER", employee

    if not hasattr(employee, "rop_credential") or employee.rop_credential is None:
        from apps.employees.models import RopCredential
        cred = RopCredential.objects.create(employee=employee)
        cred.set_password(raw_password)
        cred.save()
        return True, "SUCCESS", employee

    if not employee.rop_credential.check_password(raw_password):
        return False, "WRONG_PASSWORD", employee

    return True, "SUCCESS", employee


@router.message(RegistrationStates.enter_password)
async def process_password(message: Message, state: FSMContext) -> None:
    """Validate ROP password for registration (unbound) or re-authentication (bound)."""
    if message.from_user is None or message.text is None:
        return

    telegram_id = message.from_user.id
    await _safe_delete_user_message(message)

    if await sync_to_async(is_rate_limited)(telegram_id):
        await _send_or_edit_registration_prompt(
            message, state, "Siz juda ko'p Noto'g'ri urinish qildingiz. Administrator bilan bog'laning."
        )
        await state.clear()
        return

    retry_builder = InlineKeyboardBuilder()
    retry_builder.button(text="🔄 Qayta urinish", callback_data="retry_registration")

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
            await _send_or_edit_registration_prompt(
                message, state, "Sessiya eskirgan. Qayta boshlash uchun /start bosing.", reply_markup=retry_builder.as_markup()
            )
            await state.clear()
            return

    raw_password = message.text.strip()

    async def fail_login(reason: str, custom_msg: str | None = None):
        await sync_to_async(record_failed_attempt)(telegram_id, employee_id, "[FAILED_ROP_PASSWORD]")
        logger.warning("ROP login failed for telegram_id %s, employee_id %s: %s", telegram_id, employee_id, reason)
        await _send_or_edit_registration_prompt(
            message, state, custom_msg or "ID yoki parol noto'g'ri.", reply_markup=retry_builder.as_markup()
        )

    ok, error_code, employee = await sync_to_async(verify_rop_credentials)(employee_id, raw_password)
    if not ok or not employee:
        if error_code == "NO_CREDENTIAL":
            await fail_login("Leader has no password credential set", custom_msg="Siz uchun hali ROP paroli o'rnatilmagan. Administrator bilan bog'laning.")
        else:
            await fail_login(f"ROP password check failed: {error_code}")
        await state.clear()
        return

    session_hours = getattr(settings, "ROP_SESSION_HOURS", 12)
    success_text = f"🔑 ROP sessiyangiz tasdiqlandi! (Sessiya {session_hours} soat davomida faol bo'ladi)\n\n"

    existing_binding = await sync_to_async(
        lambda: TelegramAccount.objects.filter(telegram_id=telegram_id).first()
    )()

    if existing_binding and existing_binding.role == "ROP":
        # Re-authentication path: session expired, binding exists.
        existing_binding.rop_authenticated_at = timezone.now()
        await sync_to_async(existing_binding.save)(update_fields=["rop_authenticated_at"])
        await sync_to_async(clear_failed_attempts)(telegram_id)
        await state.clear()
        groups = await sync_to_async(
            lambda: list(SalesGroup.objects.filter(leader=employee, is_active=True))
        )()
        group_code = groups[0].code if groups else (employee.group.code if employee.group else "-")
        text = success_text + rop_menu_text(employee.full_name, group_code, employee.employee_id)
        reply_markup = rop_menu_keyboard()
        await _send_or_edit_registration_prompt(message, state, text, reply_markup=reply_markup)
        return

    # Registration path: no binding exists, create binding via bind()
    try:
        employee = await sync_to_async(TelegramBindingService().bind)(
            employee_id=employee_id,
            telegram_id=telegram_id,
            username=message.from_user.username if getattr(message.from_user, "username", None) and isinstance(message.from_user.username, str) else "",
            role="ROP",
        )
    except DomainError as exc:
        await _send_or_edit_registration_prompt(message, state, str(exc), reply_markup=retry_builder.as_markup())
        await state.clear()
        return
    except Exception as exc:
        logger.exception("ROP binding error: %s", exc)
        await _send_or_edit_registration_prompt(
            message, state, "Bog'lanishda xatolik yuz berdi. Administratsiyaga murojaat qiling.", reply_markup=retry_builder.as_markup()
        )
        await state.clear()
        return

    await sync_to_async(
        lambda: TelegramAccount.objects.filter(telegram_id=telegram_id).update(rop_authenticated_at=timezone.now())
    )()

    await sync_to_async(clear_failed_attempts)(telegram_id)
    await state.clear()

    groups = await sync_to_async(
        lambda: list(SalesGroup.objects.filter(leader=employee, is_active=True))
    )()
    group_code = groups[0].code if groups else (employee.group.code if employee.group else "-")
    welcome_prefix = f"Muvaffaqiyatli bog'landi! Xush kelibsiz, <b>{employee.full_name}</b>!\n\n"
    text = welcome_prefix + success_text + rop_menu_text(employee.full_name, group_code, employee.employee_id)
    reply_markup = rop_menu_keyboard()
    await _send_or_edit_registration_prompt(message, state, text, reply_markup=reply_markup)


@router.message(RegistrationStates.enter_name)
async def process_name(message: Message, state: FSMContext) -> None:
    """Validate typed name against stored List2 record name."""
    if message.from_user is None or message.text is None:
        return

    telegram_id = message.from_user.id
    await _safe_delete_user_message(message)

    if await sync_to_async(is_rate_limited)(telegram_id):
        await _send_or_edit_registration_prompt(
            message, state, "Siz juda ko'p Noto'g'ri urinish qildingiz. Administrator bilan bog'laning."
        )
        await state.clear()
        return

    retry_builder = InlineKeyboardBuilder()
    retry_builder.button(text="🔄 Qayta urinish", callback_data="retry_registration")

    data = await state.get_data()
    employee_id = data.get("employee_id", "")
    sheet_name = data.get("sheet_name", "")

    if not employee_id or not sheet_name:
        await _send_or_edit_registration_prompt(
            message, state, "Sessiya eskirgan. Qayta boshlash uchun /start bosing.", reply_markup=retry_builder.as_markup()
        )
        await state.clear()
        return

    if not names_match(message.text, sheet_name):
        await sync_to_async(record_failed_attempt)(telegram_id, employee_id, message.text)
        text = "Kiritilgan ism-familiya ushbu ID ma'lumotlariga mos kelmadi."
        await _send_or_edit_registration_prompt(message, state, text, reply_markup=retry_builder.as_markup())
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
    await _send_or_edit_registration_prompt(message, state, text, reply_markup=builder.as_markup())


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
    await _send_or_edit_registration_prompt(callback, state, text, reply_markup=builder.as_markup())
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

    retry_builder = InlineKeyboardBuilder()
    retry_builder.button(text="🔄 Qayta urinish", callback_data="retry_registration")

    if not employee_id:
        await callback.answer("Sessiya eskirgan. /start bosing.", show_alert=True)
        await state.clear()
        return

    if role == "ROP":
        await state.set_state(RegistrationStates.enter_password)
        await _send_or_edit_registration_prompt(callback, state, "Parolingizni kiriting:")
        await callback.answer()
        return

    try:
        employee = await sync_to_async(TelegramBindingService().bind)(
            employee_id=employee_id,
            telegram_id=telegram_id,
            username=callback.from_user.username or "",
            role=role,
        )
    except DomainError as exc:
        await _send_or_edit_registration_prompt(callback, state, str(exc), reply_markup=retry_builder.as_markup())
        await state.clear()
        await callback.answer()
        return
    except Exception as exc:
        logger.exception("Binding error: %s", exc)
        await _send_or_edit_registration_prompt(
            callback, state, "Bog'lanishda xatolik yuz berdi. Iltimos administratsiyaga murojaat qiling.", reply_markup=retry_builder.as_markup()
        )
        await state.clear()
        await callback.answer()
        return

    await sync_to_async(clear_failed_attempts)(telegram_id)
    await state.clear()

    welcome_prefix = f"Muvaffaqiyatli bog'landi! Xush kelibsiz, <b>{employee.full_name}</b>!\n\n"
    text = welcome_prefix + xizmatlar_menu_text()
    is_leader = await sync_to_async(is_group_leader)(employee)
    keyboard = xizmatlar_menu_keyboard(show_rop_switch=is_leader)

    await _send_or_edit_registration_prompt(callback, state, text, reply_markup=keyboard)
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

@router.message(Command("shaxsiy"))
async def shaxsiy_command(message: Message, state: FSMContext | None = None) -> None:
    """Open personal XIZMATLAR menu."""
    if message.from_user is None:
        return

    account = await sync_to_async(
        lambda: TelegramAccount.objects.select_related("employee").filter(telegram_id=message.from_user.id).first()
    )()
    if not account or not account.employee:
        await message.answer("Avval Employee ID orqali profilingizni bog'lang.")
        return

    await ensure_fresh_data_and_get_timestamp()
    is_leader = await sync_to_async(is_group_leader)(account.employee)
    text = xizmatlar_menu_text()
    reply_markup = xizmatlar_menu_keyboard(show_rop_switch=is_leader)
    await message.answer(text, reply_markup=reply_markup)


@router.message(Command("rop"))
async def rop_command(message: Message, state: FSMContext) -> None:
    """Open ROP panel menu (or prompt for password if expired)."""
    if message.from_user is None:
        return

    account = await sync_to_async(
        lambda: TelegramAccount.objects.select_related("employee").filter(telegram_id=message.from_user.id).first()
    )()
    if not account or not account.employee:
        await message.answer("Avval Employee ID orqali profilingizni bog'lang.")
        return

    is_leader = await sync_to_async(is_group_leader)(account.employee)
    if not is_leader:
        await message.answer("Siz guruh rahbari emassiz.")
        return

    if require_rop_session(account):
        groups = await sync_to_async(
            lambda: list(SalesGroup.objects.filter(leader=account.employee, is_active=True))
        )()
        group = groups[0]
        text = rop_menu_text(account.employee.full_name, group.code, account.employee.employee_id)
        reply_markup = rop_menu_keyboard()
        await message.answer(text, reply_markup=reply_markup)
        return

    await state.update_data(employee_id=account.employee.employee_id)
    await state.set_state(RegistrationStates.enter_password)
    await message.answer("Parolingizni kiriting:")


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

    is_leader = await sync_to_async(is_group_leader)(account.employee)

    if account.role == "ROP" and is_leader:
        if not require_rop_session(account):
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
    reply_markup = xizmatlar_menu_keyboard(show_rop_switch=is_leader)
    await message.answer(text, reply_markup=reply_markup)


@router.callback_query(F.data == "xm_switch_rop")
async def handle_switch_rop(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle click on [ 👔 ROP PANELI ] switch button from personal menu."""
    if callback.from_user is None:
        return

    telegram_id = callback.from_user.id
    account = await sync_to_async(
        lambda: TelegramAccount.objects.select_related("employee").filter(telegram_id=telegram_id).first()
    )()
    if not account or not account.employee:
        await callback.answer("Avval profilingizni bog'lang.", show_alert=True)
        return

    is_leader = await sync_to_async(is_group_leader)(account.employee)
    if not is_leader:
        await callback.answer("Siz guruh rahbari emassiz.", show_alert=True)
        return

    if require_rop_session(account):
        groups = await sync_to_async(
            lambda: list(SalesGroup.objects.filter(leader=account.employee, is_active=True))
        )()
        group_code = groups[0].code if groups else (account.employee.group.code if account.employee.group else "-")
        text = rop_menu_text(account.employee.full_name, group_code, account.employee.employee_id)
        reply_markup = rop_menu_keyboard()
        if callback.message:
            await callback.message.edit_text(text, reply_markup=reply_markup)
        await callback.answer()
        return

    await state.update_data(employee_id=account.employee.employee_id)
    await state.set_state(RegistrationStates.enter_password)
    if callback.message:
        await callback.message.answer("🔑 ROP paneliga kirish uchun parolingizni kiriting:")
    await callback.answer()


@router.callback_query(F.data.startswith("rop_"))
async def handle_rop_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle ROP menu & card callbacks with DB-enforced leadership and session validation."""
    if callback.from_user is None or callback.data is None:
        return

    telegram_id = callback.from_user.id
    account = await sync_to_async(
        lambda: TelegramAccount.objects.select_related("employee").filter(telegram_id=telegram_id).first()
    )()
    if not account or not account.employee:
        await callback.answer("Avval profilingizni bog'lang.", show_alert=True)
        return

    is_leader = await sync_to_async(is_group_leader)(account.employee)
    if not is_leader:
        await callback.answer("Siz faol guruh rahbari emassiz.", show_alert=True)
        return

    if not require_rop_session(account):
        await callback.answer("Sessiyangiz eskirgan. Parolingizni qayta kiriting.", show_alert=True)
        if callback.message:
            await state.update_data(employee_id=account.employee.employee_id)
            await state.set_state(RegistrationStates.enter_password)
            await callback.message.answer("Sessiyangiz eskirgan. Qayta kirish uchun parolingizni kiriting:")
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
    elif len(groups) > 1 and not callback.data.startswith("rop_card:") and not callback.data.startswith("rop_emp_filter:"):
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
    elif action == "rop_card:mop_salary":
        text = (
            card_text(
                "earned_salary",
                account.employee.full_name,
                group.code,
                account.employee.summary_data,
            )
            + footer
        )
        keyboard = rop_card_keyboard()
    elif action == "rop_card:mop_xizmatlar":
        text = xizmatlar_menu_text()
        keyboard = xizmatlar_menu_keyboard(show_rop_switch=True, src="rop")
    elif action == "rop_card:employee_list":
        text = "<b>Xodimlarni filtrlash:</b>"
        keyboard = rop_employee_filter_menu_keyboard()
    elif action.startswith("rop_emp_filter:"):
        parts = action.split(":")
        filter_key = parts[1] if len(parts) > 1 else "all"
        if filter_key not in ("has_sales", "no_sales", "all"):
            filter_key = "all"
        try:
            page = int(parts[2]) if len(parts) > 2 else 1
        except ValueError:
            page = 1
        if page < 1:
            page = 1

        employees = await sync_to_async(RopService().get_group_employee_list)(group, filter_key)
        total_count = len(employees)
        page_size = 20
        total_pages = max(1, math.ceil(total_count / page_size))
        if page > total_pages:
            page = total_pages

        text = (
            rop_employee_list_card_text(group.code, filter_key, employees, page, total_count, page_size)
            + footer
        )
        keyboard = rop_employee_list_keyboard(filter_key, page, total_pages)
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
    is_leader_with_cred = await sync_to_async(
        lambda: SalesGroup.objects.filter(leader=account.employee, is_active=True).exists()
        and hasattr(account.employee, "rop_credential")
        and account.employee.rop_credential is not None
    )()
    text = xizmatlar_menu_text()
    reply_markup = xizmatlar_menu_keyboard(show_rop_switch=is_leader_with_cred)
    await message.answer(text, reply_markup=reply_markup)



@router.callback_query(F.data.startswith("xm_"))
async def handle_xizmatlar_callback(callback: CallbackQuery, state: FSMContext | None = None) -> None:
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
    src: str | None = None
    for part in parts:
        if part.startswith("src="):
            src = part.split("=")[1]
            break

    period_iso: str | None = None
    period_date: date | None = None
    is_closed = False
    period_label: str | None = None

    for part in parts[1:]:
        if not part.startswith("src="):
            try:
                date.fromisoformat(part)
                period_iso = part
                break
            except Exception:
                pass

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
            summary_data = None
            is_closed = False
            period_label = format_uzbek_period(period_date)
        else:
            summary_data = stat.summary_data
            is_closed = stat.is_closed
            period_label = format_uzbek_period(period_date)

        fallback_salary = None

    ts_str, is_stale = await ensure_fresh_data_and_get_timestamp()
    footer = "\n\n🔒 <b>Oy yopilgan</b>" if is_closed else format_footer(ts_str, is_stale)

    text = ""
    reply_markup = None

    is_leader = await sync_to_async(is_group_leader)(employee)

    if action == "xm_menu" and not period_iso and src == "rop":
        if is_leader:
            if require_rop_session(account):
                groups = await sync_to_async(
                    lambda: list(SalesGroup.objects.filter(leader=employee, is_active=True))
                )()
                group_code = groups[0].code if groups else (employee.group.code if employee.group else "-")
                text = rop_menu_text(employee.full_name, group_code, employee.employee_id)
                reply_markup = rop_menu_keyboard()
                if callback.message:
                    try:
                        await callback.message.edit_text(text, reply_markup=reply_markup)
                    except TelegramBadRequest as exc:
                        if "message is not modified" not in str(exc).lower():
                            logger.warning("Failed to edit ROP menu: %s", exc)
                await callback.answer()
                return

            if state is not None:
                await state.update_data(employee_id=employee.employee_id)
                await state.set_state(RegistrationStates.enter_password)
            if callback.message:
                await callback.message.answer("Sessiyangiz eskirgan. Qayta kirish uchun parolingizni kiriting:")
            await callback.answer()
            return

    if action in ("xm_menu", "xm_period", "xm_back"):
        text = xizmatlar_menu_text(period_label)
        if period_iso and (summary_data is None or not summary_data):
            text += "\n\nBu oy uchun ma'lumot saqlanmagan."
        reply_markup = xizmatlar_menu_keyboard(period_iso=period_iso, show_rop_switch=is_leader, src=src)

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
        reply_markup = card_keyboard(period_iso, src=src, card_type=card_type)

    elif action == "xm_orders":
        from apps.imports.models import SpreadsheetPeriod
        active_sp = await sync_to_async(lambda: SpreadsheetPeriod.objects.filter(is_active=True).first())()
        p_date = period_date or (active_sp.period if active_sp else timezone.localtime().date())

        counts = await sync_to_async(get_order_status_counts)(employee.id, p_date.year, p_date.month)
        text = order_status_picker_text()
        reply_markup = order_status_picker_keyboard(counts=counts, period_iso=period_iso, src=src)

    elif action == "xm_months":
        try:
            periods = await sync_to_async(StatisticsService().available_periods_for_telegram)(telegram_id)
        except Exception:
            periods = []

        if not periods:
            text = "Sizda hali saqlangan oylik ma'lumotlari yo'q."
            builder = InlineKeyboardBuilder()
            src_suffix = f":src={src}" if src else ""
            builder.button(text="⬅️ Xizmatlarga qaytish", callback_data=f"xm_menu{src_suffix}")
            reply_markup = builder.as_markup()
        else:
            text = "<b>📅 Kerakli oy hisobotini tanlang:</b>"
            reply_markup = period_selector_keyboard(periods, src=src)

    if text and callback.message:
        try:
            await callback.message.edit_text(text, reply_markup=reply_markup)
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                pass
            else:
                logger.warning("Callback edit error: %s", exc)

    await callback.answer()


def get_order_status_counts(employee_id: int, year: int, month: int) -> dict[str, int]:
    from django.db.models import Count
    from apps.sales.models import Sale
    res = Sale.objects.filter(employee_id=employee_id, ordered_at__year=year, ordered_at__month=month).values("status").annotate(cnt=Count("id"))
    return {r["status"]: r["cnt"] for r in res}


def get_paginated_orders(
    employee_id: int, status: str, year: int, month: int, page: int
) -> tuple[list[Any], int, int]:
    from apps.sales.models import Sale
    qs = Sale.objects.filter(
        employee_id=employee_id,
        status=status,
        ordered_at__year=year,
        ordered_at__month=month,
    ).select_related("employee").order_by("-ordered_at")

    total_count = qs.count()
    if total_count == 0:
        return [], 0, 1

    total_pages = math.ceil(total_count / 5)
    if page > total_pages:
        page = total_pages
    if page < 1:
        page = 1

    offset = (page - 1) * 5
    orders = list(qs[offset : offset + 5])
    return orders, total_count, total_pages


@router.callback_query(F.data.startswith("ord_status:") | F.data.startswith("ord_list:"))
async def handle_order_list_callbacks(callback: CallbackQuery) -> None:
    """Handle status selection and pagination for operator's own orders list."""
    if callback.from_user is None or callback.data is None:
        return

    telegram_id = callback.from_user.id
    account = await sync_to_async(
        lambda: TelegramAccount.objects.select_related("employee").filter(telegram_id=telegram_id).first()
    )()
    if not account or not account.employee:
        await callback.answer("Avval Employee ID orqali profilingizni bog'lang.", show_alert=True)
        return

    employee = account.employee
    parts = callback.data.split(":")
    status = parts[1] if len(parts) > 1 else "successful"
    page = 1
    period_iso = None
    src = None

    for p in parts[2:]:
        if p.startswith("p="):
            try:
                page = int(p.split("=")[1])
            except ValueError:
                page = 1
        elif p.startswith("src="):
            src = p.split("=")[1]
        elif "-" in p and len(p) == 7:
            period_iso = p

    from apps.imports.models import SpreadsheetPeriod
    active_sp = await sync_to_async(lambda: SpreadsheetPeriod.objects.filter(is_active=True).first())()

    if period_iso:
        try:
            p_date = date.fromisoformat(period_iso)
        except Exception:
            p_date = active_sp.period if active_sp else timezone.localtime().date()
    else:
        p_date = active_sp.period if active_sp else timezone.localtime().date()

    period_label = format_uzbek_period(p_date)

    orders, total_count, total_pages = await sync_to_async(get_paginated_orders)(
        employee_id=employee.id,
        status=status,
        year=p_date.year,
        month=p_date.month,
        page=page,
    )

    text = order_list_text(
        orders=orders,
        status=status,
        total_count=total_count,
        page=page,
        total_pages=total_pages,
        period_label=period_label,
    )
    reply_markup = order_list_keyboard(
        status=status,
        page=page,
        total_pages=total_pages,
        period_iso=period_iso,
        src=src,
    )

    if text and callback.message:
        try:
            await callback.message.edit_text(text, reply_markup=reply_markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                logger.warning("Order list callback edit error: %s", exc)

    await callback.answer()

