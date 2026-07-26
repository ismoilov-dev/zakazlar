"""Aiogram routers; handlers delegate all data access to application services."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from asgiref.sync import sync_to_async

from apps.accounts.services.binding import TelegramBindingService
from apps.common.services.exceptions import DomainError
from apps.statistics.services.statistics import StatisticsService
from apps.telegram_bot.services.formatting import employee_dashboard_text, group_dashboard_text

router = Router(name="sales_bot")


@router.message(CommandStart())
async def start(message: Message) -> None:
    """Explain the Employee ID binding flow."""
    await message.answer("Xush kelibsiz. Employee ID raqamingizni yuboring. Masalan: <code>0191</code>")


@router.message(F.text.regexp(r"^\d{4,32}$"))
async def bind_and_show_employee_stats(message: Message) -> None:
    """Bind the sender Telegram identity and return full employee calculations."""
    if message.from_user is None or message.text is None:
        return
    user_id = message.text.strip().zfill(4)
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
        await message.answer(employee_dashboard_text(dashboard))
    except DomainError as exc:
        await message.answer(str(exc))


@router.message(Command("stats"))
async def employee_stats(message: Message) -> None:
    """Return requested or bound employee's dashboard."""
    if message.from_user is None:
        return
    parts = (message.text or "").split()
    if len(parts) > 1 and parts[1].isdigit():
        user_id = parts[1].strip().zfill(4)
        try:
            dashboard = await sync_to_async(StatisticsService().employee_dashboard_for_employee)(user_id)
            await message.answer(employee_dashboard_text(dashboard))
            return
        except DomainError as exc:
            await message.answer(str(exc))
            return

    try:
        dashboard = await sync_to_async(StatisticsService().employee_dashboard_for_telegram)(message.from_user.id)
        await message.answer(employee_dashboard_text(dashboard))
    except DomainError as exc:
        await message.answer(str(exc))



@router.message(Command("group_stats"))
async def group_stats(message: Message) -> None:
    """Return a group dashboard only when the sender is that group's leader."""
    if message.from_user is None:
        return
    try:
        dashboard = await sync_to_async(StatisticsService().group_dashboard_for_telegram)(message.from_user.id)
    except DomainError as exc:
        await message.answer(str(exc))
        return
    await message.answer(group_dashboard_text(dashboard))
