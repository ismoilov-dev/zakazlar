"""Importer layer that persists parsed DTOs into PostgreSQL.

This is the ONLY code that touches the database during imports.
"""

from __future__ import annotations

from decimal import Decimal
from typing import NamedTuple

from django.db import transaction

from apps.employees.repositories.employee import EmployeeRepository
from apps.groups.repositories.group import SalesGroupRepository
from apps.imports.dto import OrderDTO, PayrollDTO
from apps.imports.models import ImportJob
from apps.sales.models import Sale
from apps.sales.repositories.sale import SaleRepository


class ImportResult(NamedTuple):
    processed_rows: int
    created_sales: int
    updated_sales: int


class DataImporter:
    """Writes clean DTO lists transactionally to database."""

    def __init__(self) -> None:
        self.groups = SalesGroupRepository()
        self.employees = EmployeeRepository()
        self.sales = SaleRepository()

    def import_dto_lists(
        self,
        *,
        orders: list[OrderDTO],
        payroll: list[PayrollDTO],
        job: ImportJob | None = None,
    ) -> ImportResult:
        """Persist payroll and orders inside a single atomic transaction."""
        with transaction.atomic():
            # 1. Upsert payroll & employees
            for row in payroll:
                group = self.groups.get_or_create(code=row.group_code)
                self.employees.upsert(
                    employee_id=row.employee_id,
                    full_name=row.employee_name,
                    group=group,
                    monthly_salary=row.monthly_salary,
                )

            # 2. Upsert sales & employees
            sales_to_upsert: list[Sale] = []
            for row in orders:
                group = self.groups.get_or_create(code=row.group_code)
                employee = self.employees.upsert(
                    employee_id=row.employee_id,
                    full_name=row.employee_name,
                    group=group,
                )
                sales_to_upsert.append(
                    Sale(
                        external_order_id=row.order_id,
                        employee=employee,
                        import_job=job,
                        status=row.status,
                        source=row.source,
                        sale_amount=row.sale_amount,
                        profit_amount=Decimal("0"),
                        ordered_at=row.ordered_at,
                    )
                )

            created, updated = self.sales.bulk_upsert(sales_to_upsert)
            return ImportResult(
                processed_rows=len(orders),
                created_sales=created,
                updated_sales=updated,
            )
