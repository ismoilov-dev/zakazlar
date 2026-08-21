"""Google Sheets implementation of BaseSource using gspread."""

from __future__ import annotations

import json
import logging
import os
import re
from decimal import Decimal

logger = logging.getLogger(__name__)

from django.core.cache import cache
from django.core.exceptions import ValidationError

from apps.common.services.exceptions import ValidationError as DomainValidationError

PARSE_ERRORS = (ValidationError, DomainValidationError)
import gspread
from collections import Counter, defaultdict
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

SHEET_ERROR_LITERALS: set[str] = {
    "#N/A",
    "#REF!",
    "#DIV/0!",
    "#VALUE!",
    "#NAME?",
    "#NULL!",
    "#NUM!",
    "#ERROR!",
    "#N/A N/A",
}

STATUS_MAP = {
    "успешно": "successful",
    "успешна": "successful",
    "успешка": "successful",
    "успешные": "successful",
    "успешный": "successful",
    "успешно.": "successful",
    "uspeshka": "successful",
    "muvaffaqiyatli": "successful",
    "доставлен": "successful",
    "доставлено": "successful",
    "доставили": "successful",
    "доставка": "successful",
    "оплачено": "successful",
    "оплачен": "successful",
    "сдан": "successful",
    "сдано": "successful",
    "bajarildi": "successful",
    "topshirildi": "successful",
    "qabul qilindi": "successful",
    "отказ": "cancelled",
    "bekor qilingan": "cancelled",
    "otkaz": "cancelled",
    "bekor": "cancelled",
    "отмена": "cancelled",
    "возврат": "cancelled",
    "в процес": "pending",
    "в процес.": "pending",
    "в процесс": "pending",
    "в процесс.": "pending",
    "v protsess": "pending",
    "v process": "pending",
    "jarayonda": "pending",
    "у курьер": "successful",
    "у курьер.": "successful",
    "у курьера": "successful",
    "у курьера.": "successful",
    "курьер": "successful",
    "курьерда": "successful",
    "kuryerda": "successful",
    "ожидание": "pending",
}


def resolve_spreadsheet_id(passed_sheet_id: str | None = None) -> tuple[str, str]:
    """Resolve spreadsheet ID and return (sheet_id, source_description).

    Resolution order:
    1. Explicitly passed sheet_id (if non-empty)
    2. Active SpreadsheetPeriod in database (is_active=True)
    3. Fallback to GOOGLE_SHEET_ID in environment
    """
    if passed_sheet_id:
        clean_id = passed_sheet_id.strip().strip("/")
        if clean_id:
            return clean_id, "explicit argument"

    try:
        from apps.imports.models import SpreadsheetPeriod
        active_period = SpreadsheetPeriod.objects.filter(is_active=True).first()
        if active_period and active_period.spreadsheet_id:
            period_str = active_period.period.strftime("%Y-%m")
            return active_period.spreadsheet_id.strip().strip("/"), f"DB SpreadsheetPeriod ({period_str})"
    except Exception as exc:
        logger.warning("SpreadsheetPeriod o'qishda xatolik: %s", exc)

    env_id = (os.environ.get("GOOGLE_SHEET_ID") or "").strip().strip("/")
    if env_id:
        return env_id, "env fallback"

    raise ValidationError("GOOGLE_SHEET_ID muhit o'zgaruvchisi yoki faol SpreadsheetPeriod topilmadi.")


