"""Management command to clear all Google Sheets integration cache keys."""

from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.db import connection


def clear_sheets_cache_keys() -> int:
    """Clear all sheets-related cache keys and return total deleted count."""
    count = 0
    known_keys = [
        "sheets_sync_recent_lock",
        "sheets_sync_orders_lock",
        "sheet_webhook_last_call_timestamp",
    ]

    for key in known_keys:
        try:
            if cache.delete(key):
                count += 1
        except Exception:
            pass

    # For DatabaseCache, query sync_cache table directly if present to delete pattern keys
    try:
        tables = connection.introspection.table_names()
        if "sync_cache" in tables:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM sync_cache WHERE cache_key LIKE 'sheets_ws_titles_%%' OR cache_key LIKE 'drive_modified_time_%%';"
                )
                count += cursor.rowcount
    except Exception:
        pass

    return count


class Command(BaseCommand):
    help = "Barcha Google Sheets bilan bog'liq kesh kalitlarini tozalaydi."

    def handle(self, *args, **options):
        deleted_count = clear_sheets_cache_keys()
        self.stdout.write(
            self.style.SUCCESS(f"✅ Google Sheets kesh kalitlari tozalandi! Jami {deleted_count} ta kalit o'chirildi.")
        )
