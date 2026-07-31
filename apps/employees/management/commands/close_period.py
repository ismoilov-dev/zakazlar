"""Management command to close all EmployeeMonthlyStat records for a period (e.g. 2026-06)."""

from datetime import date, datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.employees.models import EmployeeMonthlyStat


class Command(BaseCommand):
    help = "Close all EmployeeMonthlyStat records for a period (e.g. 2026-06)."

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

        qs = EmployeeMonthlyStat.objects.filter(period=period_date, is_closed=False)
        updated_count = qs.update(
            is_closed=True,
            closed_at=timezone.now(),
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"{period_str} davri uchun {updated_count} ta oylik statistika yopildi."
            )
        )
