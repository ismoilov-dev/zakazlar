"""Management command to restore EmployeeMonthlyStat snapshots from a historical Google Sheet workbook."""

from datetime import date, datetime

from django.core.management.base import BaseCommand, CommandError

from apps.employees.models import Employee
from apps.employees.repositories.monthly_stat import ClosedPeriodError, EmployeeMonthlyStatRepository
from apps.imports.models import SpreadsheetPeriod
from apps.imports.sources.sheets import SheetsSource


class Command(BaseCommand):
    help = "Restore EmployeeMonthlyStat snapshots from a historical workbook (List2)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "period",
            type=str,
            help="Target period in YYYY-MM format (e.g. 2026-06)",
        )
        parser.add_argument(
            "--spreadsheet-id",
            type=str,
            default="",
            help="Google Spreadsheet ID for the historical workbook",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            default=False,
            help="Force overwrite closed periods (is_closed=True)",
        )

    def handle(self, *args, **options) -> None:
        period_str = options["period"].strip()
        try:
            dt = datetime.strptime(period_str, "%Y-%m")
            target_period = date(dt.year, dt.month, 1)
        except ValueError:
            raise CommandError("Noto'g'ri sana formati. Format YYYY-MM bo'lishi kerak (masalan: 2026-06).")

        sheet_id = options.get("spreadsheet_id", "").strip()
        if not sheet_id:
            sp = SpreadsheetPeriod.objects.filter(period=target_period).first()
            if sp and sp.spreadsheet_id:
                sheet_id = sp.spreadsheet_id
            else:
                raise CommandError(f"{period_str} davri uchun --spreadsheet-id ko'rsatilmadi va DBda topilmadi.")

        self.stdout.write(f"Davr: {period_str} | Sheet ID: {sheet_id} o'qilmoqda...")

        try:
            source = SheetsSource(sheet_id=sheet_id)
            spreadsheet = source.client.open_by_key(source.sheet_id)
            worksheets = {ws.title.strip().lower(): ws for ws in spreadsheet.worksheets()}

            payroll_ws = None
            for candidate in ["list2", "xodimlar maoshi", "ish haqi"]:
                if candidate in worksheets:
                    payroll_ws = worksheets[candidate]
                    break

            if not payroll_ws:
                raise CommandError("Workbook'da List2 varog'i topilmadi.")

            payroll_dtos = source._parse_payroll(payroll_ws)
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(f"Google Sheet'dan ma'lumotlarni o'qishda xatolik: {exc}") from exc

        repo = EmployeeMonthlyStatRepository()
        restored_count = 0
        skipped_count = 0

        self.stdout.write("\n--- SOTUVCHILAR BO'YICHA O'ZGARISHLAR DIFF'I ---")

        for dto in payroll_dtos:
            emp = Employee.objects.filter(employee_id=dto.employee_id).first()
            if not emp:
                self.stdout.write(self.style.WARNING(f"Xodim {dto.employee_id} ({dto.employee_name}) DBda topilmadi, o'tkazib yuborildi."))
                continue

            stat = repo.model.objects.filter(employee=emp, period=target_period).first()
            before_data = stat.summary_data if stat else {}
            after_data = dto.summary_data or {}

            diffs = []
            all_keys = sorted(set(before_data.keys()) | set(after_data.keys()))
            for key in all_keys:
                v_before = str(before_data.get(key, ""))
                v_after = str(after_data.get(key, ""))
                if v_before != v_after:
                    diffs.append(f"    {key}: {v_before or 'N/A'} -> {v_after or 'N/A'}")

            self.stdout.write(f"[{emp.employee_id}] {emp.full_name}:")
            if diffs:
                for line in diffs:
                    self.stdout.write(line)
            else:
                self.stdout.write("    (O'zgarishlar yo'q)")

            try:
                repo.upsert_snapshot(
                    employee=emp,
                    period=target_period,
                    summary_data=after_data,
                    source_spreadsheet_id=sheet_id,
                    force=options["force"],
                )
                restored_count += 1
            except ClosedPeriodError:
                skipped_count += 1
                self.stdout.write(
                    self.style.WARNING(
                        "    ⚠️ YOPILGAN OY (is_closed=True) — --force ko'rsatilmagoni uchun rad etildi."
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nTiklash yakunlandi ({period_str}): {restored_count} ta snapshot tiklandi/yangilandi, {skipped_count} ta yopilgan row rad etildi."
            )
        )
