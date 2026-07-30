from django.core.management.base import BaseCommand
from apps.imports.dto import normalize_employee_id
from apps.imports.sources.sheets import SheetsSource


class Command(BaseCommand):
    help = "Diagnose Google Sheets List1 parsing, showing dropped rows and column mappings without touching DB."

    def add_arguments(self, parser):
        parser.add_argument(
            "--employee-id",
            type=str,
            help="Filter diagnostics for a specific Employee ID (e.g. 0191)",
        )

    def handle(self, *args, **options):
        target_emp_id = None
        if options.get("employee_id"):
            try:
                target_emp_id = normalize_employee_id(options["employee_id"])
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"Invalid employee-id argument: {exc}"))
                return

        self.stdout.write(self.style.MIGRATE_HEADING("=== Google Sheets List1 Diagnostika ==="))

        source = SheetsSource()
        orders, payroll = source.read()

        header_idx = getattr(source, "last_header_row_idx", 0)
        headings = getattr(source, "last_headings", [])
        column_map = getattr(source, "last_column_indexes", {})

        self.stdout.write(f"\n📌 Sarlavha qatori indeksi: {header_idx}")
        self.stdout.write("📌 Ustunlar xaritasi:")
        for name, idx in column_map.items():
            val_str = f"Indeks {idx}" if idx is not None else "TOPILMADI"
            self.stdout.write(f"   • {name}: {val_str}")

        summary = getattr(source, "last_parse_summary", {})
        dropped_rows = getattr(source, "last_dropped_rows", [])

        self.stdout.write("\n📊 Parse Xulosasi:")
        self.stdout.write(f"   • Jami ma'lumot qatorlari: {summary.get('total_raw_rows', 0)}")
        self.stdout.write(f"   • Bo'sh qatorlar (o'tkazib yuborilgan): {summary.get('empty_rows_skipped', 0)}")
        self.stdout.write(f"   • Tashlangan qatorlar (xatolar): {summary.get('dropped_count', len(dropped_rows))}")
        self.stdout.write(f"   • Muvaffaqiyatli parse qilingan: {summary.get('parsed_rows_count', 0)}")


        dropped_payroll_rows = getattr(source, "last_dropped_payroll_rows", [])
        if dropped_payroll_rows:
            self.stdout.write(self.style.WARNING(f"\n⚠️ Tashlangan Payroll (List2) Qatorlari (Jami: {len(dropped_payroll_rows)}):"))
            for item in dropped_payroll_rows:
                title = item["sheet_title"]
                r_idx = item["row_idx"]
                reason = item["reason"]
                self.stdout.write(f"   Varoq: '{title}' | Qator #{r_idx} | Sabab: {reason}")

        if dropped_rows:
            self.stdout.write(self.style.WARNING(f"\n⚠️ Tashlangan Qatorlar Jadvali (Jami: {len(dropped_rows)}):"))
            for item in dropped_rows:
                r_idx = item["row_idx"]
                reason = item["reason"]
                cells = item["raw_cells"]
                self.stdout.write(f"   Qator #{r_idx} | Sabab: {reason} | Qiymatlar: {cells}")
        else:
            self.stdout.write(self.style.SUCCESS("\n✅ Birorta ham List1 buyurtma qatori tashlanmadi."))


        if target_emp_id:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== Xodim Diagnostikasi (ID: {target_emp_id}) ==="))
            emp_parsed_orders = [o for o in orders if o.employee_id == target_emp_id]
            
            # Count rows in dropped_rows matching target_emp_id (if ID cell was present or row_data matches)
            emp_dropped = []
            id_idx = column_map.get("ID")
            for item in dropped_rows:
                row_data = item.get("row_data", [])
                raw_id = row_data[id_idx] if (id_idx is not None and id_idx < len(row_data)) else ""
                try:
                    if raw_id and normalize_employee_id(raw_id) == target_emp_id:
                        emp_dropped.append(item)
                except Exception:
                    pass

            self.stdout.write(f"   • {target_emp_id} uchun parse bo'lgan zakazlar: {len(emp_parsed_orders)} ta")
            self.stdout.write(f"   • {target_emp_id} uchun tashlangan qatorlar: {len(emp_dropped)} ta")
            if emp_dropped:
                for item in emp_dropped:
                    self.stdout.write(f"     Qator #{item['row_idx']} | Sabab: {item['reason']} | {item['raw_cells']}")
