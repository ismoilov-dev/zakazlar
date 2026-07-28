"""Google Sheets implementation of BaseSource using gspread."""

from __future__ import annotations

from decimal import Decimal
import json
import os
import re

from django.core.exceptions import ValidationError
from django.utils.dateparse import parse_date as parse_iso_date
import gspread
from google.oauth2.service_account import Credentials

from apps.imports.dto import OrderDTO, PayrollDTO, normalize_employee_id, normalize_order_id
from apps.imports.sources.base import BaseSource

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

STATUS_MAP = {
    "успешно": "Muvaffaqiyatli",
    "muvaffaqiyatli": "Muvaffaqiyatli",
    "отказ": "Bekor qilingan",
    "bekor qilingan": "Bekor qilingan",
    "в процесс": "Jarayonda",
    "v protsess": "Jarayonda",
    "jarayonda": "Jarayonda",
    "у курьера": "Jarayonda",
}


class SheetsSource(BaseSource):
    """Fetch live data from Google Sheets."""

    def __init__(self, sheet_id: str | None = None, credentials_path: str | None = None) -> None:
        self.sheet_id = (sheet_id or os.environ.get("GOOGLE_SHEET_ID") or "").strip().strip("/")
        if not self.sheet_id:
            raise ValidationError("GOOGLE_SHEET_ID muhit o'zgaruvchisi o'rnatilmagan.")

        self.file_credentials = credentials_path or os.environ.get(
            "GOOGLE_SERVICE_ACCOUNT_FILE", "credentials/service-account.json"
        )
        self.json_credentials = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")

        self.client = self._authenticate()

    def _authenticate(self) -> gspread.Client:
        # Prefer raw JSON env string if present (useful for server deployments)
        if self.json_credentials:
            try:
                info = json.loads(self.json_credentials)
                creds = Credentials.from_service_account_info(info, scopes=SCOPES)
                return gspread.authorize(creds)
            except Exception as exc:
                raise ValidationError(f"GOOGLE_SERVICE_ACCOUNT_JSON ni tahlil qilishda xatolik: {exc}") from exc

        # Fallback to credentials file
        if self.file_credentials and os.path.exists(self.file_credentials):
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

        # Check all candidate payroll worksheets: 'xodimlar maoshi', 'ish haqi', 'list2'
        payroll_candidates: list[gspread.Worksheet] = []
        for name in ["xodimlar maoshi", "ish haqi", "list2"]:
            ws = worksheets.get(name)
            if ws and ws not in payroll_candidates:
                payroll_candidates.append(ws)

        if not payroll_candidates:
            raise ValidationError("Google Sheet'da 'Xodimlar maoshi', 'Ish haqi' yoki 'List2' varog'i topilmadi.")

        payroll_by_id: dict[str, PayrollDTO] = {}
        for ws in payroll_candidates:
            try:
                parsed = self._parse_payroll(ws)
                for dto in parsed:
                    if dto.employee_id not in payroll_by_id:
                        payroll_by_id[dto.employee_id] = dto
            except Exception:
                pass  # Skip optional candidate parse failures

        payroll = list(payroll_by_id.values())

        if not orders:
            raise ValidationError("List1 varog'idan birorta ham buyurtma o'qilmadi.")

        return orders, payroll

    def _parse_orders(self, worksheet: gspread.Worksheet) -> list[OrderDTO]:
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

        # Locate header row dynamically in the first 5 rows
        header_row_idx = None
        for i, row in enumerate(raw_rows[:5]):
            row_str_cells = [str(c).strip() for c in row]
            if any(cell in ["ID", "Tabel raqami"] for cell in row_str_cells):
                header_row_idx = i
                break

        if header_row_idx is None:
            raise ValidationError(f"'{worksheet.title}' varog'ida 'ID' yoki 'Tabel raqami' ustuni topilmadi.")

        headings = raw_rows[header_row_idx]

        # Check header formats for 'Ish haqi', 'Xodimlar maoshi', or 'List2'
        id_idx = self._find_single_column_index(headings, candidates=["Tabel raqami", "ID"], name="ID")
        name_idx = self._find_single_column_index(headings, candidates=["FISH", "XODIMLAR ISMLARI", "Оператор"], name="xodim ismi")
        group_idx = self._find_single_column_index(headings, candidates=["Guruhi", "Bo'lim "], name="guruh", required=False)
        salary_idx = self._find_single_column_index(headings, candidates=["Ish haqi", "OYLIK MOASH", "Oylik maoshi 12%"], name="ish haqi", required=False)

        payroll: list[PayrollDTO] = []
        for row in raw_rows[header_row_idx + 1:]:
            if not any(str(cell).strip() for cell in row):
                continue  # Skip fully empty rows

            id_val = self._get_cell(row, id_idx)
            if not id_val:
                continue

            emp_id = normalize_employee_id(id_val)
            emp_name = self._require_text(self._get_cell(row, name_idx), "Xodim ismi")
            grp_code = (self._get_cell(row, group_idx) or "A").strip().upper()
            salary_str = self._get_cell(row, salary_idx) if salary_idx is not None else ""
            salary = self._parse_money(salary_str) if salary_str else Decimal("0.00")

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
        if not val:
            return Decimal("0.00")
        clean = val.replace(" ", "").replace(",", "").replace("$", "").replace("so'm", "").replace("som", "").strip()
        if not clean:
            return Decimal("0.00")
        try:
            return Decimal(clean)
        except Exception as exc:
            raise ValidationError(f"Noto'g'ri pul summasi formati ('{val}').") from exc

    @staticmethod
    def _parse_date(val: str):
        if not val:
            raise ValidationError("Sana maydoni bo'sh bo'lishi mumkin emas.")
        # Try dd.mm.yyyy format
        m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", val.strip())
        if m:
            day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
            try:
                from datetime import date
                return date(year, month, day)
            except ValueError as exc:
                raise ValidationError(f"Noto'g'ri sana ('{val}'): {exc}") from exc

        # Fallback to ISO parsing (yyyy-mm-dd)
        parsed = parse_iso_date(val.strip())
        if parsed:
            return parsed

        raise ValidationError(f"Noto'g'ri sana formati ('{val}'). Kutilmoqda: dd.mm.yyyy")

    @staticmethod
    def _parse_status(val: str) -> str:
        if not val:
            raise ValidationError("Status maydoni bo'sh bo'lishi mumkin emas.")
        raw = val.strip().lower()
        if raw in STATUS_MAP:
            return STATUS_MAP[raw]
        raise ValidationError(f"Noma'lum status: '{val}'")

    @staticmethod
    def _normalize_source(val: str) -> str:
        raw = val.strip().lower()
        if "первичный" in raw or "pervich" in raw:
            return "Pervichka"
        if "база" in raw or "baza" in raw:
            return "Baza"
        return "Pervichka"
