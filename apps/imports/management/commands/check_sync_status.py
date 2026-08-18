"""Management command to check Google Sheets sync status, active period, and recent sync logs."""

from __future__ import annotations

import logging
from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.imports.models import SyncLog, SpreadsheetPeriod
from apps.imports.sources.sheets import SheetsSource

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Check whether Google Sheets sync is functioning, active SpreadsheetPeriod, and display recent sync logs."

    def handle(self, *args: Any, **options: Any) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING("=== GOOGLE SHEETS SINXRONIZATSIYA HOLATI VA DIAGNOSTIKASI ==="))

        # 1. Active SpreadsheetPeriod Check
        self.stdout.write("\n1. 📅 FAOL OYLIK PERIOD (SpreadsheetPeriod):")
        active_period = SpreadsheetPeriod.objects.filter(is_active=True).first()
        if active_period:
            period_str = active_period.period.strftime("%Y-%m")
            self.stdout.write(self.style.SUCCESS(f"   ✓ Faol period: {period_str}"))
            self.stdout.write(f"   ✓ Spreadsheet ID: {active_period.spreadsheet_id}")
            if active_period.note:
                self.stdout.write(f"   ✓ Izoh: {active_period.note}")
        else:
            self.stdout.write(self.style.WARNING("   ⚠️ DIQQAT: Bazada is_active=True bo'lgan SpreadsheetPeriod topilmadi!"))

        # 2. Live Google Sheets API Connection Test
        self.stdout.write("\n2. 🔗 GOOGLE SHEETS API ULANISHI VA O'QISH TESTI:")
        try:
            source = SheetsSource()
            orders, payroll = source.read()
            self.stdout.write(self.style.SUCCESS("   ✓ Google Sheets API ulanishi MUVAFFAQIYATLI!"))
            self.stdout.write(f"   ✓ List1 (Zakazlar): {len(orders)} ta buyurtma o'qildi")
            self.stdout.write(f"   ✓ List2 (Payroll): {len(payroll)} ta xodim o'qildi")
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"   X XATOLIK: Google Sheets'dan o'qishda xato: {exc}"))

        # 3. Recent Sync Logs Check
        self.stdout.write("\n3. 📊 OXIRGI SINXRONIZATSIYA LOGLARI (SyncLog):")
        recent_logs = SyncLog.objects.all().order_by("-started_at")[:5]
        if not recent_logs:
            self.stdout.write(self.style.WARNING("   ⚠️ Tizimda hali birorta ham SyncLog saqlanmagan."))
        else:
            for log in recent_logs:
                st_color = self.style.SUCCESS if log.status == "success" else self.style.ERROR
                started_str = timezone.localtime(log.started_at).strftime("%d.%m.%Y %H:%M:%S")
                self.stdout.write(st_color(f"   • [{started_str}] {log.sync_type.upper()} -> {log.status.upper()}"))
                self.stdout.write(f"     Row count: {log.row_count} | Yangi: {log.created_sales} | Yangilandi: {log.updated_sales}")
                if log.error_text:
                    self.stdout.write(self.style.ERROR(f"     Xatolik: {log.error_text}"))

        # 4. Summary Verdict
        self.stdout.write(self.style.MIGRATE_HEADING("\n=== DIAGNOSTIKA YAKUNI ==="))
        last_payroll_sync = SyncLog.get_last_successful(sync_type="payroll")
        last_orders_sync = SyncLog.get_last_successful(sync_type="orders")
        
        if last_payroll_sync and last_orders_sync:
            p_time = timezone.localtime(last_payroll_sync.finished_at).strftime("%H:%M:%S")
            o_time = timezone.localtime(last_orders_sync.finished_at).strftime("%H:%M:%S")
            self.stdout.write(self.style.SUCCESS(f"✅ TIZIM SOG'LOM: Payroll ({p_time}) va Zakazlar ({o_time}) muvaffaqiyatli yangilanmoqda!"))
        else:
            self.stdout.write(self.style.WARNING("⚠️ Ba'zi sinxronizatsiya turlari hali to'liq yakunlanmagan."))
