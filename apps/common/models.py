"""Shared persistence primitives."""

from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base model with audit timestamps."""

    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
