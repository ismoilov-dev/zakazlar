"""Management command to recalculate group_total_sales for all SalesGroup instances."""

from decimal import Decimal
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.groups.models import SalesGroup
from apps.statistics.repositories.statistics import StatisticsRepository


class Command(BaseCommand):
    help = "Recalculate group_total_sales for all SalesGroup objects directly from DB Sale aggregations."

    def handle(self, *args, **options):
        stats_repo = StatisticsRepository()
        self.stdout.write("Guruhlar umumiy savdosi bazadagi zakazlardan qayta hisoblanmoqda...")
        for grp in SalesGroup.objects.all():
            db_tot = stats_repo.group_totals(grp.id)
            ts = db_tot.get("total_sales") or Decimal("0.00") if db_tot else Decimal("0.00")
            old_val = grp.group_total_sales
            grp.group_total_sales = ts
            grp.synced_at = timezone.now()
            grp.save(update_fields=["group_total_sales", "synced_at"])
            self.stdout.write(
                self.style.SUCCESS(f"✅ Guruh '{grp.code}' ({grp.name}): {old_val:,.2f} -> {ts:,.2f} so'm")
            )
