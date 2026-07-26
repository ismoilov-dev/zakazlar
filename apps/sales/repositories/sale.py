"""ORM repository for imported sales."""

from collections.abc import Iterable

from django.db import transaction

from apps.sales.models import Sale


class SaleRepository:
    """Encapsulate high-throughput sale upserts."""

    @transaction.atomic
    def bulk_upsert(self, sales: Iterable[Sale]) -> tuple[int, int]:
        items = list(sales)
        external_ids = [sale.external_order_id for sale in items]
        existing_ids = set(
            Sale.objects.filter(external_order_id__in=external_ids).values_list("external_order_id", flat=True)
        )
        Sale.objects.bulk_create(
            items,
            batch_size=1000,
            update_conflicts=True,
            update_fields=["employee", "import_job", "status", "source", "sale_amount", "profit_amount", "ordered_at", "updated_at"],
            unique_fields=["external_order_id"],
        )
        updated = sum(item.external_order_id in existing_ids for item in items)
        return len(items) - updated, updated
