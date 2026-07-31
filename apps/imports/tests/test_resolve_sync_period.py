from datetime import date, datetime

from django.test import TestCase

from apps.common.services.exceptions import ValidationError
from apps.imports.dto import OrderDTO
from apps.imports.services.sheets_sync import resolve_sync_period


class ResolveSyncPeriodTest(TestCase):
    def test_modal_month_resolution(self):
        orders = [
            OrderDTO("0191", "Amir", "A", "1", "successful", "Baza", 100, datetime(2026, 6, 15, 10, 0)),
            OrderDTO("0191", "Amir", "A", "2", "successful", "Baza", 100, datetime(2026, 6, 16, 10, 0)),
            OrderDTO("0191", "Amir", "A", "3", "successful", "Baza", 100, datetime(2026, 5, 30, 10, 0)),
        ]

        period = resolve_sync_period(orders)
        self.assertEqual(period, date(2026, 6, 1))

    def test_modal_month_under_threshold_raises_validation_error(self):
        orders = [
            OrderDTO("0191", "Amir", "A", "1", "successful", "Baza", 100, datetime(2026, 6, 15, 10, 0)),
            OrderDTO("0191", "Amir", "A", "2", "successful", "Baza", 100, datetime(2026, 5, 16, 10, 0)),
        ]

        with self.assertRaises(ValidationError) as ctx:
            resolve_sync_period(orders)
        self.assertIn("50.0%", str(ctx.exception))
