"""Google Sheets data source for live synchronization."""

from __future__ import annotations

import json
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.utils import timezone
import gspread
from google.oauth2.service_account import Credentials

from apps.common.services.exceptions import ValidationError
from apps.imports.dto import OrderDTO, PayrollDTO, normalize_employee_id, normalize_order_id
from apps.imports.sources.base import BaseSource
from apps.sales.models import SaleStatus

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

STATUS_MAP = {
    "успешно": SaleStatus.SUCCESSFUL,
    "отказ": SaleStatus.CANCELLED,
    "в процесс": SaleStatus.PENDING,
    "у курьера": SaleStatus.PENDING,
}


def clean_sheet_id(raw_id: str) -> str:
    s = raw_id.strip()
    if "/d/" in s:
        s = s.split("/d/")[1].split("/")[0]
    return s.strip("/ ")


class SheetsSource(BaseSource):
    """Reads live orders and payroll from Google Sheets using gspread (Read-only)."""

    def __init__(
        self,
        sheet_id: str | None = None,
        json_credentials: str | None = None,
        file_credentials: str | None = None,
    ) -> None:
        raw_sheet_id = sheet_id or os.getenv("GOOGLE_SHEET_ID", "")
        if not raw_sheet_id:
            raise ValidationError("GOOGLE_SHEET_ID environment variable is missing.")
        self.sheet_id = clean_sheet_id(raw_sheet_id)

        self.json_credentials = json_credentials or os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        self.file_credentials = file_credentials or os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials/service-account.json")

        self.client = self._get_client()

    def _get_client(self) -> gspread.Client:
        if self.json_credentials and self.json_credentials.strip():
            try:
                info = json.loads(self.json_credentials)
                creds = Credentials.from_service_account_info(info, scopes=SCOPES)
                return gspread.authorize(creds)
            except Exception as exc:
                raise ValidationError(f"GOOGLE_SERVICE_ACCOUNT_JSON formatida xatolik: {exc}") from exc

        if self.file_credentials and os.path.exists(self.file_credentials) and os.path.getsize(self.file_credentials) > 0:
            try:
                creds = Credentials.from_service_account_file(self.file_credentials, scopes=SCOPES)
                return gspread.authorize(creds)
            except Exception as exc:
                raise ValidationError(f"GOOGLE_SERVICE_ACCOUNT_FILE yuklashda xatolik ({self.file_credentials}): {exc}") from exc

        raise ValidationError("Google Service Account kalitlari topilmadi (GOOGLE_SERVICE_ACCOUNT_JSON yoki GOOGLE_SERVICE_ACCOUNT_FILE).")

    def read(self) -> tuple[list[OrderDTO], list[PayrollDTO]]:
        """Read data from Google Sheets and return DTO lists. (Read-only)"""
        try:
            spreadsheet = self.client.open_by_key(self.sheet_id)
        except Exception as exc:
            raise ValidationError(f"Google Sheet faylini ochib bo'lmadi (ID: {self.sheet_id}): {exc}") from exc

        worksheets = {ws.title.strip().lower(): ws for ws in spreadsheet.worksheets()}

        if "list1" not in worksheets:
            raise ValidationError("Google Sheet'da 'List1' varog'i topilmadi.")

        orders = self._parse_orders(worksheets["list1"])

        # Check 'Ish haqi' tab first, fallback to 'List2'
        payroll_ws = worksheets.get("ish haqi") or worksheets.get("list2")
        if not payroll_ws:
            raise ValidationError("Google Sheet'da 'Ish haqi' yoki 'List2' varog'i topilmadi.")

        payroll = self._parse_payroll(payroll_ws)

        if not orders:
            raise ValidationError("List1 varog'idan birorta ham buyurtma o'qilmadi.")

        return orders, payroll

    def _parse_orders(self, worksheet: gspread.Worksheet) -> list[OrderDTO]:
        # CHOICE OF VALUE FORMATTING:
        # We deliberately use gspread's default get_all_values() which requests FORMATTED_VALUE
        # from Google Sheets API. This ensures dates arrive as human-readable string text (e.g., '01.06.2026'),
        # avoiding Excel serial date number ambiguity (such as 46174) returned by UNFORMATTED_VALUE.
        raw_rows = worksheet.get_all_values()
        if not raw_rows:
            raise ValidationError("List1 varog'i bo'sh.")

        headings = raw_rows[0]

        # Locate columns strictly by HEADER NAME (never by positional index)
        required_headers = {"№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус"}
        columns = self._find_column_indexes(headings, required_headers, sheet_name="List1")

        # Find group index: check exact " " (single space), or candidates "Guruhi", "Bo'lim "
        group_idx = next((i for i, h in enumerate(headings) if h == " "), None)
        if group_idx is None:
            group_idx = self._find_single_column_index(headings, candidates=["Guruhi", "Bo'lim ", "Guruh"], name="guruh")

        # Source columns candidates
        source_idx = self._find_single_column_index(headings, candidates=["Столбец 2", "Контакт", "Источник"], name="manba", required=False)

        orders: list[OrderDTO] = []
        for row_idx, row in enumerate(raw_rows[1:], start=2):
            if not any(str(cell).strip() for cell in row):
                continue  # Skip fully empty rows

            id_val = self._get_cell(row, columns["ID"])
            if not id_val:
                continue

            try:
                emp_id = normalize_employee_id(id_val)
                emp_name = self._require_text(self._get_cell(row, columns["Ответственный"]), "Ответственный")
                grp_code = (self._get_cell(row, group_idx) or "A").strip().upper()
                if not grp_code:
                    grp_code = "A"
                ord_id = normalize_order_id(self._get_cell(row, columns["№"]))
                stat_val = self._parse_status(self._get_cell(row, columns["статус"]))
                src_val = self._normalize_source(self._get_cell(row, source_idx) if source_idx is not None else "")
                amount = self._parse_money(self._get_cell(row, columns["Сумма"]))
                ordered_at = self._parse_date(self._get_cell(row, columns["Дата Заказа"]))

                orders.append(
                    OrderDTO(
                        employee_id=emp_id,
                        employee_name=emp_name,
                        group_code=grp_code,
                        order_id=ord_id,
                        status=stat_val,
                        source=src_val,
                        sale_amount=amount,
                        ordered_at=ordered_at,
                    )
                )
            except ValidationError as exc:
                raise ValidationError(f"List1 varog'i, {row_idx}-qator: {exc}") from exc

        return orders

    def _parse_payroll(self, worksheet: gspread.Worksheet) -> list[PayrollDTO]:
        raw_rows = worksheet.get_all_values()
        if not raw_rows:
            raise ValidationError(f"'{worksheet.title}' varog'i bo'sh.")

        headings = raw_rows[0]

        # Check header formats for 'Ish haqi' or 'List2'
        id_idx = self._find_single_column_index(headings, candidates=["Tabel raqami", "ID"], name="ID")
        name_idx = self._find_single_column_index(headings, candidates=["FISH", "XODIMLAR ISMLARI "], name="xodim ismi")
        group_idx = self._find_single_column_index(headings, candidates=["Guruhi", "Bo'lim "], name="guruh", required=False)
        salary_idx = self._find_single_column_index(headings, candidates=["Ish haqi", "OYLIK MOASH "], name="ish haqi")

        payroll: list[PayrollDTO] = []
        for row in raw_rows[1:]:
            if not any(str(cell).strip() for cell in row):
                continue  # Skip fully empty rows

            id_val = self._get_cell(row, id_idx)
            if not id_val:
                continue

            emp_id = normalize_employee_id(id_val)
            emp_name = self._require_text(self._get_cell(row, name_idx), "Xodim ismi")
            grp_code = (self._get_cell(row, group_idx) or "A").strip().upper()
            salary = self._parse_money(self._get_cell(row, salary_idx))

            payroll.append(
                PayrollDTO(
                    employee_id=emp_id,
                    employee_name=emp_name,
                    group_code=grp_code if grp_code else "A",
                    monthly_salary=salary,
                )
            )

        return payroll

    @staticmethod
    def _find_column_indexes(headings: list[str], required: set[str], sheet_name: str) -> dict[str, int]:
        found: dict[str, int] = {}
        for idx, col_name in enumerate(headings):
            col_clean = str(col_name).strip()
            if col_clean in required and col_clean not in found:
                found[col_clean] = idx

        missing = required - set(found.keys())
        if missing:
            raise ValidationError(
                f"Google Sheet '{sheet_name}' varog'ida majburiy ustunlar topilmadi: {', '.join(sorted(missing))}"
            )
        return found

    @staticmethod
    def _find_single_column_index(
        headings: list[str], candidates: list[str], name: str, required: bool = True
    ) -> int | None:
        for candidate in candidates:
            for idx, col_name in enumerate(headings):
                if str(col_name).strip() == candidate.strip():
                    return idx

        if required:
            raise ValidationError(f"Ustun topilmadi ('{name}'): mos nomlar {candidates}")
        return None

    @staticmethod
    def _get_cell(row: list[str], idx: int | None) -> str:
        if idx is None or idx >= len(row):
            return ""
        return str(row[idx]).strip()

    @staticmethod
    def _require_text(val: str, field_name: str) -> str:
        if not val:
            raise ValidationError(f"'{field_name}' maydoni bo'sh bo'lishi mumkin emas.")
        return val

    @staticmethod
    def _parse_money(val: str) -> Decimal:
        if not val or val.startswith("#"):
            return Decimal("0.00")
        clean_str = val.replace(",", "").replace(" ", "").replace("\xa0", "").strip()
        try:
            return Decimal(clean_str).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError, ValueError):
            return Decimal("0.00")

    @staticmethod
    def _parse_status(val: str) -> str:
        raw = val.strip().lower()
        if raw in STATUS_MAP:
            return STATUS_MAP[raw]
        raise ValidationError(f"Noma'lum status: '{val}'")

    @staticmethod
    def _parse_date(val: str) -> datetime:
        # Expecting dd.mm.yyyy string format from FORMATTED_VALUE
        if not val:
            raise ValidationError("Sana maydoni bo'sh.")
        formats = ["%d.%m.%Y", "%Y-%m-%d", "%d.%m.%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"]
        for fmt in formats:
            try:
                dt = datetime.strptime(val.strip(), fmt)
                if timezone.is_naive(dt):
                    return timezone.make_aware(dt, timezone.get_current_timezone())
                return dt
            except ValueError:
                continue
        raise ValidationError(f"Sana formati noto'g'ri: '{val}'. Kutilgan format: dd.mm.yyyy")

    @staticmethod
    def _normalize_source(raw: str) -> str:
        s = raw.strip().lower()
        if "perv" in s or "первич" in s:
            return "Pervichka"
        if "baza" in s or "база" in s:
            return "Baza"
        return raw.strip() if raw.strip() else "Pervichka"
