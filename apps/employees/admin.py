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


from django.utils import timezone

from apps.employees.models import EmployeeMonthlyStat


@admin.action(description="Tanlangan oylik statlarni yopish (Close period)")
def close_selected_monthly_stats(modeladmin, request, queryset):
    updated = queryset.update(
        is_closed=True,
        closed_at=timezone.now(),
        closed_by=request.user if request.user and request.user.is_authenticated else None,
    )
    modeladmin.message_user(request, f"{updated} ta oylik statistika yopildi.")


@admin.action(description="Tanlangan oylik statlarni qayta ochish (Reopen period)")
def reopen_selected_monthly_stats(modeladmin, request, queryset):
    updated = queryset.update(
        is_closed=False,
        closed_at=None,
        closed_by=None,
    )
    modeladmin.message_user(request, f"{updated} ta oylik statistika qayta ochildi.")


@admin.register(EmployeeMonthlyStat)
class EmployeeMonthlyStatAdmin(admin.ModelAdmin):
    list_display = ("employee", "period", "is_closed", "closed_at", "closed_by", "source_spreadsheet_id", "updated_at")
    list_filter = ("is_closed", "period", "employee__group")
    search_fields = ("employee__employee_id", "employee__full_name")
    actions = [close_selected_monthly_stats, reopen_selected_monthly_stats]
    readonly_fields = ("closed_at", "closed_by")

