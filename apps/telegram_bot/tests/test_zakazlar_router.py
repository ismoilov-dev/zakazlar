from datetime import datetime, date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import TelegramAccount
from apps.employees.models import Employee
from apps.groups.models import SalesGroup
from apps.imports.models import SpreadsheetPeriod
from apps.sales.models import Sale, SaleStatus
from apps.telegram_bot.routers import (
    get_order_status_counts,
    get_paginated_orders,
    handle_order_list_callbacks,
    handle_xizmatlar_callback,
)
from apps.telegram_bot.services.formatting import (
    MISSING_VALUE_TEXT,
    order_list_keyboard,
    order_list_text,
    order_status_picker_keyboard,
    order_status_picker_text,
)


class ZakazlarRouterTest(TestCase):
    def setUp(self):
        self.group = SalesGroup.objects.create(code="A", name="Group A")
        self.emp1 = Employee.objects.create(
            employee_id="0191",
            full_name="Amir Karimov",
            group=self.group,
        )
        self.acc1 = TelegramAccount.objects.create(
            employee=self.emp1,
            telegram_id=111111,
            username="amir_k",
        )

        self.emp2 = Employee.objects.create(
            employee_id="0079",
            full_name="Bekzod Alimov",
            group=self.group,
        )
        self.acc2 = TelegramAccount.objects.create(
            employee=self.emp2,
            telegram_id=222222,
            username="bekzod_a",
        )

        self.period = SpreadsheetPeriod.objects.create(
            period=date(2026, 7, 1),
            spreadsheet_id="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms",
            is_active=True,
        )

        # Create sales for emp1
        self.sale_succ1 = Sale.objects.create(
            external_order_id="202607_0191_1001",
            employee=self.emp1,
            status=SaleStatus.SUCCESSFUL,
            sale_amount=Decimal("750000.00"),
            client_name="maqsuda",
            product_name="Bioflex pro",
            quantity=1,
            ordered_at=timezone.make_aware(datetime(2026, 7, 1, 10, 0, 0)),
        )
        self.sale_succ2 = Sale.objects.create(
            external_order_id="202607_0191_1002",
            employee=self.emp1,
            status=SaleStatus.SUCCESSFUL,
            sale_amount=Decimal("1600000.00"),
            client_name="Хайдарова Ю.",
            product_name="Dolion Ge",
            quantity=2,
            ordered_at=timezone.make_aware(datetime(2026, 7, 1, 11, 0, 0)),
        )
        self.sale_canc = Sale.objects.create(
            external_order_id="202607_0191_1003",
            employee=self.emp1,
            status=SaleStatus.CANCELLED,
            sale_amount=Decimal("500000.00"),
            client_name="Sobir",
            product_name="Product X",
            quantity=1,
            ordered_at=timezone.make_aware(datetime(2026, 7, 2, 9, 0, 0)),
        )
        # Missing product, missing qty, NULL amount sale
        self.sale_null = Sale.objects.create(
            external_order_id="202607_0191_1004",
            employee=self.emp1,
            status=SaleStatus.PENDING,
            sale_amount=None,
            client_name="",
            product_name="",
            quantity=None,
            ordered_at=timezone.make_aware(datetime(2026, 7, 3, 14, 0, 0)),
        )

        # Create sale for emp2
        self.sale_other = Sale.objects.create(
            external_order_id="202607_0079_2001",
            employee=self.emp2,
            status=SaleStatus.SUCCESSFUL,
            sale_amount=Decimal("2000000.00"),
            client_name="Other Client",
            product_name="Other Product",
            quantity=5,
            ordered_at=timezone.make_aware(datetime(2026, 7, 1, 12, 0, 0)),
        )

    def test_get_order_status_counts(self):
        counts = get_order_status_counts(self.emp1.id, 2026, 7)
        self.assertEqual(counts.get("successful"), 2)
        self.assertEqual(counts.get("cancelled"), 1)
        self.assertEqual(counts.get("pending"), 1)

    def test_status_returns_right_set_and_only_own_orders(self):
        orders, total_count, total_pages = get_paginated_orders(
            employee_id=self.emp1.id,
            status="successful",
            year=2026,
            month=7,
            page=1,
        )
        self.assertEqual(total_count, 2)
        self.assertEqual(len(orders), 2)
        # Newest first
        self.assertEqual(orders[0].external_order_id, "202607_0191_1002")
        self.assertEqual(orders[1].external_order_id, "202607_0191_1001")
        self.assertTrue(all(o.employee_id == self.emp1.id for o in orders))

    def test_order_with_every_field_renders_all_six_lines(self):
        sale_full = Sale.objects.create(
            external_order_id="202607_0191_52344",
            employee=self.emp1,
            status=SaleStatus.SUCCESSFUL,
            sale_amount=Decimal("1000000.00"),
            client_name="maqsuda",
            product_name="Bioflex pro",
            quantity=1,
            product_name_2="Dolion Ge",
            quantity_2=2,
            ordered_at=timezone.make_aware(datetime(2026, 8, 2, 10, 0, 0)),
        )
        text = order_list_text(
            orders=[sale_full],
            status="successful",
            total_count=1,
            page=1,
            total_pages=1,
            period_label="Avgust 2026",
        )
        expected = (
            "✅ Muvaffaqiyatli — 1 ta\n"
            "📅 Avgust 2026\n\n"
            "1)\n"
            "🆔 Raqam: 52344\n"
            "👤 Mijoz: maqsuda\n"
            "💰 Narxi: 1\xa0000\xa0000 so'm\n"
            "💊 Tovar: Bioflex pro — 1 ta\n"
            "💊 Tovar 2: Dolion Ge — 2 ta\n"
            "📅 Vaqti: 02.08.2026"
        )
        self.assertEqual(text, expected)

    def test_order_missing_client_omits_client_line_and_keeps_rest(self):
        sale_no_client = Sale.objects.create(
            external_order_id="202607_0191_52345",
            employee=self.emp1,
            status=SaleStatus.SUCCESSFUL,
            sale_amount=Decimal("500000.00"),
            client_name="",
            product_name="Bioflex pro",
            quantity=1,
            ordered_at=timezone.make_aware(datetime(2026, 8, 2, 11, 0, 0)),
        )
        text = order_list_text(
            orders=[sale_no_client],
            status="successful",
            total_count=1,
            page=1,
            total_pages=1,
            period_label="Avgust 2026",
        )
        self.assertIn("1)\n🆔 Raqam: 52345\n💰 Narxi:", text)
        self.assertNotIn("👤 Mijoz:", text)
        self.assertIn("💊 Tovar: Bioflex pro — 1 ta", text)
        self.assertIn("📅 Vaqti: 02.08.2026", text)

    def test_order_with_no_second_product_has_no_tovar_2_line(self):
        text = order_list_text(
            orders=[self.sale_succ1],
            status="successful",
            total_count=1,
            page=1,
            total_pages=1,
            period_label="Iyul 2026",
        )
        self.assertIn("💊 Tovar: Bioflex pro — 1 ta", text)
        self.assertNotIn("💊 Tovar 2:", text)

    def test_null_amount_shows_missing_value_text(self):
        self.sale_null.has_sheet_error = True
        self.sale_null.save()
        text = order_list_text(
            orders=[self.sale_null],
            status="pending",
            total_count=1,
            page=1,
            total_pages=1,
            period_label="Iyul 2026",
        )
        self.assertIn(f"💰 Narxi: {MISSING_VALUE_TEXT}", text)
        self.assertNotIn("0 so'm", text)

    def test_pagination_boundaries_at_5_per_page(self):
        for i in range(10, 25):
            Sale.objects.create(
                external_order_id=f"202607_0191_{i}",
                employee=self.emp1,
                status=SaleStatus.SUCCESSFUL,
                sale_amount=Decimal("100000.00"),
                client_name=f"Client {i}",
                product_name="Prod",
                quantity=1,
                ordered_at=timezone.make_aware(datetime(2026, 7, 5, 10, i - 10, 0)),
            )

        orders_p1, total_count, total_pages = get_paginated_orders(self.emp1.id, "successful", 2026, 7, page=1)
        self.assertEqual(total_count, 17)
        self.assertEqual(total_pages, 4)
        self.assertEqual(len(orders_p1), 5)

        orders_p2, _, _ = get_paginated_orders(self.emp1.id, "successful", 2026, 7, page=2)
        self.assertEqual(len(orders_p2), 5)

        orders_p4, _, _ = get_paginated_orders(self.emp1.id, "successful", 2026, 7, page=4)
        self.assertEqual(len(orders_p4), 2)

    @patch("apps.telegram_bot.routers.ensure_fresh_data_and_get_timestamp", return_value=("01.07.2026 12:00:00", False))
    async def test_callback_xm_orders_opens_status_picker(self, _mock_ts):
        callback = MagicMock()
        callback.from_user.id = 111111
        callback.data = "xm_orders"
        callback.message.edit_text = AsyncMock()
        callback.answer = AsyncMock()

        await handle_xizmatlar_callback(callback)
        callback.message.edit_text.assert_called_once()
        text = callback.message.edit_text.call_args[0][0]
        self.assertIn("Zakazlar", text)
        reply_markup = callback.message.edit_text.call_args[1]["reply_markup"]
        btn_texts = [b.text for row in reply_markup.inline_keyboard for b in row]
        self.assertIn("✅ Muvaffaqiyatli (2)", btn_texts)
        self.assertIn("❌ Otkaz (1)", btn_texts)
        self.assertIn("⏳ Jarayonda (1)", btn_texts)

    async def test_privacy_tampered_callback_uses_sender_identity(self):
        """Even if payload requests orders, queries are strictly scoped to callback.from_user.id."""
        callback = MagicMock()
        callback.from_user.id = 222222  # Bekzod Alimov
        callback.data = "ord_list:successful:p=1"
        callback.message.edit_text = AsyncMock()
        callback.answer = AsyncMock()

        await handle_order_list_callbacks(callback)
        callback.message.edit_text.assert_called_once()
        text = callback.message.edit_text.call_args[0][0]
        self.assertIn("Other Client", text)
        self.assertNotIn("maqsuda", text)  # Amir's client must not be visible

    async def test_unbound_user_callback_returns_error(self):
        callback = MagicMock()
        callback.from_user.id = 999999
        callback.data = "ord_status:successful"
        callback.message.answer = AsyncMock()
        callback.answer = AsyncMock()

        await handle_order_list_callbacks(callback)
        callback.answer.assert_called_once_with("Avval Employee ID orqali profilingizni bog'lang.", show_alert=True)
