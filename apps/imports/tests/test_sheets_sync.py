from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.imports.models import SyncLog, SyncStatus
from apps.imports.services.sheets_sync import SheetsSyncService
from apps.imports.sources.sheets import SheetsSource
from apps.telegram_bot.routers import ensure_fresh_data_and_get_timestamp


class SheetsSyncFailureTest(TestCase):
    @patch("apps.imports.services.sheets_sync.SheetsSource")
    def test_sync_failure_updates_synclog_and_stale_flag(self, mock_sheets_source_cls) -> None:
        # Set up mock source to raise exception on read()
        mock_source = mock_sheets_source_cls.return_value
        mock_source.sheet_id = "test_sheet_id"
        mock_source.read_payroll_only.side_effect = Exception("API connection timeout")
        mock_source.read.side_effect = Exception("API connection timeout")

        service = SheetsSyncService()
        with self.assertRaises(Exception):
            service.sync_if_needed(force=True)

        # Check SyncLog
        log = SyncLog.objects.order_by("-started_at").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.status, SyncStatus.FAILED)
        self.assertIsNotNone(log.finished_at)
        self.assertIn("API connection timeout", log.error_text)

    @patch("apps.telegram_bot.routers._do_sync")
    async def test_is_stale_returns_true_when_failed(self, _mock_do_sync) -> None:
        # Create a FAILED log
        await SyncLog.objects.acreate(
            status=SyncStatus.FAILED,
            error_text="Fatal error",
            finished_at=timezone.now(),
        )

        _, is_stale = await ensure_fresh_data_and_get_timestamp()
        self.assertTrue(is_stale)

    @patch("apps.imports.services.sheets_sync.SHEETS_RECALC_DELAY_SECONDS", 0)
    @patch("apps.imports.services.sheets_sync.SheetsSource")
    def test_period_mismatch_aborts_sync_with_error_and_nothing_written(self, mock_sheets_source_cls) -> None:
        from datetime import date, datetime, timezone as tz
        from decimal import Decimal
        from apps.common.services.exceptions import ValidationError
        from apps.employees.models import EmployeeMonthlyStat
        from apps.imports.dto import OrderDTO, PayrollDTO
        from apps.imports.models import SpreadsheetPeriod

        SpreadsheetPeriod.objects.all().delete()
        SpreadsheetPeriod.objects.create(
            period=date(2026, 8, 1),
            spreadsheet_id="1W8wvi0nmrlnIsrqUBjNjEuoXbkcLQxFCK5fd3v3hto8",
            is_active=True,
        )

        mock_source = mock_sheets_source_cls.return_value
        mock_source.sheet_id = "16rSon1F6rSon1F6rSon1F6rSon1F6rSon1F6rSon1F"
        mock_source.read.return_value = (
            [
                OrderDTO(
                    employee_id="0001",
                    employee_name="Test Seller",
                    group_code="A",
                    order_id="1001",
                    status="Muvaffaqiyatli",
                    source="Test",
                    sale_amount=Decimal("100000"),
                    ordered_at=datetime(2026, 6, 15, 10, 0, tzinfo=tz.utc),
                )
            ],
            [
                PayrollDTO(
                    group_code="A",
                    employee_id="0001",
                    employee_name="Test Seller",
                    monthly_salary=None,
                    summary_data={"total_sales": "100000"},
                )
            ],
        )

        service = SheetsSyncService()
        with self.assertLogs("apps.imports.services.sheets_sync", level="ERROR") as cm:
            with self.assertRaises(ValidationError):
                service.sync_orders(force=True)

        self.assertTrue(any("does not match" in log for log in cm.output))
        self.assertEqual(EmployeeMonthlyStat.objects.count(), 0)

    @patch("apps.imports.services.sheets_sync.SHEETS_RECALC_DELAY_SECONDS", 0)
    @patch("apps.imports.services.sheets_sync.SheetsSource")
    def test_sync_payroll_fast_path_writes_no_sale_rows(self, mock_sheets_source_cls) -> None:
        from datetime import date
        from decimal import Decimal
        from apps.employees.models import Employee, EmployeeMonthlyStat
        from apps.imports.dto import GroupSummaryDTO, PayrollDTO
        from apps.imports.models import SpreadsheetPeriod
        from apps.sales.models import Sale

        SpreadsheetPeriod.objects.all().delete()
        SpreadsheetPeriod.objects.create(
            period=date(2026, 8, 1),
            spreadsheet_id="1W8wvi0nmrlnIsrqUBjNjEuoXbkcLQxFCK5fd3v3hto8",
            is_active=True,
        )

        mock_source = mock_sheets_source_cls.return_value
        mock_source.sheet_id = "1W8wvi0nmrlnIsrqUBjNjEuoXbkcLQxFCK5fd3v3hto8"
        mock_source.read_payroll_only.return_value = (
            [
                PayrollDTO(
                    group_code="A",
                    employee_id="0001",
                    employee_name="Test Seller",
                    monthly_salary=Decimal("5000000"),
                    summary_data={"earned_salary": "5000000", "total_sales": "10000000"},
                )
            ],
            [
                GroupSummaryDTO(
                    group_code="A",
                    group_total_sales=Decimal("10000000"),
                    group_profit=Decimal("2000000"),
                    leader_bonus=Decimal("200000"),
                )
            ],
        )

        service = SheetsSyncService()
        log = service.sync_payroll(force=True)

        self.assertEqual(log.status, SyncStatus.SUCCESS)
        self.assertEqual(Sale.objects.count(), 0)

        emp = Employee.objects.get(employee_id="0001")
        self.assertEqual(emp.summary_data["earned_salary"], "5000000")

        stat = EmployeeMonthlyStat.objects.get(employee=emp, period=date(2026, 8, 1))
        self.assertEqual(stat.summary_data["total_sales"], "10000000")

    @patch("apps.imports.sources.sheets.SheetsSource._authenticate")
    def test_read_payroll_only_uses_values_batch_get_single_api_call(self, mock_auth) -> None:
        from apps.imports.sources.sheets import SheetsSource

        mock_client = mock_auth.return_value
        mock_spreadsheet = mock_client.open_by_key.return_value
        mock_spreadsheet.values_batch_get.return_value = {
            "valueRanges": [
                {
                    "range": "List2!A1:Z100",
                    "values": [
                        ["ID", "FISH", "Guruhi", "Ish haqi", "Umumiy zakaz summasi"],
                        ["0001", "Amir Karimov", "A", "5,000,000", "10,000,000"],
                    ],
                },
                {
                    "range": "Guruhlar!A1:Z50",
                    "values": [
                        ["Guruh", "Guruh foydasi", "Rahbar bonusi"],
                        ["A", "2,000,000", "200,000"],
                    ],
                },
            ]
        }

        source = SheetsSource(sheet_id="test_sheet_id")
        payroll, groups = source.read_payroll_only()

        self.assertEqual(mock_spreadsheet.values_batch_get.call_count, 1)
        self.assertEqual(len(payroll), 1)
        self.assertEqual(payroll[0].employee_id, "0001")
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].group_code, "A")

    @patch("apps.imports.services.sheets_sync.SheetsSource")
    def test_drive_metadata_failure_proceeds_to_read(self, mock_sheets_source_cls) -> None:
        from apps.imports.dto import PayrollDTO

        mock_source = mock_sheets_source_cls.return_value
        mock_source.sheet_id = "test_sheet_id"
        mock_source.client.http_client.get_file_drive_metadata.side_effect = Exception("Drive API unavailable")
        mock_source.read_payroll_only.return_value = (
            [
                PayrollDTO(
                    group_code="A",
                    employee_id="0001",
                    employee_name="Test Seller",
                    monthly_salary=None,
                    summary_data={"earned_salary": "100000"},
                )
            ],
            [],
        )

        service = SheetsSyncService()
        log = service.sync_payroll(force=True)

        self.assertEqual(log.status, SyncStatus.SUCCESS)
        self.assertTrue(mock_source.read_payroll_only.called)

    @patch("apps.imports.services.sheets_sync.SheetsSource")
    def test_unchanged_payroll_hash_short_circuits_and_skips_db_writes(self, mock_sheets_source_cls) -> None:
        from apps.imports.dto import PayrollDTO

        mock_source = mock_sheets_source_cls.return_value
        mock_source.sheet_id = "test_sheet_id"
        mock_source.last_payroll_hash = "fixed_hash_123"
        mock_source.read_payroll_only.return_value = (
            [
                PayrollDTO(
                    group_code="A",
                    employee_id="0001",
                    employee_name="Test Seller",
                    monthly_salary=None,
                    summary_data={"earned_salary": "100000"},
                )
            ],
            [],
        )

        service = SheetsSyncService()
        log1 = service.sync_payroll(force=True)
        self.assertEqual(log1.payroll_hash, "fixed_hash_123")
        self.assertFalse(log1.unchanged)

        with patch.object(service.importer, "import_payroll_only") as mock_import:
            log2 = service.sync_payroll(force=False)
            self.assertFalse(mock_import.called)
            self.assertEqual(log2.status, SyncStatus.SUCCESS)
            self.assertTrue(log2.unchanged)
            self.assertEqual(log2.row_count, 0)
            self.assertGreaterEqual(log2.finished_at, log1.finished_at)

            last_successful = SyncLog.get_last_successful()
            self.assertEqual(last_successful.pk, log2.pk)
            self.assertEqual(last_successful.finished_at, log2.finished_at)

    @patch("apps.imports.services.sheets_sync.SheetsSource")
    def test_get_last_successful_includes_payroll_fast_path_logs(self, mock_sheets_source_cls) -> None:
        from apps.imports.dto import PayrollDTO

        mock_source = mock_sheets_source_cls.return_value
        mock_source.sheet_id = "test_sheet_id"
        mock_source.read_payroll_only.return_value = (
            [
                PayrollDTO(
                    group_code="A",
                    employee_id="0001",
                    employee_name="Test Seller",
                    monthly_salary=None,
                    summary_data={"earned_salary": "100000"},
                )
            ],
            [],
        )

        service = SheetsSyncService()
        payroll_log = service.sync_payroll(force=True)

        last_successful = SyncLog.get_last_successful()
        self.assertIsNotNone(last_successful)
        self.assertEqual(last_successful.pk, payroll_log.pk)
        self.assertEqual(last_successful.sync_type, "payroll")

    @patch("apps.imports.management.commands.sync_benchmark.SheetsSource")
    @patch("apps.imports.management.commands.sync_benchmark.SheetsSyncService")
    def test_sync_benchmark_command_executes_successfully(self, mock_service_cls, mock_source_cls) -> None:
        from io import StringIO
        from datetime import datetime, timezone as dt_timezone
        from decimal import Decimal
        from django.core.management import call_command
        from apps.imports.dto import OrderDTO, PayrollDTO

        mock_source = mock_source_cls.return_value
        mock_source.sheet_id = "test_sheet_id"
        mock_source.read.return_value = (
            [
                OrderDTO(
                    employee_id="0001",
                    employee_name="Test Seller",
                    group_code="A",
                    order_id="202608_0001_1",
                    status="successful",
                    source="Baza",
                    sale_amount=Decimal("100000"),
                    ordered_at=datetime(2026, 8, 1, tzinfo=dt_timezone.utc),
                )
            ],
            [],
        )
        mock_source._parse_payroll.return_value = [
            PayrollDTO(
                group_code="A",
                employee_id="0001",
                employee_name="Test Seller",
                monthly_salary=None,
                summary_data={"earned_salary": "100000"},
            )
        ]
        mock_source._parse_groups.return_value = []

        out = StringIO()
        call_command("sync_benchmark", runs=1, stdout=out)
        output = out.getvalue()
        self.assertIn("FAST PATH", output)
        self.assertIn("SLOW PATH", output)
        self.assertIn("TOTAL FAST PATH TIME", output)

    def test_tightened_sheet_error_detector(self) -> None:
        from apps.imports.sources.sheets import SheetsSource, SHEET_ERROR_LITERALS

        source = SheetsSource(sheet_id="test_sheet_id")
        self.assertFalse(source._is_sheet_error("#1 mijoz"))
        self.assertFalse(source._is_sheet_error("N/A"))
        self.assertFalse(source._is_sheet_error("ERR"))
        self.assertFalse(source._is_sheet_error("ERROR"))

        self.assertTrue(source._is_sheet_error("#N/A"))
        self.assertTrue(source._is_sheet_error("#REF!"))
        self.assertTrue(source._is_sheet_error("#DIV/0!"))
        self.assertTrue(source._is_sheet_error("#VALUE!"))

    def test_payroll_cell_formula_error_omits_key_without_dropping_row(self) -> None:
        from decimal import Decimal
        from apps.imports.sources.sheets import SheetsSource

        source = SheetsSource(sheet_id="test_sheet_id")
        raw_payroll = [
            ["ID", "FISH", "Guruhi", "Ish haqi", "Umumiy zakaz summasi", "Otkaz"],
            ["0079", "Test Emp 0079", "A", "10,000,000", "50,000,000", "#N/A"],
        ]
        payroll = source._parse_payroll(raw_payroll)
        self.assertEqual(len(payroll), 1)
        dto = payroll[0]
        self.assertEqual(dto.employee_id, "0079")
        self.assertEqual(dto.monthly_salary, Decimal("10000000"))
        self.assertEqual(dto.summary_data.get("total_sales"), "50000000")
        self.assertNotIn("otkaz_sales", dto.summary_data)
        self.assertEqual(len(getattr(source, "last_dropped_payroll_rows", [])), 0)

    def test_payroll_high_ratio_formula_errors_syncs_successfully(self) -> None:
        """300 qatordan 250 tasida #N/A bo'lsa ham sync muvaffaqiyatli tugashi va boshqa ko'rsatkichlar saqlanishi kerak."""
        from decimal import Decimal
        from apps.imports.sources.sheets import SheetsSource

        source = SheetsSource(sheet_id="test_sheet_id")
        raw_payroll = [["ID", "FISH", "Guruhi", "Ish haqi", "Umumiy zakaz summasi", "Otkaz"]]
        for i in range(1, 301):
            emp_id = str(i).zfill(4)
            otkaz_val = "#N/A" if i <= 250 else "1,000,000"
            raw_payroll.append([emp_id, f"Emp {emp_id}", "A", "10,000,000", "50,000,000", otkaz_val])

        payroll = source._parse_payroll(raw_payroll)
        self.assertEqual(len(payroll), 300)
        self.assertEqual(len(getattr(source, "last_dropped_payroll_rows", [])), 0)

        # Check first 250 employees have total_sales but omit otkaz_sales
        self.assertEqual(payroll[0].summary_data.get("total_sales"), "50000000")
        self.assertNotIn("otkaz_sales", payroll[0].summary_data)

        # Check remaining 50 employees have both total_sales and otkaz_sales
        self.assertEqual(payroll[255].summary_data.get("total_sales"), "50000000")
        self.assertEqual(payroll[255].summary_data.get("otkaz_sales"), "1000000")

    def test_list1_row_with_formula_error_amount_imports_as_null_and_has_sheet_error(self) -> None:
        from unittest.mock import MagicMock
        from apps.imports.sources.sheets import SheetsSource

        ws = MagicMock()
        ws.title = "List1"
        ws.get_all_values.return_value = [
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус", "Источник"],
            ["1", "0001", "Amir Karimov", "#N/A", "28.07.2026", "успешно", "Baza"],
        ]

        source = SheetsSource(sheet_id="test_sheet_id")
        orders = source._parse_orders(ws)

        self.assertEqual(len(orders), 1)
        dto = orders[0]
        self.assertEqual(dto.order_id, "202607_0001_1")
        self.assertIsNone(dto.sale_amount)
        self.assertTrue(dto.has_sheet_error)
        self.assertEqual(len(getattr(source, "last_dropped_rows", [])), 0)

    def test_sheets_group_summary_preserved_without_being_overwritten_by_db(self) -> None:
        """Verify that Google Sheets GroupSummaryDTO totals are preserved as authoritative in SalesGroup."""
        from decimal import Decimal
        from apps.groups.models import SalesGroup
        from apps.imports.dto import GroupSummaryDTO, OrderDTO, PayrollDTO
        from apps.imports.services.importer import DataImporter

        group = SalesGroup.objects.create(code="B", name="Group B", group_total_sales=Decimal("0"))

        importer = DataImporter()
        importer.import_dto_lists(
            orders=[],
            payroll=[],
            group_summaries=[
                GroupSummaryDTO(
                    group_code="B",
                    group_total_sales=Decimal("630315000.00"),
                    group_profit=Decimal("200000000.00"),
                    leader_bonus=Decimal("5000000.00"),
                )
            ],
        )

        group.refresh_from_db()
        self.assertEqual(group.group_total_sales, Decimal("630315000.00"))


