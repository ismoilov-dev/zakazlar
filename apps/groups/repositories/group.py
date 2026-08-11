"""ORM repository for sales groups."""

from apps.common.repositories.base import DjangoRepository
from apps.groups.models import SalesGroup


class SalesGroupRepository(DjangoRepository[SalesGroup]):
    """Encapsulate group lookup and import-time upsert operations."""

    model = SalesGroup

    def get_or_create(self, *, code: str) -> SalesGroup:
        group, _ = self.model.objects.get_or_create(code=code, defaults={"name": f"Group {code}"})
        return group

    def get_for_leader(self, *, leader_id: int) -> SalesGroup:
        group = self.model.objects.filter(leader_id=leader_id, is_active=True).first()
        if not group:
            raise SalesGroup.DoesNotExist("Guruh topilmadi.")
        return group
