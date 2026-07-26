"""Django Admin presentation for Telegram bindings."""

from django.contrib import admin

from apps.accounts.models import TelegramAccount


@admin.register(TelegramAccount)
class TelegramAccountAdmin(admin.ModelAdmin):
    list_display = ("telegram_id", "employee", "username", "bound_at")
    search_fields = ("telegram_id", "employee__employee_id", "employee__full_name", "username")
    list_select_related = ("employee",)
    readonly_fields = ("bound_at", "created_at", "updated_at")
