import logging
from collections.abc import Iterable

from django.db import transaction

from apps.sales.models import Sale

logger = logging.getLogger(__name__)


class SaleRepository:
    """Encapsulate high-throughput sale upserts."""

    @transaction.atomic
    def bulk_upsert(self, sales: Iterable[Sale]) -> tuple[int, int]:
        deduped_map: dict[str, Sale] = {}
        duplicate_ids: set[str] = set()

        for sale in sales:
            if sale.external_order_id in deduped_map:
                duplicate_ids.add(sale.external_order_id)
            deduped_map[sale.external_order_id] = sale

        if duplicate_ids:
            logger.warning(
                "Duplicate external_order_ids found during bulk_upsert: %s",
                sorted(list(duplicate_ids)),
            )

        items = list(deduped_map.values())
        if not items:
            return 0, 0

        external_ids = [sale.external_order_id for sale in items]
        existing_ids = set(
            Sale.objects.filter(external_order_id__in=external_ids).values_list("external_order_id", flat=True)
        )
        Sale.objects.bulk_create(
            items,
            batch_size=1000,
            update_conflicts=True,
            update_fields=["employee", "import_job", "status", "source", "sale_amount", "has_sheet_error", "profit_amount", "ordered_at", "updated_at"],
            unique_fields=["external_order_id"],
        )
        updated = sum(item.external_order_id in existing_ids for item in items)
        return len(items) - updated, updated