class SheetsSource(BaseSource):
    """Fetch live data from Google Sheets."""

    def __init__(self, sheet_id: str | None = None, credentials_path: str | None = None) -> None:
        self.sheet_id, source_desc = resolve_spreadsheet_id(sheet_id)
        logger.info("SheetsSource resolved spreadsheet ID: %s from %s", self.sheet_id, source_desc)

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

    def read_payroll_only(self) -> tuple[list[PayrollDTO], list[GroupSummaryDTO]]:
        """Read List2 (payroll) and Guruhlar worksheets using a single values_batch_get API call."""
        try:
            spreadsheet = self.client.open_by_key(self.sheet_id)
        except Exception as exc:
            raise ValidationError(f"Google Sheet faylini ochib bo'lmadi (ID: {self.sheet_id}): {exc}") from exc

        self.last_dropped_payroll_rows = []

        cache_key = f"sheets_ws_titles_{self.sheet_id}"
        ws_titles = cache.get(cache_key)
        if not ws_titles:
            try:
                ws_titles = [ws.title for ws in spreadsheet.worksheets()]
                cache.set(cache_key, ws_titles, timeout=300)
            except Exception as exc:
                logger.warning("Worksheet nomlarini olishda xatolik: %s", exc)
                ws_titles = ["List2", "Guruhlar"]

        payroll_title = None
        for name in ["list2", "xodimlar maoshi", "ish haqi"]:
            for t in ws_titles:
                if t.strip().lower() == name:
                    payroll_title = t
                    break
            if payroll_title:
                break

        if not payroll_title:
            payroll_title = "List2"

        guruhlar_title = None
        for t in ws_titles:
            if t.strip().lower() == "guruhlar":
                guruhlar_title = t
                break
        if not guruhlar_title:
            guruhlar_title = "Guruhlar"

        ranges_to_fetch = [payroll_title, guruhlar_title]

        try:
            batch_resp = spreadsheet.values_batch_get(ranges_to_fetch)
        except Exception as exc:
            raise ValidationError(f"Google Sheet batch read xatosi (ID: {self.sheet_id}): {exc}") from exc

        value_ranges = batch_resp.get("valueRanges", [])
        raw_payroll = value_ranges[0].get("values", []) if len(value_ranges) > 0 else []
        raw_guruhlar = value_ranges[1].get("values", []) if len(value_ranges) > 1 else []

        import hashlib
        raw_payroll_str = json.dumps({"payroll": raw_payroll, "guruhlar": raw_guruhlar}, sort_keys=True)
        self.last_payroll_hash = hashlib.sha256(raw_payroll_str.encode("utf-8")).hexdigest()

        payroll = self._parse_payroll(raw_payroll, sheet_title=payroll_title)
        groups_summary = self._parse_groups(raw_guruhlar, payroll_dtos=payroll)

        self.groups_summary = groups_summary
        return payroll, groups_summary

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

        # Check candidate payroll worksheets: 'list2' prioritized first, then 'xodimlar maoshi', 'ish haqi'
        payroll_candidates: list[gspread.Worksheet] = []
        for name in ["list2", "xodimlar maoshi", "ish haqi"]:
            ws = worksheets.get(name)
            if ws and ws not in payroll_candidates:
                payroll_candidates.append(ws)
                break

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
        name_to_id_map = {p.employee_name.strip().lower(): p.employee_id for p in payroll if p.employee_name}

        orders = self._parse_orders(worksheets["list1"], valid_employee_ids=valid_employee_ids, name_to_id_map=name_to_id_map)

        if not orders:
            raise ValidationError("List1 varog'idan birorta ham buyurtma o'qilmadi.")

        ws_guruhlar = worksheets.get("guruhlar")
        groups_summary: list[GroupSummaryDTO] = []
        if ws_guruhlar:
            try:
                groups_summary = self._parse_groups(ws_guruhlar, payroll_dtos=payroll)
            except Exception as exc:
                logger.warning("Guruhlar varag'ini tahlil qilishda xatolik: %s", exc)
        else:
            logger.warning("Google Sheet'da 'Guruhlar' varog'i topilmadi.")

        self.groups_summary = groups_summary

        import hashlib
        orders_payload = [(r.order_id, r.employee_id, r.status, str(r.sale_amount)) for r in orders]
        self.last_orders_hash = hashlib.sha256(json.dumps(orders_payload, sort_keys=True).encode("utf-8")).hexdigest()

        return orders, payroll


    def _parse_orders(
        self,
        worksheet: gspread.Worksheet,
        valid_employee_ids: set[str] | None = None,
        name_to_id_map: dict[str, str] | None = None,
    ) -> list[OrderDTO]:

        if isinstance(worksheet, list):
            raw_rows = worksheet
        else:
            raw_rows = worksheet.get_all_values(combine_merged_cells=True)
        if not raw_rows:
            raise ValidationError("List1 varog'i bo'sh.")

        name_map: dict[str, str] = {}
        if name_to_id_map:
            name_map = {k.strip().lower(): v for k, v in name_to_id_map.items() if k}

        try:
            from apps.employees.models import Employee
            for emp in Employee.objects.all():
                if emp.full_name and emp.full_name.strip().lower() not in name_map:
                    name_map[emp.full_name.strip().lower()] = emp.employee_id
        except Exception:
            pass

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

        id_candidates = ["ID(xodim)", "ID (xodim)", "ID", "Tabel raqami", "User ID", "Id", "id"]
        id_idx = self._find_single_column_index(headings, candidates=id_candidates, name="ID", required=False)
        ord_idx = self._find_single_column_index(headings, candidates=["№", "Zakaz №", "Order ID", "Номер", "No", "Nomer"], name="№", required=False)
        name_idx = self._find_single_column_index(headings, candidates=["Ответственный(VLOOKUP)", "Ответственный (VLOOKUP)", "Ответственный", "Xodim", "Menejer", "Operator", "ФИО", "FISH", "XODIMLAR ISMLARI", "Xodim ismi"], name="Ответственный", required=False)

        if id_idx is None and name_idx is not None and name_idx > 0:
            candidate_id_idx = name_idx - 1
            logger.warning(
                "ID sarlavhasi topilmadi (exact candidate match bo'lmadi). Strukturaviy fallback bo'yicha 'Ответственный' (indeks %s) dan oldingi %s-ustun tanlanmoqda. Sarlavhalar: %s",
                name_idx,
                candidate_id_idx,
                headings,
            )
            if self._validate_id_column(raw_rows, header_row_idx, candidate_id_idx):
                id_idx = candidate_id_idx

        if id_idx is None:
            raise ValidationError(f"Ustun topilmadi ('ID'): mos nomlar {id_candidates}")
        amount_idx = self._find_single_column_index(headings, candidates=["Сумма", "Summa", "Narxi", "Qiymati", "Summasi", "Obshiy summa"], name="Сумма", required=False)
        date_idx = self._find_single_column_index(headings, candidates=["Дата Заказа", "Дата", "Sana", "Zakaz sanasi", "Sana/vaqt"], name="Дата Заказа", required=False)
        status_idx = self._find_single_column_index(headings, candidates=["статус", "Статус", "Status", "Holat", "Holati"], name="статус", required=False)

        # Find group index: check candidates "Bo'lim", "Guruhi", "Guruh", etc.
        group_idx = self._find_single_column_index(
            headings,
            candidates=["Bo'lim", "Guruhi", "Guruh", "Bo'lim ", "Guruhlar", "Guruh nomi", "Bo'lim nomi", " ", "  "],
            name="guruh",
            required=False,
        )

        source_candidates = ["Столбец 2", "Контакт", "Источник", "manba", "Manba"]
        source_idx = self._find_single_column_index(headings, candidates=source_candidates, name="manba", required=False)

        client_idx = self._find_single_column_index(
            headings,
            candidates=["Ф.И.О.", "ФИО клиента", "Mijoz F.I.O", "Mijoz ismi", "Mijoz FIO", "Ф.И.О", "ФИО", "Ф. И. О.", "ФИО Клиента", "Клиент"],
            name="client_name",
            required=False,
            exact_only=False,
        )
        product_idx = self._find_single_column_index(
            headings,
            candidates=["Товар1", "Товар 1", "Товар", "Mahsulot1", "Mahsulot", "Tovar1", "Tovar"],
            name="product_name",
            required=False,
            exact_only=False,
        )
        qty_idx = product_idx + 1 if (product_idx is not None and product_idx + 1 < len(headings)) else None

        product_idx_2 = self._find_single_column_index(
            headings,
            candidates=["Товар2", "Товар 2", "Mahsulot2", "Tovar2"],
            name="product_name_2",
            required=False,
            exact_only=False,
        )
        qty_idx_2 = product_idx_2 + 1 if (product_idx_2 is not None and product_idx_2 + 1 < len(headings)) else None

        cleaned_order_map = self._check_column_collisions({
            "ID": id_idx,
            "№": ord_idx,
            "Ответственный": name_idx,
            "Сумма": amount_idx,
            "Дата Заказа": date_idx,
            "статус": status_idx,
            "guruh": group_idx,
            "manba": source_idx,
            "client_name": client_idx,
            "product_name": product_idx,
            "quantity": qty_idx,
            "product_name_2": product_idx_2,
            "quantity_2": qty_idx_2,
        })
        id_idx = cleaned_order_map["ID"]
        ord_idx = cleaned_order_map["№"]
        name_idx = cleaned_order_map["Ответственный"]
        amount_idx = cleaned_order_map["Сумма"]
        date_idx = cleaned_order_map["Дата Заказа"]
        status_idx = cleaned_order_map["статус"]
        group_idx = cleaned_order_map["guruh"]
        source_idx = cleaned_order_map["manba"]
        client_idx = cleaned_order_map["client_name"]
        product_idx = cleaned_order_map["product_name"]
        qty_idx = cleaned_order_map["quantity"]
        product_idx_2 = cleaned_order_map["product_name_2"]
        qty_idx_2 = cleaned_order_map["quantity_2"]

        logger.info(
            "List1 ustunlar: client=%s, product=%s, qty=%s, product2=%s, qty2=%s",
            client_idx,
            product_idx,
            qty_idx,
            product_idx_2,
            qty_idx_2,
        )

        if None in (client_idx, product_idx, qty_idx, product_idx_2, qty_idx_2):
            logger.warning(
                "List1 ba'zi ixtiyoriy ustunlar topilmadi (client=%s, product=%s, qty=%s, product2=%s, qty2=%s) | Full headings: %s",
                client_idx,
                product_idx,
                qty_idx,
                product_idx_2,
                qty_idx_2,
                headings,
            )

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
            "client_name": client_idx,
            "product_name": product_idx,
            "quantity": qty_idx,
            "product_name_2": product_idx_2,
            "quantity_2": qty_idx_2,
        }

        logger.info(
            "List1 sarlavha indeksi: %s | Ustunlar: ID=%s, №=%s, Xodim=%s, Summa=%s, Sana=%s, Status=%s, Guruh=%s, Manba=%s, Client=%s, Product=%s, Qty=%s",
            header_row_idx,
            id_idx,
            ord_idx,
            name_idx,
            amount_idx,
            date_idx,
            status_idx,
            group_idx,
            source_idx,
            client_idx,
            product_idx,
            qty_idx,
        )

        self.last_raw_list1_rows = raw_rows
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
        unrecognized_groups_count = Counter()
        unrecognized_statuses_count = Counter()
        unrecognized_statuses_sum = Decimal("0.00")
        seen_order_ids: dict[str, int] = {}
        duplicate_orders_count = 0
        duplicate_orders_sum = Decimal("0.00")

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

            mapped_id = name_map.get(raw_emp_name.strip().lower()) if raw_emp_name else None
            names_match = (
                name_idx is not None
                and last_seen_emp_name is not None
                and bool(raw_emp_name)
                and raw_emp_name.lower() == last_seen_emp_name.lower()
            )
            is_name_error = self._is_sheet_error(raw_emp_name) or "topilmadi" in raw_emp_name.lower()

            # Secondary check: if employee ID is empty and row is an unmapped/error template or lacks order content, treat as empty template row
            if not id_val and (not raw_emp_name or is_name_error or (not has_meaningful_content and not mapped_id and not names_match)):
                empty_rows_skipped += 1
                continue

            emp_id: str | None = None
            if id_val:
                try:
                    emp_id = normalize_employee_id(id_val)
                    last_seen_emp_id = emp_id
                    if raw_emp_name:
                        last_seen_emp_name = raw_emp_name
                        name_map[raw_emp_name.strip().lower()] = emp_id
                except PARSE_ERRORS as exc:
                    dropped_invalid_id += 1
                    reason = f"ID formati noto'g'ri: {exc}"
                    first_6 = [str(c).strip() for c in row[:6]]
                    dropped_rows.append({"row_idx": row_idx, "reason": reason, "raw_cells": first_6, "row_data": row})
                    logger.warning("List1 %s-qator tashlandi: %s | Birinchi 6 katak: %s", row_idx, reason, first_6)
                    continue
            else:
                if mapped_id:
                    emp_id = mapped_id
                    last_seen_emp_id = emp_id
                    if raw_emp_name:
                        last_seen_emp_name = raw_emp_name
                elif has_meaningful_content and SHEETS_FORWARD_FILL_EMPLOYEE_ID and last_seen_emp_id and names_match:
                    emp_id = last_seen_emp_id
                    logger.info(
                        "List1 %s-qator bo'sh ID forward-fill qilindi: %s (ism: %s)",
                        row_idx,
                        emp_id,
                        last_seen_emp_name,
                    )
                else:
                    dropped_empty_id += 1
                    reason = f"ID katakchasi bo'sh yoki ism mos kelmadi: '{raw_emp_name}'"
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

            raw_grp = self._get_cell(row, group_idx).strip() if group_idx is not None else ""
            if not raw_grp or "topilmadi" in raw_grp.lower():
                grp_code = "UNKNOWN"
                unrecognized_groups_count[raw_grp or "[BO'SH]"] += 1
            else:
                grp_code = raw_grp.upper()
                if grp_code not in ["A", "B", "C", "D", "E", "BAZA", "PERVICHKA", "UNKNOWN"]:
                    grp_code = "UNKNOWN"
                    unrecognized_groups_count[raw_grp] += 1

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

            stat_val, is_unrecognized_stat = self._parse_status(stat_raw)

            sale_amount: Decimal | None = None
            has_sheet_error = False
            raw_amount_cell = str(row[amount_idx]).strip() if amount_idx is not None and amount_idx < len(row) else ""
            if raw_amount_cell and self._is_sheet_error(raw_amount_cell):
                has_sheet_error = True
                sale_amount = None
            else:
                try:
                    sale_amount = self._parse_money(amount_str, sheet_name="List1", row_idx=row_idx)
                except PARSE_ERRORS as exc:
                    dropped_invalid_id += 1
                    reason = f"Summa xatosi: {exc}"
                    first_6 = [str(c).strip() for c in row[:6]]
                    dropped_rows.append({"row_idx": row_idx, "reason": reason, "raw_cells": first_6, "row_data": row})
                    logger.warning("List1 %s-qator tashlandi: %s | Birinchi 6 katak: %s", row_idx, reason, first_6)
                    continue

            if is_unrecognized_stat and stat_raw.strip():
                unrecognized_statuses_count[stat_raw.strip()] += 1
                if sale_amount:
                    unrecognized_statuses_sum += sale_amount

            src_raw_cell = self._get_cell(row, source_idx) if source_idx is not None else ""
            src_val, unrecognized_src = self._normalize_source(src_raw_cell)
            if unrecognized_src:
                unrecognized_sources_count[unrecognized_src] += 1

            client_name = self._get_cell(row, client_idx).strip() if client_idx is not None else ""
            product_name = self._get_cell(row, product_idx).strip() if product_idx is not None else ""
            raw_qty = self._get_cell(row, qty_idx) if qty_idx is not None else ""
            quantity: int | None = None
            if raw_qty:
                try:
                    val_flt = float(raw_qty.replace(",", "."))
                    quantity = int(val_flt)
                except Exception:
                    quantity = None

            product_name_2 = self._get_cell(row, product_idx_2).strip() if product_idx_2 is not None else ""
            raw_qty_2 = self._get_cell(row, qty_idx_2) if qty_idx_2 is not None else ""
            quantity_2: int | None = None
            if raw_qty_2:
                try:
                    val_flt_2 = float(raw_qty_2.replace(",", "."))
                    quantity_2 = int(val_flt_2)
                except Exception:
                    quantity_2 = None

            try:
                clean_ord = normalize_order_id(ord_raw)
                base_ord_id = f"{ordered_at:%Y%m}_{emp_id}_{clean_ord}"
                if base_ord_id in seen_order_ids:
                    seen_order_ids[base_ord_id] += 1
                    ord_id = f"{base_ord_id}_dup{seen_order_ids[base_ord_id]}"
                    duplicate_orders_count += 1
                    if sale_amount:
                        duplicate_orders_sum += sale_amount
                    logger.warning(
                        "List1 %s-qator: Dublikat № zakaz raqami '%s' aniqlandi (summa: %s). Noyob ID saqlandi: '%s'",
                        row_idx,
                        base_ord_id,
                        sale_amount,
                        ord_id,
                    )
                else:
                    seen_order_ids[base_ord_id] = 1
                    ord_id = base_ord_id
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
                    sale_amount=sale_amount,
                    ordered_at=ordered_at,
                    has_sheet_error=has_sheet_error,
                    client_name=client_name,
                    product_name=product_name,
                    quantity=quantity,
                    product_name_2=product_name_2,
                    quantity_2=quantity_2,
                )
            )
            parsed_rows_count += 1

        self.last_unrecognized_statuses = unrecognized_statuses_count
        self.last_unrecognized_statuses_sum = unrecognized_statuses_sum
        self.last_duplicate_orders_count = duplicate_orders_count
        self.last_duplicate_orders_sum = duplicate_orders_sum

        if unrecognized_sources_count:
            logger.debug("List1 noma'lum manba (source) qiymatlari agregatsiyasi: %s", dict(unrecognized_sources_count))
        if unrecognized_groups_count:
            logger.debug("List1 noma'lum guruh (Bo'lim) qiymatlari agregatsiyasi: %s", dict(unrecognized_groups_count))

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


    def _parse_payroll(self, worksheet_or_rows: gspread.Worksheet | list[list[Any]], sheet_title: str = "List2") -> list[PayrollDTO]:
        if isinstance(worksheet_or_rows, list):
            raw_rows = worksheet_or_rows
            title = sheet_title
        else:
            raw_rows = worksheet_or_rows.get_all_values(combine_merged_cells=True)
            title = worksheet_or_rows.title

        if not raw_rows:
            raise ValidationError(f"'{title}' varog'i bo'sh.")

        # Locate header row dynamically in the first 15 rows: require strict matching of essential columns
        def _norm(s: object) -> str:
            return re.sub(r"[\'\’\‘\ʼ\`\s\.\_\-]+", "", str(s or "").strip().lower())

        id_norms = {_norm(x) for x in ["Tabel raqami", "ID", "Табельный номер", "ID №", "ИД"]}
        name_norms = {_norm(x) for x in ["FISH", "XODIMLAR ISMLARI", "Xodim ismi", "Xodim", "Оператор", "ФИО", "Сотрудник"]}
        fin_norms = {_norm(x) for x in [
            "Uspeshka summasi", "Успешка суммаси", "Uspeshka", "Успешка summasi", "Успешка",
            "Umumiy zakaz summasi", "Общая сумма", "Jami summa", "Jami zakaz summasi", "Первичный Заказ", "База"
        ]}

        header_row_idx = None
        for i, row in enumerate(raw_rows[:15]):
            row_norms = {_norm(c) for c in row if c}
            if bool(row_norms & id_norms) and bool(row_norms & name_norms) and bool(row_norms & fin_norms):
                header_row_idx = i
                break

        if header_row_idx is None:
            for i, row in enumerate(raw_rows[:15]):
                row_norms = {_norm(c) for c in row if c}
                if bool(row_norms & id_norms) and bool(row_norms & name_norms):
                    header_row_idx = i
                    break

        if header_row_idx is None:
            raise ValidationError(f"'{title}' varog'ida sarlavha qatori (ID, FISH/Xodim va Uspeshka/Umumiy zakaz ustunlari) topilmadi.")

        headings = raw_rows[header_row_idx]

        id_candidates = ["Tabel raqami", "ID", "Табельный номер", "ID №", "ИД"]
        name_candidates = ["FISH", "XODIMLAR ISMLARI", "Xodim ismi", "Xodim", "Оператор", "ФИО", "Сотрудник"]

        id_idx = self._find_single_column_index(headings, candidates=id_candidates, name="ID", required=False)
        name_idx = self._find_single_column_index(headings, candidates=name_candidates, name="xodim ismi", required=False)

        if id_idx is None and name_idx is not None and name_idx > 0:
            candidate_id_idx = name_idx - 1
            logger.warning(
                "ID sarlavhasi topilmadi (exact candidate match bo'lmadi). Strukturaviy fallback bo'yicha 'xodim ismi' (indeks %s) dan oldingi %s-ustun tanlanmoqda. Sarlavhalar: %s",
                name_idx,
                candidate_id_idx,
                headings,
            )
            if self._validate_id_column(raw_rows, header_row_idx, candidate_id_idx):
                id_idx = candidate_id_idx

        if id_idx is None:
            raise ValidationError(f"'{title}' varog'ida 'ID' ustuni topilmadi: mos nomlar {id_candidates}")

        if name_idx is None:
            raise ValidationError(f"'{title}' varog'ida 'xodim ismi' ('FISH'/'XODIM') ustuni topilmadi: mos nomlar {name_candidates}")

        group_idx = self._find_single_column_index(
            headings,
            candidates=["Bo'lim", "Guruhi", "Guruh", "Bo'lim ", "Guruhlar", "Guruh nomi", "Bo'lim nomi", "Группа", "Отдел"],
            name="guruh",
            required=False,
        )
        salary_idx = self._find_single_column_index(
            headings,
            candidates=["Ish haqi", "Oylik ish haqi", "OYLIK MOASH", "OYLIK MAOSH", "Oylik maosh", "Oylik maoshi 12%", "Oylik", "Maosh", "Зарплата", "Оклад"],
            name="ish haqi",
            required=False,
        )

        total_sales_idx = self._find_single_column_index(
            headings,
            candidates=["Umumiy zakaz summasi", "Общая сумма", "Jami summa", "Jami zakaz summasi", "Umumiy summa", "Общая сумма заказов"],
            name="total_sales",
            required=False,
        )
        perv_sales_idx = self._find_single_column_index(
            headings,
            candidates=["Первичный Заказ", "Первичка", "Pervichka", "Pervichniy zakaz"],
            name="perv_sales",
            required=False,
        )
        baza_sales_idx = self._find_single_column_index(
            headings,
            candidates=["База", "Baza"],
            name="baza_sales",
            required=False,
        )
        otkaz_sales_idx = self._find_single_column_index(
            headings,
            candidates=["Otkaz", "Отказ"],
            name="otkaz_sales",
            required=False,
        )
        v_proc_sales_idx = self._find_single_column_index(
            headings,
            candidates=["В процесс", "В процессе", "V jarayonda", "Jarayonda"],
            name="v_proc_sales",
            required=False,
        )
        upakovka_idx = self._find_single_column_index(
            headings,
            candidates=["Upakovka soni", "Upakovka", "Упаковка"],
            name="upakovka",
            required=False,
        )
        conv_idx = self._find_single_column_index(
            headings,
            candidates=["Konversiya", "Конверсия"],
            name="conversion",
            required=False,
        )
        real_conv_idx = self._find_single_column_index(
            headings,
            candidates=["Real konversiya", "Реальная конверсия"],
            name="real_conversion",
            required=False,
        )

        successful_sales_idx = self._find_single_column_index(
            headings,
            candidates=["Uspeshka summasi", "Успешка суммаси", "Uspeshka", "Успешка summasi", "Успешка", "Успешные заказы", "Успешка сумма"],
            name="successful_sales",
            required=False,
            exact_only=True,
        )

        if successful_sales_idx is None and total_sales_idx is None and (perv_sales_idx is None or baza_sales_idx is None):
            raise ValidationError(
                f"'{title}' varog'ida muhim moliyaviy ustunlar ('Uspeshka summasi' yoki 'Umumiy zakaz summasi') topilmadi."
            )

        salary_1_15_idx = self._find_single_column_index(
            headings,
            candidates=[
                "1-15 kunlik ish haqi",
                "1-15 ish haqi",
                "1-15 oylik",
                "1-15 kunlik oylik",
                "1-15 kunlik",
                "1-15",
                "Ish haqi 1-15",
                "Oylik 1-15",
                "1-15 (12%)",
                "1-15 oylik (12%)",
                "1-15 kun",
                "1-15 ish haqi 12%",
                "1-15 oylik ish haqi",
            ],
            name="salary_1_15",
            required=False,
        )

        salary_16_31_idx = self._find_single_column_index(
            headings,
            candidates=[
                "16-31 kunlik ish haqi",
                "16-31 ish haqi",
                "16-31 oylik",
                "16-31 kunlik oylik",
                "16-31 kunlik",
                "16-31",
                "Ish haqi 16-31",
                "Oylik 16-31",
                "16-31 (12%)",
                "16-31 oylik (12%)",
                "16-31 kun",
                "16-oxiri",
                "16-30",
                "16-30 kunlik",
                "16-31 ish haqi 12%",
                "16-31 oylik ish haqi",
            ],
            name="salary_16_31",
            required=False,
        )

        cleaned_payroll_map = self._check_column_collisions({
            "ID": id_idx,
            "xodim ismi": name_idx,
            "guruh": group_idx,
            "ish haqi": salary_idx,
            "total_sales": total_sales_idx,
            "perv_sales": perv_sales_idx,
            "baza_sales": baza_sales_idx,
            "otkaz_sales": otkaz_sales_idx,
            "v_proc_sales": v_proc_sales_idx,
            "upakovka": upakovka_idx,
            "conversion": conv_idx,
            "real_conversion": real_conv_idx,
            "successful_sales": successful_sales_idx,
            "salary_1_15": salary_1_15_idx,
            "salary_16_31": salary_16_31_idx,
        })
        id_idx = cleaned_payroll_map["ID"]
        name_idx = cleaned_payroll_map["xodim ismi"]
        group_idx = cleaned_payroll_map["guruh"]
        salary_idx = cleaned_payroll_map["ish haqi"]
        total_sales_idx = cleaned_payroll_map["total_sales"]
        perv_sales_idx = cleaned_payroll_map["perv_sales"]
        baza_sales_idx = cleaned_payroll_map["baza_sales"]
        otkaz_sales_idx = cleaned_payroll_map["otkaz_sales"]
        v_proc_sales_idx = cleaned_payroll_map["v_proc_sales"]
        upakovka_idx = cleaned_payroll_map["upakovka"]
        conv_idx = cleaned_payroll_map["conversion"]
        real_conv_idx = cleaned_payroll_map["real_conversion"]
        successful_sales_idx = cleaned_payroll_map["successful_sales"]
        salary_1_15_idx = cleaned_payroll_map["salary_1_15"]
        salary_16_31_idx = cleaned_payroll_map["salary_16_31"]

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
                raw_grp = self._get_cell(row, group_idx).strip() if group_idx is not None else ""
                grp_code = raw_grp.upper() if raw_grp else "UNKNOWN"
                salary_str = self._get_cell(row, salary_idx) if salary_idx is not None else ""
                salary = self._parse_money(salary_str) if salary_str else Decimal("0.00")

                summary: dict[str, object] = {}

                def _process_payroll_col(col_idx: int | None, col_name: str, key_name: str, parser_fn):
                    if col_idx is not None and col_idx < len(row):
                        raw_val = str(row[col_idx]).strip()
                        if raw_val and not self._is_sheet_error(raw_val):
                            try:
                                res = parser_fn(raw_val)
                                if res is not None:
                                    summary[key_name] = res
                            except Exception:
                                pass

                # Salary processing
                salary = Decimal("0.00")
                if salary_idx is not None and salary_idx < len(row):
                    raw_sal = str(row[salary_idx]).strip()
                    if raw_sal and not self._is_sheet_error(raw_sal):
                        try:
                            salary = self._parse_money(raw_sal, sheet_name=title, row_idx=row_idx)
                            summary["earned_salary"] = str(salary)
                        except Exception:
                            pass

                _process_payroll_col(total_sales_idx, "Umumiy zakaz summasi", "total_sales", lambda v: str(self._parse_money(v, sheet_name=title, row_idx=row_idx)))
                _process_payroll_col(successful_sales_idx, "Uspeshka summasi", "successful_sales", lambda v: str(self._parse_money(v, sheet_name=title, row_idx=row_idx)))
                _process_payroll_col(perv_sales_idx, "Первичный Заказ", "perv_sales", lambda v: str(self._parse_money(v, sheet_name=title, row_idx=row_idx)))
                _process_payroll_col(baza_sales_idx, "База", "baza_sales", lambda v: str(self._parse_money(v, sheet_name=title, row_idx=row_idx)))
                _process_payroll_col(otkaz_sales_idx, "Otkaz", "otkaz_sales", lambda v: str(self._parse_money(v, sheet_name=title, row_idx=row_idx)))
                _process_payroll_col(v_proc_sales_idx, "В процесс", "v_proc_sales", lambda v: str(self._parse_money(v, sheet_name=title, row_idx=row_idx)))
                _process_payroll_col(upakovka_idx, "Upakovka soni", "successful_orders", lambda v: int(float(v.replace(",", "."))))
                _process_payroll_col(salary_1_15_idx, "1-15 kunlik ish haqi", "earned_salary_1_15", lambda v: str(self._parse_money(v, sheet_name=title, row_idx=row_idx)))
                _process_payroll_col(salary_16_31_idx, "16-31 kunlik ish haqi", "earned_salary_16_31", lambda v: str(self._parse_money(v, sheet_name=title, row_idx=row_idx)))

                def _parse_conv(v: str) -> float | None:
                    raw_c = v.replace("%", "").replace(",", ".").strip()
                    val_dec = Decimal(raw_c)
                    return float(val_dec / 100) if float(val_dec) > 1 else float(val_dec)

                _process_payroll_col(conv_idx, "Konversiya", "conversion_rate", _parse_conv)
                _process_payroll_col(real_conv_idx, "Real konversiya", "real_conversion_rate", _parse_conv)

                # Fallback: If successful_sales is missing from explicit column, derive from perv_sales + baza_sales
                if "successful_sales" not in summary:
                    if perv_sales_idx is not None and baza_sales_idx is not None:
                        if perv_sales_idx < len(row) and baza_sales_idx < len(row):
                            raw_perv = str(row[perv_sales_idx]).strip()
                            raw_baza = str(row[baza_sales_idx]).strip()
                            if raw_perv and not self._is_sheet_error(raw_perv) and raw_baza and not self._is_sheet_error(raw_baza):
                                try:
                                    perv_m = self._parse_money(raw_perv, sheet_name=title, row_idx=row_idx)
                                    baza_m = self._parse_money(raw_baza, sheet_name=title, row_idx=row_idx)
                                    uspeshka_derived = perv_m + baza_m
                                    summary["successful_sales"] = str(uspeshka_derived)
                                    logger.info(
                                        "Payroll '%s' %s-qator uchun 'successful_sales' perv+baza orqali hisoblandi: %s + %s = %s",
                                        title,
                                        row_idx,
                                        perv_m,
                                        baza_m,
                                        uspeshka_derived,
                                    )
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
                logger.warning("Payroll varog'i '%s', %s-qator tahlil xatosi: %s", title, row_idx, exc)
                if not hasattr(self, "last_dropped_payroll_rows"):
                    self.last_dropped_payroll_rows = []
                self.last_dropped_payroll_rows.append(
                    {
                        "sheet_title": title,
                        "row_idx": row_idx,
                        "reason": str(exc),
                        "row_data": row,
                    }
                )
                continue


        return payroll


    def _parse_groups(
        self,
        worksheet_or_rows: gspread.Worksheet | list[list[Any]],
        valid_group_codes: set[str] | list[str] | None = None,
        payroll_dtos: list[PayrollDTO] | None = None,
    ) -> list[GroupSummaryDTO]:
        if isinstance(worksheet_or_rows, list):
            raw_rows = worksheet_or_rows
        else:
            raw_rows = worksheet_or_rows.get_all_values(combine_merged_cells=True)
        if not raw_rows:
            return []

        # 1. Try vertical format first if 'Guruh foydasi' or 'Guruh kodi' column exists in header
        header_row_idx = None
        for i, row in enumerate(raw_rows[:15]):
            row_clean = [str(c).strip().lower() for c in row]
            if "guruh foydasi" in row_clean or "guruh kodi" in row_clean:
                header_row_idx = i
                break

        if header_row_idx is not None:
            headings = raw_rows[header_row_idx]
            code_idx = self._find_single_column_index(headings, candidates=["Guruh kodi", "Guruh"], name="guruh kodi", required=False)
            profit_idx = self._find_single_column_index(headings, candidates=["Guruh foydasi", "Foyda"], name="guruh foydasi", required=False)
            bonus_idx = self._find_single_column_index(headings, candidates=["Rahbar bonusi"], name="rahbar bonusi", required=False)
            total_sales_idx = self._find_single_column_index(
                headings,
                candidates=[
                    "Guruh jami savdosi",
                    "Guruh savdosi",
                    "Jami savdo",
                    "Savdo summasi",
                    "Savdo",
                    "Umumiy savdo",
                    "Total sales",
                    "Jami zakaz summasi",
                    "Umumiy zakaz summasi",
                ],
                name="guruh jami savdosi",
                required=False,
            )

            if code_idx is not None and (profit_idx is not None or total_sales_idx is not None):
                groups: list[GroupSummaryDTO] = []
                for row in raw_rows[header_row_idx + 1:]:
                    if not any(str(cell).strip() for cell in row):
                        continue
                    grp_code = self._get_cell(row, code_idx).upper()
                    if not grp_code:
                        continue
                    profit = self._parse_money(self._get_cell(row, profit_idx)) if profit_idx is not None else Decimal("0.00")
                    bonus = self._parse_money(self._get_cell(row, bonus_idx)) if bonus_idx is not None else (profit * Decimal("0.02"))

                    total_sales = Decimal("0.00")
                    if total_sales_idx is not None:
                        total_sales = self._parse_money(self._get_cell(row, total_sales_idx))

                    # Fallback: if total_sales is missing/zero, sum employee total_sales for this group from payroll_dtos
                    if (total_sales == Decimal("0.00") or total_sales_idx is None) and payroll_dtos:
                        emp_sales_sum = Decimal("0.00")
                        for dto in payroll_dtos:
                            if dto.group_code and dto.group_code.strip().upper() == grp_code and dto.summary_data:
                                ts_str = dto.summary_data.get("total_sales")
                                if ts_str:
                                    try:
                                        emp_sales_sum += self._parse_money(ts_str)
                                    except Exception:
                                        pass
                        if emp_sales_sum > Decimal("0.00"):
                            total_sales = emp_sales_sum

                    groups.append(
                        GroupSummaryDTO(
                            group_code=grp_code,
                            group_total_sales=total_sales,
                            group_profit=profit,
                            leader_bonus=bonus,
                        )
                    )
                if groups:
                    return groups

        # 2. Horizontal layout parsing
        row0 = raw_rows[0] if raw_rows else []
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

        if valid_group_codes:
            allowed_codes = {str(c).strip().upper() for c in valid_group_codes if str(c).strip()}
        else:
            allowed_codes = {"A", "B", "C", "D", "E", "U", "BAZA", "OFICE", "PERVICHKA"}

        groups = []
        seen_codes: set[str] = set()
        for col_idx, cell_val in enumerate(row0):
            raw_val = str(cell_val or "").strip().upper()
            clean_code = re.sub(r"[\:\.\,\s]+", "", raw_val)

            if clean_code in allowed_codes and clean_code not in seen_codes:
                seen_codes.add(clean_code)
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
                        group_code=clean_code,
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
    def _check_column_collisions(resolved_indexes: dict[str, int | None]) -> dict[str, int | None]:
        """Verify that no two fields point to the exact same column index.

        If a collision occurs (two or more fields sharing the same non-None index),
        log an ERROR and set all colliding fields to None.
        """
        index_to_fields: dict[int, list[str]] = defaultdict(list)
        for field_name, idx in resolved_indexes.items():
            if idx is not None:
                index_to_fields[idx].append(field_name)

        cleaned = dict(resolved_indexes)
        for idx, field_names in index_to_fields.items():
            if len(field_names) > 1:
                logger.error(
                    "Ustun indekslarida to'qnashuv (collision) aniqlandi: %s maydonlari bitta %s-ustunga bog'langan! Barcha to'qnashgan maydonlar None ga o'tkazildi.",
                    field_names,
                    idx,
                )
                for f in field_names:
                    cleaned[f] = None

        return cleaned

    @staticmethod
    def _validate_id_column(raw_rows: list[list[Any]], header_row_idx: int, candidate_idx: int) -> bool:
        """Validate if candidate column contains valid employee IDs (^\d{4,32}$) in >=80% of sampled rows."""
        sample_size = 0
        valid_count = 0

        for row in raw_rows[header_row_idx + 1:]:
            if sample_size >= 50:
                break
            if not any(str(cell or "").strip() for cell in row):
                continue

            val = str(row[candidate_idx]).strip() if candidate_idx < len(row) else ""
            if not val or SheetsSource._is_sheet_error(val):
                continue

            sample_size += 1
            try:
                norm_id = normalize_employee_id(val)
                if re.match(r"^\d{4,32}$", norm_id):
                    valid_count += 1
            except Exception:
                pass

        ratio = (valid_count / sample_size) if sample_size > 0 else 0.0
        passed = sample_size > 0 and ratio >= 0.8

        if passed:
            logger.info(
                "ID ustuni strukturaviy fallback tekshiruvi MUVAFFAQIYATLI: sample_size=%s, valid_count=%s, ratio=%.2f, tanlangan_indeks=%s",
                sample_size,
                valid_count,
                ratio,
                candidate_idx,
            )
        else:
            logger.warning(
                "ID ustuni strukturaviy fallback tekshiruvi MUVAFFAQIYATSIZ: sample_size=%s, valid_count=%s, ratio=%.2f, tanlangan_indeks=%s rad etildi",
                sample_size,
                valid_count,
                ratio,
                candidate_idx,
            )

        return passed

    @staticmethod
    def _find_single_column_index(
        headings: list[str],
        candidates: list[str],
        name: str,
        required: bool = True,
        exact_only: bool = True,
    ) -> int | None:
        def _norm(s: object) -> str:
            return re.sub(r"[\'\’\‘\ʼ\`\s\.\_\-]+", "", str(s or "").strip().lower())

        for candidate in candidates:
            if candidate in (" ", "  "):
                for idx, col_name in enumerate(headings):
                    if str(col_name or "") == candidate:
                        logger.info("Sheet ustun topildi (bitta probel sarlavhasi '%s'): indeks %s", name, idx)
                        return idx

            cand_norm = _norm(candidate)
            if not cand_norm:
                continue

            for idx, col_name in enumerate(headings):
                col_name_str = str(col_name or "").strip()
                col_norm = _norm(col_name_str)
                if col_norm and col_norm == cand_norm:
                    if name not in ("conversion", "real_conversion"):
                        col_lower = col_name_str.lower()
                        if any(p in col_lower for p in ["foiz", "фоиз", "%"]):
                            logger.warning(
                                "Ustun sarlavhasida foiz ko'rsatkichi bo'lgani sababli rad etildi ('%s'): name='%s', idx=%s",
                                col_name_str,
                                name,
                                idx,
                            )
                            continue
                    logger.info("Sheet ustun topildi ('%s'): indeks %s ('%s')", name, idx, col_name_str)
                    return idx

        if not exact_only:
            for candidate in candidates:
                cand_norm = _norm(candidate)
                if not cand_norm:
                    continue
                for idx, col_name in enumerate(headings):
                    col_name_str = str(col_name or "").strip()
                    col_norm = _norm(col_name_str)
                    if col_norm and (cand_norm in col_norm or col_norm in cand_norm):
                        if name not in ("conversion", "real_conversion"):
                            col_lower = col_name_str.lower()
                            if any(p in col_lower for p in ["foiz", "фоиз", "%"]):
                                logger.warning(
                                    "Ustun sarlavhasida foiz ko'rsatkichi bo'lgani sababli rad etildi ('%s'): name='%s', idx=%s",
                                    col_name_str,
                                    name,
                                    idx,
                                )
                                continue
                        logger.info("Sheet ustun qisman moslik bilan topildi ('%s'): indeks %s ('%s')", name, idx, col_name_str)
                        return idx

        if required:
            raise ValidationError(f"Ustun topilmadi ('{name}'): mos nomlar {candidates}")
        logger.warning("Sheet ustun topilmadi ('%s'): qidirilgan nomlar %s | Natija: None", name, candidates)
        return None

    @staticmethod
    def _is_sheet_error(val: object) -> bool:
        if val is None:
            return False
        s = str(val).strip().upper()
        return s in SHEET_ERROR_LITERALS

    @staticmethod
    def _get_cell(row: list[str], idx: int | None) -> str:
        if idx is None or idx >= len(row):
            return ""
        val = str(row[idx]).strip()
        if SheetsSource._is_sheet_error(val):
            return ""
        return val

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
        if not s or SheetsSource._is_sheet_error(s):
            return Decimal("0.00")
        clean = s.replace(" ", "").replace("\xa0", "").replace("$", "").replace("so'm", "").replace("som", "").strip()
        if not clean or SheetsSource._is_sheet_error(clean):
            return Decimal("0.00")

        if "," in clean and "." in clean:
            last_comma = clean.rfind(",")
            last_dot = clean.rfind(".")
            if last_dot > last_comma:
                clean = clean.replace(",", "")
            else:
                clean = clean.replace(".", "").replace(",", ".")
        elif "," in clean and "." not in clean:
            parts = clean.split(",")
            if len(parts) > 2:
                clean = clean.replace(",", "")
            elif len(parts) == 2:
                if len(parts[1]) == 3 and parts[1].isdigit():
                    clean = clean.replace(",", "")
                elif len(parts[1]) in (1, 2) and parts[0].isdigit():
                    clean = clean.replace(",", ".")
                else:
                    clean = clean.replace(",", "")
        elif "." in clean and "," not in clean:
            parts = clean.split(".")
            if len(parts) > 2:
                clean = clean.replace(".", "")
            elif len(parts) == 2:
                if len(parts[1]) == 3 and parts[1].isdigit():
                    clean = clean.replace(".", "")

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
    def _parse_status(val: str) -> tuple[str, bool]:
        if not val or not str(val).strip():
            return "pending", True
        raw = re.sub(r"[\.\,\:\s]+$", "", str(val).strip().lower()).strip()
        if raw in STATUS_MAP:
            return STATUS_MAP[raw], False
        if any(term in raw for term in ["отказ", "возврат", "otkaz", "bekor", "otmena"]):
            return "cancelled", False
        if any(term in raw for term in ["курьер", "kuryer", "достав", "dostav", "успеш", "uspesh", "оплач", "сдан", "topshir"]):
            return "successful", False
        if any(term in raw for term in ["процес", "ожидан", "protsess", "process", "jarayon", "kutilmoq"]):
            return "pending", False

        logger.warning("Noma'lum status matni uchradi ('%s'), 'pending' deb qabul qilindi", val)
        return "pending", True

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