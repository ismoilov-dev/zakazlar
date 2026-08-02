"""Management command to benchmark performance of Google Sheets sync fast and slow paths."""

from __future__ import annotations

import logging
import time
from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.imports.services.sheets_sync import SheetsSyncService
from apps.imports.sources.sheets import SheetsSource

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Benchmark timing per phase (Drive metadata, sheet read, parse, DB write, total) for fast and slow sync paths."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--runs",
            type=int,
            default=1,
            help="Number of benchmark iterations to run (default: 1).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        runs = options.get("runs", 1)
        self.stdout.write(self.style.MIGRATE_HEADING(f"=== Running Google Sheets Sync Benchmark ({runs} iteration(s)) ==="))

        for i in range(1, runs + 1):
            if runs > 1:
                self.stdout.write(f"\n--- Iteration {i}/{runs} ---")
            self._benchmark_fast_path()
            self._benchmark_slow_path()

    def _benchmark_fast_path(self) -> None:
        self.stdout.write(self.style.SUCCESS("\n[ FAST PATH — sync_payroll() ]"))
        service = SheetsSyncService()
        source = SheetsSource()
        sheet_id = source.sheet_id

        # 1. Drive metadata
        t0 = time.perf_counter()
        modified_time = service._get_drive_modified_time(source, sheet_id)
        t_drive = time.perf_counter() - t0

        # 2. Sheet read (batchGet)
        t0 = time.perf_counter()
        spreadsheet = source.client.open_by_key(sheet_id)
        value_ranges = spreadsheet.values_batch_get(["List2", "Guruhlar"]).get("valueRanges", [])
        raw_payroll = value_ranges[0].get("values", []) if len(value_ranges) > 0 else []
        raw_guruhlar = value_ranges[1].get("values", []) if len(value_ranges) > 1 else []
        t_read = time.perf_counter() - t0

        # 3. Parse
        t0 = time.perf_counter()
        payroll = source._parse_payroll(raw_payroll, sheet_title="List2")
        groups = source._parse_groups(raw_guruhlar)
        t_parse = time.perf_counter() - t0

        # 4. DB Write
        t0 = time.perf_counter()
        from apps.imports.models import SpreadsheetPeriod
        active_sp = SpreadsheetPeriod.objects.filter(is_active=True).first()
        period = active_sp.period if active_sp else None
        with transaction.atomic():
            processed = service.importer.import_payroll_only(
                payroll=payroll,
                group_summaries=groups,
                period=period,
                sheet_id=sheet_id,
            )
        t_db = time.perf_counter() - t0

        t_total = t_drive + t_read + t_parse + t_db

        self.stdout.write(f"  • Drive metadata check : {t_drive * 1000:7.2f} ms")
        self.stdout.write(f"  • Sheet read (batchGet): {t_read * 1000:7.2f} ms  (1 API call)")
        self.stdout.write(f"  • Parsing (List2+Grp)  : {t_parse * 1000:7.2f} ms  ({len(payroll)} payroll DTOs)")
        self.stdout.write(f"  • DB write (Diffed)    : {t_db * 1000:7.2f} ms")
        self.stdout.write(self.style.SUCCESS(f"  ► TOTAL FAST PATH TIME  : {t_total * 1000:7.2f} ms  ({t_total:.3f} s)"))

    def _benchmark_slow_path(self) -> None:
        self.stdout.write(self.style.WARNING("\n[ SLOW PATH — sync_orders() ]"))
        service = SheetsSyncService()
        source = SheetsSource()
        sheet_id = source.sheet_id

        # 1. Drive metadata
        t0 = time.perf_counter()
        modified_time = service._get_drive_modified_time(source, sheet_id)
        t_drive = time.perf_counter() - t0

        # 2. Sheet read
        t0 = time.perf_counter()
        orders, payroll = source.read()
        t_read = time.perf_counter() - t0

        # 3. Parse & period resolution
        t0 = time.perf_counter()
        from apps.imports.services.sheets_sync import resolve_sync_period
        period = resolve_sync_period(orders)
        t_parse = time.perf_counter() - t0

        # 4. DB Write
        t0 = time.perf_counter()
        with transaction.atomic():
            res = service.importer.import_orders_only(
                orders=orders,
                period=period,
            )
            created, updated = res if isinstance(res, tuple) and len(res) == 2 else (0, 0)
        t_db = time.perf_counter() - t0

        t_total = t_drive + t_read + t_parse + t_db

        self.stdout.write(f"  • Drive metadata check : {t_drive * 1000:7.2f} ms")
        self.stdout.write(f"  • Sheet read (List1)   : {t_read * 1000:7.2f} ms")
        self.stdout.write(f"  • Parse & resolve month: {t_parse * 1000:7.2f} ms  ({len(orders)} orders DTOs)")
        self.stdout.write(f"  • DB write (Diffed)    : {t_db * 1000:7.2f} ms  (Created: {created}, Updated: {updated})")
        self.stdout.write(self.style.WARNING(f"  ► TOTAL SLOW PATH TIME  : {t_total * 1000:7.2f} ms  ({t_total:.3f} s)"))
