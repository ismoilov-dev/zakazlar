"""Management command to synchronize Google Sheets data live into PostgreSQL."""

from __future__ import annotations

import logging
import signal
import time
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.common.services.exceptions import ValidationError
from apps.imports.services.sheets_sync import SheetsSyncService

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Synchronize live Google Sheets data into PostgreSQL database inside an atomic transaction."

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.keep_running = True

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--force",
            action="store_true",
            help="Bypass freshness and cache checks and force sync.",
        )
        parser.add_argument(
            "--watch",
            action="store_true",
            help="Run continuously as a daemon, syncing every interval seconds.",
        )
        parser.add_argument(
            "--interval",
            type=int,
            default=30,
            help="Interval in seconds between sync checks when running in watch mode (default: 30).",
        )
        parser.add_argument(
            "--allow-period-mismatch",
            action="store_true",
            help="Allow sync to proceed even if active SpreadsheetPeriod does not match sheet data modal month.",
        )

    def _handle_signal(self, signum: int, frame: Any) -> None:
        self.stdout.write(self.style.WARNING(f"\nSignal {signum} qabul qilindi. Jarayon toza to'xtatilmoqda..."))
        self.keep_running = False

    def handle(self, *args: Any, **options: Any) -> None:
        force = options.get("force", False)
        watch = options.get("watch", False)
        interval = options.get("interval", 30)
        allow_period_mismatch = options.get("allow_period_mismatch", False)

        if watch:
            signal.signal(signal.SIGINT, self._handle_signal)
            signal.signal(signal.SIGTERM, self._handle_signal)
            self.stdout.write(self.style.SUCCESS(f"Google Sheets davriy sinxronizatsiyasi boshlandi (interval={interval}s)..."))

            service = SheetsSyncService()
            while self.keep_running:
                try:
                    self._sync_once(service, force=force, allow_period_mismatch=allow_period_mismatch)
                except Exception as exc:
                    logger.error("Watch rejimida sinxronizatsiya xatoligi: %s", exc)

                sleep_chunk = 1
                slept = 0
                while self.keep_running and slept < interval:
                    time.sleep(min(sleep_chunk, interval - slept))
                    slept += sleep_chunk

            self.stdout.write(self.style.SUCCESS("Davriy sinxronizatsiya toza yakunlandi."))
        else:
            self.stdout.write("Google Sheets sinxronizatsiyasi boshlanmoqda...")
            service = SheetsSyncService()
            self._sync_once(service, force=force, allow_period_mismatch=allow_period_mismatch)

    def _sync_once(self, service: SheetsSyncService, force: bool, allow_period_mismatch: bool = False) -> None:
        try:
            sync_log = service.sync_if_needed(force=force, allow_period_mismatch=allow_period_mismatch)

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
