from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import TestCase

from apps.common.services.exceptions import ValidationError as DomainValidationError

PARSE_ERRORS = (DjangoValidationError, DomainValidationError)

from apps.imports.models import SyncLog, SyncStatus
from apps.imports.services.sheets_sync import SheetsSyncService
from apps.imports.sources.sheets import SheetsSource


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
        mock_source.last_dropped_payroll_rows = [{"row_idx": i} for i in range(10)]
        mock_source.read.return_value = ([], [])  # 0 parsed orders
        mock_source.read_payroll_only.return_value = ([], [])
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


    def test_summary_total_equals_empty_plus_dropped_plus_successful(self):
        """Verify that total_raw_rows == empty_rows_skipped + dropped_count + parsed_rows_count."""
        raw_data = [
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус", "Источник"],
            ["1", "0191", "Amir Karimov", "100,000", "28.07.2026", "успешно", "Baza"],
            ["", "", "", "", "", "", ""],  # empty row -> skipped
            ["2", "INVALID_ID_ABC", "Amir Karimov", "100,000", "28.07.2026", "успешно", "Baza"],  # dropped row
        ]

        source = SheetsSource.__new__(SheetsSource)
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = raw_data

        source._parse_orders(mock_worksheet)
        summary = source.last_parse_summary
        total = summary["total_raw_rows"]
        empty = summary["empty_rows_skipped"]
        dropped = summary["dropped_count"]
        successful = summary["parsed_rows_count"]

        self.assertEqual(total, 3)
        self.assertEqual(empty, 1)
        self.assertEqual(dropped, 1)
        self.assertEqual(successful, 1)
        self.assertEqual(total, empty + dropped + successful)

    def test_300_real_rows_and_4000_blank_rows_fixture(self):
        """300 real order rows and 4000 blank/template rows with pre-filled order numbers yields empty_rows_skipped == 4000 and dropped_rows == 0."""
        headers = ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус", "Источник"]
        real_rows = [
            [str(i), "0191", "Amir Karimov", f"{i * 100000}", "28.07.2026", "успешно", "Baza"]
            for i in range(1, 301)
        ]
        blank_rows_with_row_numbers = [
            [str(i), "", "", "", "", "", ""]
            for i in range(301, 4301)
        ]
        raw_data = [headers] + real_rows + blank_rows_with_row_numbers

        source = SheetsSource.__new__(SheetsSource)
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = raw_data

        orders = source._parse_orders(mock_worksheet)
        self.assertEqual(len(orders), 300)
        self.assertEqual(source.last_parse_summary["empty_rows_skipped"], 4000)
        self.assertEqual(source.last_parse_summary["dropped_count"], 0)
        self.assertEqual(len(source.last_dropped_rows), 0)

    def test_empty_id_resolved_by_name_map_from_payroll_or_db(self):
        """Empty ID cell with a known employee name is resolved using name_to_id_map rather than dropped."""
        raw_data = [
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус", "Источник"],
            ["1", "0191", "Amir Karimov", "100,000", "28.07.2026", "успешно", "Baza"],
            ["2", "", "Bekzod Alimov", "150,000", "28.07.2026", "успешно", "Baza"],
        ]

        source = SheetsSource.__new__(SheetsSource)
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = raw_data

        name_to_id_map = {"bekzod alimov": "0079"}
        orders = source._parse_orders(mock_worksheet, name_to_id_map=name_to_id_map)
        self.assertEqual(len(orders), 2)
        self.assertEqual(orders[0].employee_id, "0191")
        self.assertEqual(orders[1].employee_id, "0079")
        self.assertEqual(len(source.last_dropped_rows), 0)

    def test_unknown_or_empty_group_imported_as_unknown_not_dropped(self):
        """Unknown or empty Bo'lim (Group) cell does not drop the order; group_code is set to UNKNOWN."""
        raw_data = [
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус", "Bo'lim", "Источник"],
            ["1", "0191", "Amir Karimov", "100,000", "28.07.2026", "успешно", "", "Baza"],
            ["2", "0079", "Bekzod Alimov", "150,000", "28.07.2026", "успешно", "CustomGroupX", "Baza"],
        ]

        source = SheetsSource.__new__(SheetsSource)
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = raw_data

        with self.assertLogs("apps.imports.sources.sheets", level="DEBUG") as cm:
            orders = source._parse_orders(mock_worksheet)

        self.assertEqual(len(orders), 2)
        self.assertEqual(orders[0].group_code, "UNKNOWN")
        self.assertEqual(orders[1].group_code, "UNKNOWN")
        self.assertEqual(len(source.last_dropped_rows), 0)
        self.assertEqual(source.last_parse_summary["dropped_count"], 0)
        self.assertTrue(any("noma'lum guruh (Bo'lim) qiymatlari agregatsiyasi" in log for log in cm.output))

    def test_single_space_header_not_picked_as_group_idx(self):
        """A single space ' ' header column must not be selected as group_idx if explicit Bo'lim column exists."""
        raw_data = [
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус", " ", "Bo'lim", "Источник"],
            ["1", "0191", "Amir Karimov", "100,000", "28.07.2026", "успешно", "U", "B", "Baza"],
        ]

        source = SheetsSource.__new__(SheetsSource)
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = raw_data

        orders = source._parse_orders(mock_worksheet)
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0].group_code, "B")

    def test_formula_error_name_template_rows_skipped_as_empty(self):
        """Rows with empty ID and formula error names like 'Kerkali BO'LIM topilmadi' are skipped as empty, not dropped."""
        raw_data = [
            ["№", "ID", "Ответственный", "Сумма", "Дата Заказа", "статус", "Источник"],
            ["1", "0191", "Amir Karimov", "100,000", "28.07.2026", "успешно", "Baza"],
            ["", "", "Kerkali BO'LIM topilmadi", "", "", "", ""],
            ["", "", "Kerakli BO'LIM topilmadi", "", "", "", ""],
        ]

        source = SheetsSource.__new__(SheetsSource)
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = raw_data

        orders = source._parse_orders(mock_worksheet)
        self.assertEqual(len(orders), 1)
        self.assertEqual(source.last_parse_summary["empty_rows_skipped"], 2)
        self.assertEqual(source.last_parse_summary["dropped_count"], 0)
        self.assertEqual(len(source.last_dropped_rows), 0)

