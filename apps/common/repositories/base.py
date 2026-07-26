"""Small reusable base for ORM repository implementations."""

from __future__ import annotations

from typing import Generic, TypeVar

from django.db.models import Model

ModelT = TypeVar("ModelT", bound=Model)


class DjangoRepository(Generic[ModelT]):
    """Expose basic persistence operations without leaking ORM to services."""

    model: type[ModelT]

    def get(self, pk: int) -> ModelT:
        """Return an object or raise its model-specific DoesNotExist error."""
        return self.model.objects.get(pk=pk)
