from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.employees.models import Employee
from apps.groups.models import SalesGroup
from apps.sales.models import Sale, SaleStatus
from apps.sales.repositories.sale import SaleRepository


class SaleRepositoryTest(TestCase):
    def test_bulk_upsert_deduplication(self) -> None:
        group = SalesGroup.objects.create(code="A", name="Group A")
        employee = Employee.objects.create(
            employee_id="0001",
            full_name="Test Employee",
            group=group,
        )
        now = timezone.now()
        repo = SaleRepository()

        sale1 = Sale(
            external_order_id="10001",
            employee=employee,
            status=SaleStatus.PENDING,
            source="Pervichka",
            sale_amount=Decimal("500000.00"),
            profit_amount=Decimal("0"),
            ordered_at=now,
        )
        sale2 = Sale(
            external_order_id="10001",  # Same external_order_id
            employee=employee,
            status=SaleStatus.SUCCESSFUL,  # Updated status and amount
            source="Pervichka",
            sale_amount=Decimal("800000.00"),
            profit_amount=Decimal("0"),
            ordered_at=now,
        )

        created, updated = repo.bulk_upsert([sale1, sale2])
        self.assertEqual((created, updated), (1, 0))

        self.assertEqual(Sale.objects.count(), 1)
        saved_sale = Sale.objects.get(external_order_id="10001")
        self.assertEqual(saved_sale.status, SaleStatus.SUCCESSFUL)
        self.assertEqual(saved_sale.sale_amount, Decimal("800000.00"))
