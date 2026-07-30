"""Management command to clean up old SyncLog records while preserving the latest successful sync."""

from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.imports.models import SyncLog, SyncStatus


class Command(BaseCommand):
    help = "Delete SyncLog records older than N days (default: 30), preserving the latest successful log regardless of age."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Number of days to keep SyncLog records for (default: 30).",
        )

    def handle(self, *args, **options) -> None:
        days = options["days"]
        cutoff = timezone.now() - timedelta(days=days)

        last_successful = SyncLog.get_last_successful()
        qs = SyncLog.objects.filter(started_at__lt=cutoff)
        if last_successful:
            qs = qs.exclude(pk=last_successful.pk)

        deleted_count, _ = qs.delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"SyncLog tozalash yakunlandi: {deleted_count} ta eski yozuv o'chirildi (saqlash davri: {days} kun)."
            )
        )
