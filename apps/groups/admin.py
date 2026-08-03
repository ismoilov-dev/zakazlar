"""Django Admin presentation for sales groups."""

from django.contrib import admin

from apps.groups.models import SalesGroup


@admin.register(SalesGroup)
class SalesGroupAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "leader", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("code", "name", "leader__employee_id", "leader__full_name")
    list_select_related = ("leader",)
    autocomplete_fields = ("leader",)

