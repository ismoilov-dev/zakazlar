"""Base interface for all import sources."""

from __future__ import annotations

from abc import ABC, abstractmethod

from apps.imports.dto import OrderDTO, PayrollDTO


class BaseSource(ABC):
    """Abstract source that reads data and returns clean DTO lists without touching DB."""

    @abstractmethod
    def read(self) -> tuple[list[OrderDTO], list[PayrollDTO]]:
        """Read data from source and return (orders, payroll)."""
        pass
