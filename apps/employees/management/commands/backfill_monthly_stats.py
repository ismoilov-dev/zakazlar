"""Management command to backfill Employee.summary_data into EmployeeMonthlyStat for a period."""

from datetime import date, datetime
from django.core.management.base import BaseCommand

from apps.employees.models import Employee, EmployeeMonthlyStat


class Command(BaseCommand):
    help = "Backfill current Employee.summary_data into EmployeeMonthlyStat for a period (e.g. 2026-06)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "period",
            type=str,
            help="Period in YYYY-MM format (e.g. 2026-06)",
        )

    def handle(self, *args, **options) -> None:
        period_str = options["period"].strip()
        try:
            dt = datetime.strptime(period_str, "%Y-%m")
            period_date = date(dt.year, dt.month, 1)
        except ValueError:
            self.stderr.write(self.style.ERROR("Noto'g'ri sana formati. Format YYYY-MM bo'lishi kerak (masalan: 2026-06)."))
            return

        created_count = 0
        updated_count = 0
        skipped_closed_count = 0

        employees = Employee.objects.filter(is_active=True).exclude(summary_data={})

        for emp in employees:
            stat, created = EmployeeMonthlyStat.objects.get_or_create(
                employee=emp,
                period=period_date,
                defaults={
                    "summary_data": emp.summary_data,
                    "source_spreadsheet_id": "backfill",
                },
            )
            if created:
                created_count += 1
            else:
                if stat.is_closed:
                    skipped_closed_count += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"Xodim {emp.employee_id} uchun {period_str} davri yopilgan (is_closed=True), o'tkazib yuborildi."
                        )
                    )
                else:
                    stat.summary_data = emp.summary_data
                    stat.save(update_fields=["summary_data"])
                    updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Backfill yakunlandi ({period_str}): {created_count} ta yangi yaratildi, {updated_count} ta yangilandi, {skipped_closed_count} ta yopilgan row o'tkazib yuborildi."
            )
        )
