"""Django Admin presentation for Telegram bindings."""

from django.contrib import admin

from apps.accounts.models import TelegramAccount
from apps.groups.models import SalesGroup


@admin.register(TelegramAccount)
class TelegramAccountAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "telegram_id",
        "username",
        "employee",
        "is_leader_display",
        "has_credential_display",
        "rop_authenticated_at",
        "bound_at",
    )
    list_filter = ("bound_at", "employee__group")
    search_fields = ("telegram_id", "employee__employee_id", "employee__full_name", "username")
    list_select_related = ("employee",)
    readonly_fields = ("bound_at", "created_at", "updated_at")
    actions = ["delete_selected"]

    @admin.display(description="Guruh rahbari (Leader)", boolean=True)
    def is_leader_display(self, obj: TelegramAccount) -> bool:
        if not obj.employee:
            return False
        return SalesGroup.objects.filter(leader=obj.employee, is_active=True).exists()

    @admin.display(description="ROP parol mavjud (Cred)", boolean=True)
    def has_credential_display(self, obj: TelegramAccount) -> bool:
        if not obj.employee:
            return False
        return hasattr(obj.employee, "rop_credential") and obj.employee.rop_credential is not None
