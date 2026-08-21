"""Management command to diagnose sum mismatches between Google Sheets, parsed DTOs, DB sales, and statistics."""

from datetime import date
from decimal import Decimal
from typing import Any

from django.core.management.base import BaseCommand
from django.db.models import Sum
from django.utils import timezone

from apps.employees.models import Employee
from apps.imports.dto import normalize_employee_id
from apps.imports.models import SpreadsheetPeriod
from apps.imports.sources.sheets import SheetsSource
from apps.sales.models import Sale, SaleStatus
from apps.statistics.services.statistics import StatisticsService


class Command(BaseCommand):
    help = "Diagnose step-by-step sum mismatches between Google Sheets List1, parsed DTOs, DB Sales, and Statistics."

    def add_arguments(self, parser):
        parser.add_argument(
            "--employee-id",
            type=str,
            help="Filter diagnosis for a specific Employee ID (e.g. 0015 or 0191)",
        )
        parser.add_argument(
            "--month",
            type=str,
            help="Target month in YYYY-MM format (e.g. 2026-06 or 2026-08)",
        )

    def handle(self, *args, **options):
        target_emp_id = None
        if options.get("employee_id"):
            try:
                target_emp_id = normalize_employee_id(options["employee_id"])
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"Invalid --employee-id: {exc}"))
                return

        target_date = None
        if options.get("month"):
            try:
                parts = options["month"].strip().split("-")
                target_date = date(int(parts[0]), int(parts[1]), 1)
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"Invalid --month format (expected YYYY-MM): {exc}"))
                return

        self.stdout.write(self.style.MIGRATE_HEADING("=================================================="))
        self.stdout.write(self.style.MIGRATE_HEADING("   DIAGNOSE SUM MISMATCH — STEP-BY-STEP ANALYSIS   "))
        self.stdout.write(self.style.MIGRATE_HEADING("=================================================="))

        source = SheetsSource()
        orders, payroll = source.read()

        if target_date is None:
            active_sp = SpreadsheetPeriod.objects.filter(is_active=True).first()
            target_date = active_sp.period if active_sp else timezone.localtime().date()
        self.stdout.write(f"📌 Target Period: {target_date.strftime('%Y-%m')} (Active Sheet ID: {source.sheet_id})")
        if target_emp_id:
            self.stdout.write(f"📌 Employee Filter: {target_emp_id}")

        # 1. SHEETS LIST1 RAW ROWS ANALYSIS
        raw_rows = getattr(source, "last_raw_list1_rows", [])
        header_idx = getattr(source, "last_header_row_idx", 0)
        column_map = getattr(source, "last_column_indexes", {})
        amount_idx = column_map.get("Сумма")
        id_idx = column_map.get("ID")

        data_rows = raw_rows[header_idx + 1 :] if raw_rows else []
        raw_total_rows = 0
        raw_total_sum = Decimal("0")
        raw_rows_details = []

        for r_offset, r in enumerate(data_rows, start=header_idx + 2):
            if not any(str(cell or "").strip() for cell in r):
                continue

            emp_id_cell = ""
            if id_idx is not None and id_idx < len(r):
                emp_id_cell = str(r[id_idx] or "").strip()

            norm_id = None
            if emp_id_cell:
                try:
                    norm_id = normalize_employee_id(emp_id_cell)
                except Exception:
                    pass

            if target_emp_id and norm_id != target_emp_id:
                continue

            raw_total_rows += 1
            amt_str = str(r[amount_idx] or "").strip() if amount_idx is not None and amount_idx < len(r) else ""
            amt_val = Decimal("0")
            if amt_str and not source._is_sheet_error(amt_str):
                try:
                    amt_val = source._parse_money(amt_str)
                except Exception:
                    pass
            raw_total_sum += amt_val
            raw_rows_details.append({"row_idx": r_offset, "amount": amt_val, "raw_id": emp_id_cell, "norm_id": norm_id})

        self.stdout.write(f"\n1️⃣ Sheets List1 Xom Qatorlari:")
        self.stdout.write(f"   • Qatorlar soni: {raw_total_rows} ta")
        self.stdout.write(f"   • Jami SUM:      {raw_total_sum:,.2f} so'm")

        # 2. PARSED OrderDTO ANALYSIS
        filtered_orders = orders
        if target_emp_id:
            filtered_orders = [o for o in orders if o.employee_id == target_emp_id]

        parsed_dto_count = len(filtered_orders)
        parsed_dto_sum = sum((o.sale_amount or Decimal("0")) for o in filtered_orders)
        sheet_error_dto_count = sum(1 for o in filtered_orders if o.has_sheet_error)

        self.stdout.write(f"\n2️⃣ Parser'dan Chiqqan OrderDTO:")
        self.stdout.write(f"   • Qatorlar soni: {parsed_dto_count} ta")
        self.stdout.write(f"   • Jami SUM:      {parsed_dto_sum:,.2f} so'm")
        self.stdout.write(f"   • Sheet Error (#N/A) bo'lgan OrderDTO: {sheet_error_dto_count} ta")

        delta_1_2 = raw_total_sum - parsed_dto_sum
        self.stdout.write(self.style.WARNING(f"   ➡️ DELTA (Raw - Parsed DTO): {delta_1_2:,.2f} so'm"))

        # 3. DROPPED ROWS ANALYSIS
        dropped_rows = getattr(source, "last_dropped_rows", [])
        reasons_map: dict[str, dict[str, Any]] = {}

        for item in dropped_rows:
            r_idx = item.get("row_idx")
            reason = str(item.get("reason", "Noma'lum"))
            row_data = item.get("row_data", [])

            row_emp_id = None
            if id_idx is not None and id_idx < len(row_data):
                raw_id = str(row_data[id_idx] or "").strip()
                if raw_id:
                    try:
                        row_emp_id = normalize_employee_id(raw_id)
                    except Exception:
                        pass

            if target_emp_id and row_emp_id != target_emp_id:
                continue

            amt_val = Decimal("0")
            if amount_idx is not None and amount_idx < len(row_data):
                amt_str = str(row_data[amount_idx] or "").strip()
                if amt_str and not source._is_sheet_error(amt_str):
                    try:
                        amt_val = source._parse_money(amt_str)
                    except Exception:
                        pass

            # Group reason base category
            base_reason = reason.split(":")[0] if ":" in reason else reason
            if base_reason not in reasons_map:
                reasons_map[base_reason] = {"count": 0, "sum": Decimal("0"), "examples": []}

            reasons_map[base_reason]["count"] += 1
            reasons_map[base_reason]["sum"] += amt_val
            if len(reasons_map[base_reason]["examples"]) < 3:
                reasons_map[base_reason]["examples"].append(f"Qator #{r_idx} ({amt_val:,.0f} so'm)")

        total_dropped_count = sum(info["count"] for info in reasons_map.values())
        total_dropped_sum = sum(info["sum"] for info in reasons_map.values())

        self.stdout.write(f"\n3️⃣ Tashlangan Qatorlar (Dropped Rows):")
        self.stdout.write(f"   • Jami tashlangan qatorlar: {total_dropped_count} ta")
        self.stdout.write(f"   • Jami tashlangan SUM:      {total_dropped_sum:,.2f} so'm")

        if reasons_map:
            self.stdout.write("   📌 Sabablar bo'yicha taqsimot:")
            for reason, info in reasons_map.items():
                self.stdout.write(
                    f"      - '{reason}' -> {info['count']} qator, {info['sum']:,.2f} so'm | Miso: {', '.join(info['examples'])}"
                )

        # 4. DATABASE PERSISTED SALE RECORDS ANALYSIS (SQL Aggregation)
        db_qs = Sale.objects.filter(
            ordered_at__year=target_date.year,
            ordered_at__month=target_date.month,
        )
        if target_emp_id:
            db_qs = db_qs.filter(employee__employee_id=target_emp_id)

        db_sale_count = db_qs.count()
        db_sale_sum_agg = db_qs.aggregate(total=Sum("sale_amount")).get("total") or Decimal("0")
        db_successful_sum = (
            db_qs.filter(status=SaleStatus.SUCCESSFUL).aggregate(total=Sum("sale_amount")).get("total") or Decimal("0")
        )
        db_pending_sum = (
            db_qs.filter(status=SaleStatus.PENDING).aggregate(total=Sum("sale_amount")).get("total") or Decimal("0")
        )
        db_cancelled_sum = (
            db_qs.filter(status=SaleStatus.CANCELLED).aggregate(total=Sum("sale_amount")).get("total") or Decimal("0")
        )

        self.stdout.write(f"\n4️⃣ Bazaga Yozilgan Sale Yozuvlari (SQL Aggregation):")
        self.stdout.write(f"   • Qatorlar soni:                    {db_sale_count} ta")
        self.stdout.write(f"   • Sale aggregation (barcha status): {db_sale_sum_agg:,.2f} so'm")
        self.stdout.write(f"   • Sale aggregation (successful):   {db_successful_sum:,.2f} so'm")
        self.stdout.write(f"   • Sale aggregation (pending):      {db_pending_sum:,.2f} so'm")
        self.stdout.write(f"   • Sale aggregation (cancelled):    {db_cancelled_sum:,.2f} so'm")

        # 5. LIST2 SUMMARY_DATA vs SALE AGGREGATION COMPARISON
        if target_emp_id:
            emp = Employee.objects.filter(employee_id=target_emp_id).first()
            if emp:
                summary_data = emp.summary_data or {}
                list2_total_sales = Decimal(str(summary_data.get("total_sales", 0) or 0))
                delta_l2_all = list2_total_sales - db_sale_sum_agg
                delta_l2_succ = list2_total_sales - db_successful_sum

                self.stdout.write(f"\n5️⃣ Xodim ({emp.full_name}, ID: {target_emp_id}) bo'yicha MANBALAR SOLISHTIRISHI:")
                self.stdout.write(f"   • List2 summary_data['total_sales'] = {list2_total_sales:,.2f} so'm")
                self.stdout.write(f"   • Sale aggregation (barcha status)  = {db_sale_sum_agg:,.2f} so'm")
                self.stdout.write(f"   • Sale aggregation (successful)     = {db_successful_sum:,.2f} so'm")
                self.stdout.write(f"   • Sale aggregation (pending)        = {db_pending_sum:,.2f} so'm")
                self.stdout.write(f"   • Sale aggregation (cancelled)      = {db_cancelled_sum:,.2f} so'm")
                self.stdout.write(self.style.WARNING(f"   ➡️ DELTA (List2 - Sale All):        {delta_l2_all:,.2f} so'm"))
                self.stdout.write(self.style.WARNING(f"   ➡️ DELTA (List2 - Sale Successful): {delta_l2_succ:,.2f} so'm"))

        # 6. TELEGRAM BOT FORMATTING OUTPUT
        from apps.telegram_bot.services.formatting import card_text

        if target_emp_id:
            emp = Employee.objects.filter(employee_id=target_emp_id).first()
            if emp:
                card_res = card_text(
                    card_type="total_sales",
                    full_name=emp.full_name,
                    group_code=emp.group.code if emp.group else "A",
                    summary_data=emp.summary_data,
                    employee_id=emp.employee_id,
                    period_date=target_date,
                )
                self.stdout.write(f"\n6️⃣ Telegram Bot Card Formatting Result:")
                self.stdout.write(f"   {card_res.replace(chr(10), ' | ')}")

        self.stdout.write(self.style.MIGRATE_HEADING("\n=================================================="))
        self.stdout.write(self.style.MIGRATE_HEADING("               DIAGNOSIS COMPLETE                 "))
        self.stdout.write(self.style.MIGRATE_HEADING("=================================================="))
