"""Google Sheets implementation of BaseSource using gspread."""

from __future__ import annotations

import json
import logging
import os
import re
from decimal import Decimal

logger = logging.getLogger(__name__)

from django.core.exceptions import ValidationError

from apps.common.services.exceptions import ValidationError as DomainValidationError

PARSE_ERRORS = (ValidationError, DomainValidationError)
import gspread
from django.utils import timezone
from django.utils.dateparse import parse_date as parse_iso_date
from google.oauth2.service_account import Credentials

from apps.imports.dto import (
    GroupSummaryDTO,
    OrderDTO,
    PayrollDTO,
    normalize_employee_id,
    normalize_order_id,
)
from apps.imports.sources.base import BaseSource

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

SHEETS_FORWARD_FILL_EMPLOYEE_ID = True
MAX_SKIPPED_ROWS_RATIO_THRESHOLD = 0.05

STATUS_MAP = {
    "успешно": "successful",
    "успешна": "successful",
    "muvaffaqiyatli": "successful",
    "доставлен": "successful",
    "доставлено": "successful",
    "оплачено": "successful",
    "bajarildi": "successful",
    "отказ": "cancelled",
    "bekor qilingan": "cancelled",
    "otkaz": "cancelled",
    "bekor": "cancelled",
    "отмена": "cancelled",
    "возврат": "cancelled",
    "в процесс": "pending",
    "v protsess": "pending",
    "v process": "pending",
    "jarayonda": "pending",
    "у курьера": "pending",
    "курьер": "pending",
    "kuryerda": "pending",
    "ожидание": "pending",
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

        self.last_dropped_payroll_rows = []

        worksheets = {ws.title.strip().lower(): ws for ws in spreadsheet.worksheets()}


        if "list1" not in worksheets:
            raise ValidationError("Google Sheet'da 'List1' varog'i topilmadi.")

        # Check all candidate payroll worksheets: 'list2' prioritized first, then 'xodimlar maoshi', 'ish haqi'
        payroll_candidates: list[gspread.Worksheet] = []
        for name in ["list2", "xodimlar maoshi", "ish haqi"]:
            ws = worksheets.get(name)
            if ws and ws not in payroll_candidates:
                payroll_candidates.append(ws)

        if not payroll_candidates:
            raise ValidationError("Google Sheet'da 'List2', 'Xodimlar maoshi' yoki 'Ish haqi' varog'i topilmadi.")

        payroll_by_id: dict[str, PayrollDTO] = {}
        successful_parses = 0
        for ws in payroll_candidates:
            try:
                parsed = self._parse_payroll(ws)
                for dto in parsed:
                    existing = payroll_by_id.get(dto.employee_id)
                    if existing is None or (dto.summary_data and not existing.summary_data):
                        payroll_by_id[dto.employee_id] = dto
                successful_parses += 1
            except Exception as exc:
                logger.warning("Payroll varag'ini ('%s') tahlil qilishda xatolik: %s", ws.title, exc)

        if successful_parses == 0:
            raise ValidationError("Birorta ham payroll varog'ini tahlil qilib bo'lmadi.")

        payroll = list(payroll_by_id.values())
        valid_employee_ids = set(payroll_by_id.keys())

        orders = self._parse_orders(worksheets["list1"], valid_employee_ids=valid_employee_ids)

        if not orders:
            raise ValidationError("List1 varog'idan birorta ham buyurtma o'qilmadi.")

        ws_guruhlar = worksheets.get("guruhlar")
        groups_summary: list[GroupSummaryDTO] = []
        if ws_guruhlar:
            try:
                groups_summary = self._parse_groups(ws_guruhlar)
            except Exception as exc:
                logger.warning("Guruhlar varag'ini tahlil qilishda xatolik: %s", exc)
        else:
            logger.warning("Google Sheet'da 'Guruhlar' varog'i topilmadi.")

        self.groups_summary = groups_summary

        return orders, payroll


    def _parse_orders(self, worksheet: gspread.Worksheet, valid_employee_ids: set[str] | None = None) -> list[OrderDTO]:

        raw_rows = worksheet.get_all_values(combine_merged_cells=True)
        if not raw_rows:
            raise ValidationError("List1 varog'i bo'sh.")

        # Dynamically locate header row in first 15 rows with case-insensitive trimmed matching
        header_row_idx = None
        for i, r in enumerate(raw_rows[:15]):
            row_str_cells = [str(c).strip().lower() for c in r]
            if any(cell in ["id", "tabel raqami", "№"] for cell in row_str_cells):
                header_row_idx = i
                break

        if header_row_idx is None:
            raise ValidationError(
                f"Google Sheet '{worksheet.title}' varog'ida sarlavha qatori (ID / Tabel raqami / №) topilmadi. Dastlabki 3 qator: {raw_rows[:3]}"
            )

        headings = raw_rows[header_row_idx]

        id_idx = self._find_single_column_index(headings, candidates=["ID", "Tabel raqami", "User ID", "Id", "id"], name="ID")
        ord_idx = self._find_single_column_index(headings, candidates=["№", "Zakaz №", "Order ID", "Номер", "No", "Nomer"], name="№", required=False)
        name_idx = self._find_single_column_index(headings, candidates=["Ответственный", "Xodim", "Menejer", "Operator", "ФИО", "FISH", "XODIMLAR ISMLARI", "Xodim ismi"], name="Ответственный", required=False)
        amount_idx = self._find_single_column_index(headings, candidates=["Сумма", "Summa", "Narxi", "Qiymati", "Summasi", "Obshiy summa"], name="Сумма", required=False)
        date_idx = self._find_single_column_index(headings, candidates=["Дата Заказа", "Дата", "Sana", "Zakaz sanasi", "Sana/vaqt"], name="Дата Заказа", required=False)
        status_idx = self._find_single_column_index(headings, candidates=["статус", "Статус", "Status", "Holat", "Holati"], name="статус", required=False)

        # Find group index: check exact " " (single space), or candidates "Guruhi", "Bo'lim "
        group_idx = next((i for i, h in enumerate(headings) if h == " "), None)
        if group_idx is None:
            group_idx = self._find_single_column_index(headings, candidates=["Guruhi", "Bo'lim ", "Guruh"], name="guruh", required=False)

        source_candidates = ["Столбец 2", "Контакт", "Источник", "manba", "Manba"]
        source_idx = self._find_single_column_index(headings, candidates=source_candidates, name="manba", required=False)

        if source_idx is None:
            logger.error("List1 varog'ida manba ustuni topilmadi. Qidirilgan nomlar: %s | Mavjud sarlavhalar: %s", source_candidates, headings)
            raise ValidationError(
                f"List1 varog'ida manba ustuni topilmadi. Qidirilgan nomlar: {source_candidates}. Mavjud sarlavhalar: {headings}"
            )

        self.last_header_row_idx = header_row_idx
        self.last_headings = headings
        self.last_column_indexes = {
            "ID": id_idx,
            "№": ord_idx,
            "Ответственный": name_idx,
            "Сумма": amount_idx,
            "Дата Заказа": date_idx,
            "статус": status_idx,
            "guruh": group_idx,
            "manba": source_idx,
        }

        logger.info(
            "List1 sarlavha qatori indeksi: %s, ID ustuni indeksi: %s, Headings: %s",
            header_row_idx,
            id_idx,
            headings,
        )

        orders: list[OrderDTO] = []
        dropped_rows: list[dict[str, object]] = []

        total_raw_rows = len(raw_rows[header_row_idx + 1:])
        empty_rows_skipped = 0

        dropped_empty_id = 0
        dropped_invalid_id = 0
        parsed_rows_count = 0
        last_seen_emp_id: str | None = None
        last_seen_emp_name: str | None = None
        from collections import Counter
        unrecognized_sources_count = Counter()



        for row_idx, row in enumerate(raw_rows[header_row_idx + 1:], start=header_row_idx + 2):

            # Test for an all-empty row first, before any field-level validation
            row_str_values = [str(cell or "").replace("\xa0", "").strip() for cell in row]
            if not any(row_str_values):
                empty_rows_skipped += 1
                continue  # Skip fully empty rows

            id_val = self._get_cell(row, id_idx)
            raw_emp_name = self._get_cell(row, name_idx).strip() if name_idx is not None else ""
            ord_raw = self._get_cell(row, ord_idx) if ord_idx is not None else ""
            amount_str = self._get_cell(row, amount_idx) if amount_idx is not None else ""
            stat_raw = self._get_cell(row, status_idx) if status_idx is not None else ""
            has_meaningful_content = bool(ord_raw.strip() or amount_str.strip() or stat_raw.strip())

            # Secondary check: if all mapped cells are empty, treat as empty row
            if not id_val and not raw_emp_name and not ord_raw and not amount_str and not stat_raw:
                empty_rows_skipped += 1
                continue


            emp_id: str | None = None
            if id_val:
                try:
                    emp_id = normalize_employee_id(id_val)
                    last_seen_emp_id = emp_id
                    if raw_emp_name:
                        last_seen_emp_name = raw_emp_name
                except PARSE_ERRORS as exc:
                    dropped_invalid_id += 1
                    reason = f"ID formati noto'g'ri: {exc}"
                    first_6 = [str(c).strip() for c in row[:6]]
                    dropped_rows.append({"row_idx": row_idx, "reason": reason, "raw_cells": first_6, "row_data": row})
                    logger.warning("List1 %s-qator tashlandi: %s | Birinchi 6 katak: %s", row_idx, reason, first_6)
                    continue
            else:
                names_match = (
                    name_idx is not None
                    and last_seen_emp_name is not None
                    and bool(raw_emp_name)
                    and raw_emp_name.lower() == last_seen_emp_name.lower()
                )
                if has_meaningful_content and SHEETS_FORWARD_FILL_EMPLOYEE_ID and last_seen_emp_id and names_match:
                    emp_id = last_seen_emp_id
                    logger.info(
                        "List1 %s-qator bo'sh ID forward-fill qilindi: %s (ism: %s)",
                        row_idx,
                        emp_id,
                        last_seen_emp_name,
                    )
                else:
                    dropped_empty_id += 1
                    reason = "ID katakchasi bo'sh yoki ism mos kelmadi"
                    first_6 = [str(c).strip() for c in row[:6]]
                    dropped_rows.append({"row_idx": row_idx, "reason": reason, "raw_cells": first_6, "row_data": row})
                    logger.warning("List1 %s-qator tashlandi: %s | Birinchi 6 katak: %s", row_idx, reason, first_6)
                    continue

            if valid_employee_ids is not None and emp_id not in valid_employee_ids:
                dropped_invalid_id += 1
                reason = f"Xodim ID ({emp_id}) List2 varog'ida topilmadi"
                first_6 = [str(c).strip() for c in row[:6]]
                dropped_rows.append({"row_idx": row_idx, "reason": reason, "raw_cells": first_6, "row_data": row})
                logger.warning("List1 %s-qator tashlandi: %s | Birinchi 6 katak: %s", row_idx, reason, first_6)
                continue


            emp_name = self._get_cell(row, name_idx).strip() if name_idx is not None else "Noma'lum"
            if not emp_name:
                emp_name = "Noma'lum"

            grp_code = (self._get_cell(row, group_idx) or "A").strip().upper() if group_idx is not None else "A"
            if not grp_code:
                grp_code = "A"

            date_raw = self._get_cell(row, date_idx) if date_idx is not None else ""
            try:
                ordered_at = self._parse_date(date_raw)
            except PARSE_ERRORS as exc:
                dropped_invalid_id += 1
                reason = f"Sana formati noto'g'ri: {exc}"
                first_6 = [str(c).strip() for c in row[:6]]
                dropped_rows.append({"row_idx": row_idx, "reason": reason, "raw_cells": first_6, "row_data": row})
                logger.warning("List1 %s-qator tashlandi: %s | Birinchi 6 katak: %s", row_idx, reason, first_6)
                continue

            if ordered_at.date() > timezone.localtime().date():
                dropped_invalid_id += 1
                reason = f"Kelajakdagi sana rad etildi: {date_raw}"
                first_6 = [str(c).strip() for c in row[:6]]
                dropped_rows.append({"row_idx": row_idx, "reason": reason, "raw_cells": first_6, "row_data": row})
                logger.warning("List1 %s-qator tashlandi: %s | Birinchi 6 katak: %s", row_idx, reason, first_6)
                continue

            if not ord_raw.strip():
                dropped_invalid_id += 1
                reason = "Zakaz raqami (№) bo'sh"
                first_6 = [str(c).strip() for c in row[:6]]
                dropped_rows.append({"row_idx": row_idx, "reason": reason, "raw_cells": first_6, "row_data": row})
                logger.warning("List1 %s-qator tashlandi: %s | Birinchi 6 katak: %s", row_idx, reason, first_6)
                continue

            try:
                stat_val = self._parse_status(stat_raw)
            except PARSE_ERRORS as exc:
                dropped_invalid_id += 1
                reason = f"Status xatosi: {exc}"
                first_6 = [str(c).strip() for c in row[:6]]
                dropped_rows.append({"row_idx": row_idx, "reason": reason, "raw_cells": first_6, "row_data": row})
                logger.warning("List1 %s-qator tashlandi: %s | Birinchi 6 katak: %s", row_idx, reason, first_6)
                continue

            try:
                amount = self._parse_money(amount_str, sheet_name="List1", row_idx=row_idx)
            except PARSE_ERRORS as exc:
                dropped_invalid_id += 1
                reason = f"Summa xatosi: {exc}"
                first_6 = [str(c).strip() for c in row[:6]]
                dropped_rows.append({"row_idx": row_idx, "reason": reason, "raw_cells": first_6, "row_data": row})
                logger.warning("List1 %s-qator tashlandi: %s | Birinchi 6 katak: %s", row_idx, reason, first_6)
                continue


            src_raw_cell = self._get_cell(row, source_idx) if source_idx is not None else ""
            src_val, unrecognized_src = self._normalize_source(src_raw_cell)
            if unrecognized_src:
                unrecognized_sources_count[unrecognized_src] += 1


            try:
                clean_ord = normalize_order_id(ord_raw)
                ord_id = f"{ordered_at:%Y%m}_{emp_id}_{clean_ord}"
            except PARSE_ERRORS as exc:
                dropped_invalid_id += 1
                reason = f"Zakaz raqami (№) formati noto'g'ri: {exc}"
                first_6 = [str(c).strip() for c in row[:6]]
                dropped_rows.append({"row_idx": row_idx, "reason": reason, "raw_cells": first_6, "row_data": row})
                logger.warning("List1 %s-qator tashlandi: %s | Birinchi 6 katak: %s", row_idx, reason, first_6)
                continue

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
            parsed_rows_count += 1

        if unrecognized_sources_count:
            logger.debug("List1 noma'lum manba (source) qiymatlari agregatsiyasi: %s", dict(unrecognized_sources_count))

        dropped_count = len(dropped_rows)
        self.last_dropped_rows = dropped_rows
        self.last_parse_summary = {
            "total_raw_rows": total_raw_rows,
            "empty_rows_skipped": empty_rows_skipped,
            "dropped_count": dropped_count,
            "dropped_empty_id": dropped_empty_id,
            "dropped_invalid_id": dropped_invalid_id,
            "parsed_rows_count": parsed_rows_count,
        }

        logger.info(
            "List1 parse yakunlandi: jami %s qator, bo'sh: %s, tashlangan: %s, muvaffaqiyatli: %s",
            total_raw_rows,
            empty_rows_skipped,
            dropped_count,
            parsed_rows_count,
        )


        return orders


    def _parse_payroll(self, worksheet: gspread.Worksheet) -> list[PayrollDTO]:
        raw_rows = worksheet.get_all_values(combine_merged_cells=True)
        if not raw_rows:
            raise ValidationError(f"'{worksheet.title}' varog'i bo'sh.")

        # Locate header row dynamically in the first 15 rows
        header_row_idx = None
        for i, row in enumerate(raw_rows[:15]):
            row_str_cells = [str(c).strip().lower() for c in row]
            if any(cell in ["id", "tabel raqami"] for cell in row_str_cells):
                header_row_idx = i
                break

        if header_row_idx is None:
            raise ValidationError(f"'{worksheet.title}' varog'ida 'ID' yoki 'Tabel raqami' ustuni topilmadi.")

        headings = raw_rows[header_row_idx]

        # Check header formats for 'Ish haqi', 'Xodimlar maoshi', or 'List2'
        id_idx = self._find_single_column_index(headings, candidates=["Tabel raqami", "ID"], name="ID")
        name_idx = self._find_single_column_index(headings, candidates=["FISH", "XODIMLAR ISMLARI", "Оператор"], name="xodim ismi")
        group_idx = self._find_single_column_index(headings, candidates=["Guruhi", "Bo'lim "], name="guruh", required=False)
        salary_idx = self._find_single_column_index(
            headings,
            candidates=["Ish haqi", "Oylik ish haqi", "OYLIK MOASH", "OYLIK MAOSH", "Oylik maosh", "Oylik maoshi 12%", "Oylik", "Maosh", "Зарплата", "Оклад"],
            name="ish haqi",
            required=False,
        )


        total_sales_idx = self._find_single_column_index(headings, candidates=["Umumiy zakaz summasi", "Общая сумма", "Jami summa"], name="total_sales", required=False)
        perv_sales_idx = self._find_single_column_index(headings, candidates=["Первичный Заказ", "Первичка"], name="perv_sales", required=False)
        baza_sales_idx = self._find_single_column_index(headings, candidates=["База"], name="baza_sales", required=False)
        otkaz_sales_idx = self._find_single_column_index(headings, candidates=["Otkaz", "Отказ"], name="otkaz_sales", required=False)
        v_proc_sales_idx = self._find_single_column_index(headings, candidates=["В процесс", "В процессе"], name="v_proc_sales", required=False)
        upakovka_idx = self._find_single_column_index(headings, candidates=["Upakovka soni", "Upakovka", "Упаковка"], name="upakovka", required=False)
        conv_idx = self._find_single_column_index(headings, candidates=["Konversiya", "Конверсия"], name="conversion", required=False)
        real_conv_idx = self._find_single_column_index(headings, candidates=["Real konversiya", "Реальная конверсия"], name="real_conversion", required=False)

        successful_sales_idx = self._find_single_column_index(
            headings,
            candidates=["Uspeshka summasi", "Uspeshka", "Успешка summasi", "Успешка"],
            name="successful_sales",
            required=False,
        )

        payroll: list[PayrollDTO] = []
        for row_idx, row in enumerate(raw_rows[header_row_idx + 1:], start=header_row_idx + 2):
            if not any(str(cell).strip() for cell in row):
                continue  # Skip fully empty rows

            try:
                id_val = self._get_cell(row, id_idx)
                if not id_val:
                    continue

                emp_id = normalize_employee_id(id_val)
                emp_name = self._require_text(self._get_cell(row, name_idx), "Xodim ismi")
                grp_code = (self._get_cell(row, group_idx) or "A").strip().upper()
                salary_str = self._get_cell(row, salary_idx) if salary_idx is not None else ""
                salary = self._parse_money(salary_str) if salary_str else Decimal("0.00")

                summary: dict[str, object] = {}
                if total_sales_idx is not None and self._get_cell(row, total_sales_idx):
                    summary["total_sales"] = str(self._parse_money(self._get_cell(row, total_sales_idx)))
                if successful_sales_idx is not None and self._get_cell(row, successful_sales_idx):
                    summary["successful_sales"] = str(self._parse_money(self._get_cell(row, successful_sales_idx)))
                if perv_sales_idx is not None and self._get_cell(row, perv_sales_idx):
                    summary["perv_sales"] = str(self._parse_money(self._get_cell(row, perv_sales_idx)))
                if baza_sales_idx is not None and self._get_cell(row, baza_sales_idx):
                    summary["baza_sales"] = str(self._parse_money(self._get_cell(row, baza_sales_idx)))
                if otkaz_sales_idx is not None and self._get_cell(row, otkaz_sales_idx):
                    summary["otkaz_sales"] = str(self._parse_money(self._get_cell(row, otkaz_sales_idx)))
                if v_proc_sales_idx is not None and self._get_cell(row, v_proc_sales_idx):
                    summary["v_proc_sales"] = str(self._parse_money(self._get_cell(row, v_proc_sales_idx)))
                if upakovka_idx is not None and self._get_cell(row, upakovka_idx):
                    try:
                        summary["successful_orders"] = int(float(str(self._get_cell(row, upakovka_idx)).replace(",", ".")))
                    except Exception:
                        pass
                if salary_str:
                    summary["earned_salary"] = str(salary)
                if conv_idx is not None and self._get_cell(row, conv_idx):
                    raw_c = str(self._get_cell(row, conv_idx)).replace("%", "").replace(",", ".").strip()
                    try:
                        summary["conversion_rate"] = float(Decimal(raw_c) / 100) if float(Decimal(raw_c)) > 1 else float(Decimal(raw_c))
                    except Exception:
                        pass
                if real_conv_idx is not None and self._get_cell(row, real_conv_idx):
                    raw_rc = str(self._get_cell(row, real_conv_idx)).replace("%", "").replace(",", ".").strip()
                    try:
                        summary["real_conversion_rate"] = float(Decimal(raw_rc) / 100) if float(Decimal(raw_rc)) > 1 else float(Decimal(raw_rc))
                    except Exception:
                        pass

                payroll.append(
                    PayrollDTO(
                        employee_id=emp_id,
                        employee_name=emp_name,
                        group_code=grp_code if grp_code else "A",
                        monthly_salary=salary,
                        summary_data=summary if summary else None,
                    )
                )
            except PARSE_ERRORS as exc:
                logger.warning("Payroll varog'i '%s', %s-qator tahlil xatosi: %s", worksheet.title, row_idx, exc)
                if not hasattr(self, "last_dropped_payroll_rows"):
                    self.last_dropped_payroll_rows = []
                self.last_dropped_payroll_rows.append(
                    {
                        "sheet_title": worksheet.title,
                        "row_idx": row_idx,
                        "reason": str(exc),
                        "row_data": row,
                    }
                )
                continue


        return payroll


    def _parse_groups(self, worksheet: gspread.Worksheet) -> list[GroupSummaryDTO]:
        raw_rows = worksheet.get_all_values(combine_merged_cells=True)
        if not raw_rows:
            return []

        # 1. Try vertical format first if 'Guruh foydasi' column exists in header
        header_row_idx = None
        for i, row in enumerate(raw_rows[:15]):
            row_str_cells = [str(c).strip().lower() for c in row]
            if "guruh foydasi" in row_str_cells:
                header_row_idx = i
                break

        if header_row_idx is not None:
            headings = raw_rows[header_row_idx]
            code_idx = self._find_single_column_index(headings, candidates=["Guruh", "Bo'lim"], name="guruh", required=False)
            profit_idx = self._find_single_column_index(headings, candidates=["Guruh foydasi"], name="guruh foydasi", required=False)
            bonus_idx = self._find_single_column_index(headings, candidates=["Rahbar bonusi"], name="rahbar bonusi", required=False)

            if code_idx is not None and profit_idx is not None:
                groups: list[GroupSummaryDTO] = []
                for row in raw_rows[header_row_idx + 1:]:
                    if not any(str(cell).strip() for cell in row):
                        continue
                    grp_code = self._get_cell(row, code_idx).upper()
                    if not grp_code:
                        continue
                    profit = self._parse_money(self._get_cell(row, profit_idx))
                    bonus = self._parse_money(self._get_cell(row, bonus_idx)) if bonus_idx is not None else (profit * Decimal("0.02"))
                    groups.append(GroupSummaryDTO(group_code=grp_code, group_profit=profit, leader_bonus=bonus))
                if groups:
                    return groups

        # 2. Horizontal layout parsing (Row 0 has group codes A, B, C, D, BAZA, last JAMI row has totals)
        row0 = raw_rows[0]
        summary_row = None
        for row in reversed(raw_rows):
            cell0 = str(row[0] if row else "").strip().upper()
            if "JAMI" in cell0 or "ИТОГО" in cell0:
                summary_row = row
                break

        if not summary_row and len(raw_rows) > 1:
            summary_row = raw_rows[-1]

        if not summary_row:
            return []

        groups = []
        seen_codes: set[str] = set()
        for col_idx, cell_val in enumerate(row0):
            code = str(cell_val).strip().upper()
            if code in ["A", "B", "C", "D", "BAZA", "PERVICHKA"] and code not in seen_codes:
                seen_codes.add(code)
                total_val = summary_row[col_idx] if col_idx < len(summary_row) else "0"
                profit_col = col_idx + 1 if (col_idx + 1 < len(summary_row)) else col_idx
                profit_val = summary_row[profit_col] if profit_col < len(summary_row) else "0"
                try:
                    total_sales = self._parse_money(total_val)
                except Exception:
                    total_sales = Decimal("0.00")
                try:
                    profit = self._parse_money(profit_val)
                except Exception:
                    profit = Decimal("0.00")
                bonus = (profit * Decimal("0.02")).quantize(Decimal("0.01"))
                groups.append(
                    GroupSummaryDTO(
                        group_code=code,
                        group_total_sales=total_sales,
                        group_profit=profit,
                        leader_bonus=bonus,
                    )
                )

        return groups





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
    def _parse_money(val: object, sheet_name: str = "Sheet", row_idx: int | str = "") -> Decimal:
        if val is None:
            return Decimal("0.00")
        s = str(val).strip()
        if not s:
            return Decimal("0.00")
        clean = s.replace(" ", "").replace("\xa0", "").replace("$", "").replace("so'm", "").replace("som", "").strip()
        if not clean:
            return Decimal("0.00")
        if "." not in clean and clean.count(",") == 1:
            clean = clean.replace(",", ".")
        else:
            clean = clean.replace(",", "")
        try:
            return Decimal(clean)
        except Exception as exc:
            logger.warning("Noto'g'ri pul summasi formati ('%s') varog': '%s', qator: %s", s, sheet_name, row_idx)
            raise ValidationError(f"Noto'g'ri pul summasi formati ('{s}'): {exc}") from exc


    @staticmethod
    def _parse_date(val: str):
        from datetime import date, datetime, time

        from django.utils import timezone

        if not val:
            raise ValidationError("Sana maydoni bo'sh bo'lishi mumkin emas.")

        clean_val = str(val).strip()

        # Extract date portion if time is attached (e.g. "01.07.2026 14:30:00")
        if " " in clean_val:
            clean_val = clean_val.split()[0]

        # 1. Match dd.mm.yyyy or dd.mm.yy or d.m.yyyy or d.m.yy (with dot, slash, or dash)
        m = re.match(r"^(\d{1,2})[\.\/-](\d{1,2})[\.\/-](\d{2,4})$", clean_val)
        if m:
            day, month, year_str = int(m.group(1)), int(m.group(2)), m.group(3)
            year = int(year_str)
            if len(year_str) == 2:
                year += 2000
            try:
                d = date(year, month, day)
                return timezone.make_aware(datetime.combine(d, time.min))
            except ValueError as exc:
                raise ValidationError(f"Noto'g'ri sana ('{val}'): {exc}") from exc

        # 2. Match yyyy-mm-dd or yyyy/mm/dd
        m = re.match(r"^(\d{4})[\.\/-](\d{1,2})[\.\/-](\d{1,2})$", clean_val)
        if m:
            year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            try:
                d = date(year, month, day)
                return timezone.make_aware(datetime.combine(d, time.min))
            except ValueError as exc:
                raise ValidationError(f"Noto'g'ri sana ('{val}'): {exc}") from exc

        # 3. Fallback to ISO parsing
        parsed = parse_iso_date(clean_val)
        if parsed:
            return timezone.make_aware(datetime.combine(parsed, time.min))

        raise ValidationError(f"Noto'g'ri sana formati ('{val}'). Kutilmoqda: dd.mm.yyyy")

    @staticmethod
    def _parse_status(val: str) -> str:
        if not val:
            raise ValidationError("Status maydoni bo'sh bo'lishi mumkin emas.")
        raw = val.strip().lower()
        if raw in STATUS_MAP:
            return STATUS_MAP[raw]
        if any(term in raw for term in ["отказ", "возврат", "otkaz", "bekor"]):
            return "cancelled"
        if any(term in raw for term in ["процесс", "курьер", "ожидан", "protsess", "process", "jarayon", "kuryer"]):
            return "pending"
        raise ValidationError(f"Noma'lum status: '{val}'")

    @staticmethod
    def _normalize_source(val: str) -> tuple[str, str | None]:
        if not val or not val.strip():
            return "UNKNOWN", None
        raw = val.strip().lower()
        if "первичный" in raw or "pervich" in raw:
            return "Pervichka", None
        if "база" in raw or "baza" in raw:
            return "Baza", None
        return "UNKNOWN", val.strip()