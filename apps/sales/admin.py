"""Read-only Django Admin presentation for imported sales."""

from django.contrib import admin

from apps.sales.models import Sale


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ("external_order_id", "employee", "status", "source", "sale_amount", "profit_amount", "ordered_at")
    list_filter = ("status", "source", "ordered_at")
    search_fields = ("external_order_id", "employee__employee_id", "employee__full_name")
    list_select_related = ("employee", "import_job")
    date_hierarchy = "ordered_at"
    readonly_fields = (
        "external_order_id", "employee", "import_job", "status", "source", "sale_amount", "profit_amount", "ordered_at",
        "created_at", "updated_at",
    )

    def has_add_permission(self, request: object) -> bool:
        return False

    def has_change_permission(self, request: object, obj: Sale | None = None) -> bool:
        return False
