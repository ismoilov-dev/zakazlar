from decimal import Decimal
from io import StringIO
from unittest.mock import mock_open, patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.imports.dto import OrderDTO, PayrollDTO
from apps.sales.models import SaleStatus


class CalcUserCommandTest(TestCase):
    @patch("os.path.exists", return_value=True)
    @patch("apps.statistics.management.commands.calc_user.ExcelSource")
    def test_calc_user_command_uses_excel_source(self, mock_excel_source_cls, mock_exists) -> None:
        mock_source = mock_excel_source_cls.return_value
        now = timezone.now()
        payroll = [
            PayrollDTO(
                employee_id="0191",
                employee_name="Amir Karimov",
                group_code="A",
                monthly_salary=Decimal("5000000.00"),
            )
        ]
        orders = [
            OrderDTO(
                employee_id="0191",
                employee_name="Amir Karimov",
                group_code="A",
                order_id="101",
                status=SaleStatus.SUCCESSFUL,
                source="Pervichka",
                sale_amount=Decimal("1000000.00"),
                ordered_at=now,
            )
        ]
        mock_source.read.return_value = (orders, payroll)

        out = StringIO()
        with patch("builtins.open", mock_open(read_data=b"dummy_excel_bytes")):
            call_command("calc_user", user_id="0191", file="test.xlsx", stdout=out)

        output = out.getvalue()
        self.assertIn("USER ID: 0191 — HISOB-KITOB NATIJALARI", output)
        self.assertIn("Amir Karimov", output)
        self.assertIn("1,000,000 so'm", output)
