"""Management command to synchronize Google Sheets data live into PostgreSQL."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.common.services.exceptions import ValidationError
from apps.imports.services.sheets_sync import SheetsSyncService


class Command(BaseCommand):
    help = "Synchronize live Google Sheets data into PostgreSQL database inside an atomic transaction."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--force",
            action="store_true",
            help="Bypass freshness and cache checks and force sync.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        force = options.get("force", False)
        self.stdout.write("Google Sheets sinxronizatsiyasi boshlanmoqda...")

        try:
            service = SheetsSyncService()
            sync_log = service.sync_if_needed(force=force)

            if sync_log.status == "success":
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Muvaffaqiyatli sinxronlandi! {sync_log.row_count} ta buyurtma saqlandi "
                        f"(Yangi: {sync_log.created_sales}, Yangilandi: {sync_log.updated_sales})."
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"Sinxronizatsiya holati: {sync_log.status} (O'zgarishsiz o'tkazib yuborildi)."
                    )
                )
        except ValidationError as exc:
            raise CommandError(str(exc)) from exc
        except Exception as exc:
            raise CommandError(f"Kutilmagan xatolik: {exc}") from exc
