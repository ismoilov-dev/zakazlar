from decimal import Decimal
from unittest.mock import MagicMock, patch
from django.test import TestCase
from django.core.exceptions import ValidationError as DjangoValidationError
from apps.common.services.exceptions import ValidationError as DomainValidationError

PARSE_ERRORS = (DjangoValidationError, DomainValidationError)

from apps.imports.dto import normalize_employee_id
from apps.imports.models import SyncLog, SyncStatus
from apps.imports.sources.sheets import SheetsSource
from apps.imports.services.sheets_sync import SheetsSyncService


class DroppedRowsAndDiagnosticsTest(TestCase):
    def test_forward_fill_empty_id_with_order_details(self):
        """Empty ID cell followed by a row with order details is forward-filled using last seen ID."""
        raw_data = [
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус", "Источник"],
            ["1", "0191", "Amir Karimov", "100,000", "28.07.2026", "успешно", "Baza"],
            ["2", "", "Amir Karimov", "200,000", "28.07.2026", "успешно", "Baza"],
        ]

        source = SheetsSource.__new__(SheetsSource)
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = raw_data

        orders = source._parse_orders(mock_worksheet)
        self.assertEqual(len(orders), 2)
        self.assertEqual(orders[0].employee_id, "0191")
        self.assertEqual(orders[1].employee_id, "0191")

    def test_completely_empty_row_is_skipped(self):
        """Fully empty rows are skipped without raising errors or tracking as dropped non-empty rows."""
        raw_data = [
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус", "Источник"],
            ["1", "0191", "Amir Karimov", "100,000", "28.07.2026", "успешно", "Baza"],
            ["", "", "", "", "", "", ""],  # Fully empty row
        ]

        source = SheetsSource.__new__(SheetsSource)
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = raw_data

        orders = source._parse_orders(mock_worksheet)
        self.assertEqual(len(orders), 1)
        self.assertEqual(source.last_parse_summary["empty_rows_skipped"], 1)

    def test_ten_data_rows_yield_exactly_ten_order_dtos(self):
        """A sheet with 10 data rows yields exactly 10 OrderDTO objects."""
        raw_data = [
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус", "Источник"]
        ] + [
            [str(i), "0191", "Amir Karimov", f"{i * 100000}", "28.07.2026", "успешно", "Baza"]
            for i in range(1, 11)
        ]

        source = SheetsSource.__new__(SheetsSource)
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = raw_data

        orders = source._parse_orders(mock_worksheet)
        self.assertEqual(len(orders), 10)

    def test_missing_header_row_raises_validation_error(self):
        """If header row is missing in top 15 rows, raise ValidationError instead of defaulting to row 0."""
        raw_data = [
            ["Random", "Data", "Without", "Headers"],
            ["Another", "Row", "No", "Match"],
        ]

        source = SheetsSource.__new__(SheetsSource)
        mock_worksheet = MagicMock()
        mock_worksheet.title = "List1"
        mock_worksheet.get_all_values.return_value = raw_data

        with self.assertRaises(PARSE_ERRORS):
            source._parse_orders(mock_worksheet)

    @patch("apps.imports.services.sheets_sync.SheetsSource")
    def test_skipped_rows_ratio_exceeding_threshold_marks_sync_failed(self, mock_source_cls):
        """If skipped rows ratio exceeds 5%, threshold raises error, import is aborted, and SyncLog status is marked FAILED."""
        from apps.employees.models import Employee
        from apps.sales.models import Sale

        emp = Employee.objects.create(employee_id="0191", full_name="Test Emp", summary_data={"total_sales": "1000"})
        initial_sale_count = Sale.objects.count()

        mock_source = MagicMock()
        mock_source.sheet_id = "test-sheet-id"
        mock_source.last_dropped_rows = [{"row_idx": i} for i in range(10)]  # 10 dropped rows
        mock_source.read.return_value = ([], [])  # 0 parsed orders
        mock_source_cls.return_value = mock_source

        sync_service = SheetsSyncService()
        with self.assertRaises(PARSE_ERRORS):
            sync_service.sync_if_needed(force=True)

        # Assert data integrity: no sales created/deleted, summary_data untouched
        self.assertEqual(Sale.objects.count(), initial_sale_count)
        emp.refresh_from_db()
        self.assertEqual(emp.summary_data, {"total_sales": "1000"})

        # Assert SyncLog created with status FAILED
        failed_log = SyncLog.objects.filter(status=SyncStatus.FAILED).order_by("-id").first()
        self.assertIsNotNone(failed_log)
        self.assertIn("Tashlangan qatorlar ulushi", failed_log.error_text)


    def test_softened_normalize_employee_id_handles_non_breaking_spaces_and_formula_errors(self):
        """normalize_employee_id strips non-breaking spaces and rejects formula error strings explicitly."""
        self.assertEqual(normalize_employee_id(" 191\xa0"), "0191")

        with self.assertRaises(PARSE_ERRORS) as ctx:
            normalize_employee_id("#N/A")
        self.assertIn("Formula xatosi", str(ctx.exception))
