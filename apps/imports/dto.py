"""Data Transfer Objects and shared normalization helpers for imports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from apps.common.services.exceptions import ValidationError


def normalize_employee_id(value: object) -> str:
    """Normalize employee ID to 4-digit zero-padded string (e.g. 191 -> '0191')."""
    if value is None:
        raise ValidationError("Employee ID cannot be empty.")
    raw = str(value).replace("\xa0", "").strip()
    if not raw:
        raise ValidationError("Employee ID cannot be empty.")
    
    upper_raw = raw.upper()
    if any(upper_raw.startswith(err) for err in ["#N/A", "#REF!", "#VALUE!", "#NAME?", "#DIV/0!", "#NULL!", "#NUM!", "#ERROR!"]):
        raise ValidationError(f"Formula xatosi tufayli ID o'qilmadi: '{value}'")

    if raw.endswith(".0"):
        raw = raw[:-2]
    result = raw.zfill(4)
    if not result.isdigit():
        raise ValidationError(f"Invalid employee ID '{value}': must contain digits only.")
    return result


def normalize_order_id(value: object) -> str:
    """Normalize order ID (e.g. '51197.0' -> '51197')."""
    if value is None:
        raise ValidationError("Order ID cannot be empty.")
    raw = str(value).strip()
    if not raw:
        raise ValidationError("Order ID cannot be empty.")
    if raw.endswith(".0"):
        raw = raw[:-2]
    return raw


@dataclass(frozen=True, slots=True)
class OrderDTO:
    employee_id: str
    employee_name: str
    group_code: str
    order_id: str
    status: str
    source: str
    sale_amount: Decimal | None
    ordered_at: datetime
    has_sheet_error: bool = False


@dataclass(frozen=True, slots=True)
class PayrollDTO:
    employee_id: str
    employee_name: str
    group_code: str
    monthly_salary: Decimal
    summary_data: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class GroupSummaryDTO:
    group_code: str
    group_profit: Decimal
    leader_bonus: Decimal
    group_total_sales: Decimal = Decimal("0.00")



# Backward-compatibility aliases if needed
WorkbookRow = OrderDTO
PayrollRow = PayrollDTO

