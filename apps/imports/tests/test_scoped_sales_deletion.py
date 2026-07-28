from datetime import datetime
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone

from apps.employees.models import Employee
from apps.imports.dto import OrderDTO
from apps.imports.services.importer import DataImporter
from apps.sales.models import Sale, SaleStatus


class ScopedSalesDeletionTest(TestCase):
    def test_sync_preserves_sales_from_other_months(self):
        """Importing orders for July 2026 should delete deleted July sales but preserve June 2026 sales."""
        employee = Employee.objects.create(employee_id="0191", full_name="Amir Karimov")

        june_date = timezone.make_aware(datetime(2026, 6, 15, 10, 0, 0))
        july_date = timezone.make_aware(datetime(2026, 7, 15, 10, 0, 0))

        # June order (historical/Excel data)
        sale_june = Sale.objects.create(
            employee=employee,
            external_order_id="0191_JUNE_1",
            sale_amount=Decimal("100000"),
            status=SaleStatus.SUCCESSFUL,
            ordered_at=june_date,
        )

        # Old July order (no longer in sheet)
        sale_july_old = Sale.objects.create(
            employee=employee,
            external_order_id="0191_JULY_OLD",
            sale_amount=Decimal("100000"),
            status=SaleStatus.SUCCESSFUL,
            ordered_at=july_date,
        )

        # Current July order (in sheet)
        july_orders = [
            OrderDTO(
                order_id="0191_JULY_NEW",
                employee_id="0191",
                employee_name="Amir Karimov",
                group_code="A",
                sale_amount=Decimal("200000"),
                ordered_at=july_date,
                status="successful",
                source="baza",
            )
        ]

        importer = DataImporter()
        importer.import_dto_lists(orders=july_orders, payroll=[])

        # Verify June sale still exists
        self.assertTrue(Sale.objects.filter(pk=sale_june.pk).exists())

        # Verify old July sale was removed
        self.assertFalse(Sale.objects.filter(pk=sale_july_old.pk).exists())

        # Verify new July sale was created
        self.assertTrue(Sale.objects.filter(external_order_id="0191_JULY_NEW").exists())
