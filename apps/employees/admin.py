"""Django Admin presentation for employees."""

from django.contrib import admin

from apps.accounts.models import TelegramAccount
from apps.employees.models import Employee


class TelegramAccountInline(admin.TabularInline):
    model = TelegramAccount
    extra = 0
    readonly_fields = ("telegram_id", "username", "bound_at")
    can_delete = True


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("employee_id", "full_name", "group", "monthly_salary", "is_active", "updated_at")
    list_filter = ("is_active", "group")
    search_fields = ("employee_id", "full_name")
    list_select_related = ("group",)
    ordering = ("employee_id",)
    inlines = [TelegramAccountInline]
