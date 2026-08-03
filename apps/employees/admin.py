"""Django Admin presentation for employees."""

import secrets
from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts.models import TelegramAccount
from apps.employees.models import Employee, EmployeeMonthlyStat, RopCredential
from apps.groups.models import SalesGroup


class RopCredentialAdminForm(forms.ModelForm):
    raw_password = forms.CharField(
        label="Yangi parol (Plaintext Password)",
        widget=forms.PasswordInput(render_value=False),
        required=False,
        help_text="Yangi parol kiriting. Saqlanganda avtomatik hashlanadi.",
    )

    class Meta:
        model = RopCredential
        fields = ("employee", "raw_password")

    def clean(self):
        cleaned_data = super().clean()
        employee = cleaned_data.get("employee")
        if not employee and hasattr(self, "instance") and getattr(self.instance, "employee", None):
            employee = self.instance.employee

        if employee:
            is_leader = SalesGroup.objects.filter(leader=employee, is_active=True).exists()
            if not is_leader:
                self.add_error("employee", "Faqat guruh rahbarlari (SalesGroup.leader) uchun parol o'rnatish mumkin.")
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        raw_password = self.cleaned_data.get("raw_password")
        if raw_password:
            instance.set_password(raw_password)
        if commit:
            instance.save()
        return instance


class RopCredentialInline(admin.StackedInline):
    model = RopCredential
    form = RopCredentialAdminForm
    extra = 0
    max_num = 1
    fields = ("raw_password",)


class TelegramAccountInline(admin.TabularInline):
    model = TelegramAccount
    extra = 0
    readonly_fields = ("telegram_id", "username", "bound_at")
    can_delete = True


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("employee_id", "full_name", "group", "monthly_salary", "has_rop_credential", "is_active", "updated_at")
    list_filter = ("is_active", "group")
    search_fields = ("employee_id", "full_name")
    list_select_related = ("group",)
    autocomplete_fields = ("group",)
    ordering = ("employee_id",)
    fields = (
        "employee_id",
        "full_name",
        "monthly_salary",
        "summary_data",
        "group",
        "is_active",
    )
    inlines = [RopCredentialInline, TelegramAccountInline]

    @admin.display(boolean=True, description="ROP Paroli")
    def has_rop_credential(self, obj: Employee) -> bool:
        return hasattr(obj, "rop_credential") and obj.rop_credential is not None


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


def check_unclosed_historical_periods_and_warn(request) -> None:
    try:
        from apps.imports.models import SpreadsheetPeriod
        active_sp = SpreadsheetPeriod.objects.filter(is_active=True).first()
        if not active_sp:
            return
        unclosed_periods = (
            EmployeeMonthlyStat.objects.filter(period__lt=active_sp.period, is_closed=False)
            .values_list("period", flat=True)
            .distinct()
            .order_by("period")
        )
        if unclosed_periods:
            periods_str = ", ".join(p.strftime("%m.%Y") for p in unclosed_periods)
            messages.warning(
                request,
                f"⚠️ Diqqat: Faol oydan ({active_sp.period.strftime('%m.%Y')}) oldingi yopilmagan oylik statistikalar mavjud: {periods_str}. Iltimos, u ushbu oylarni yoping.",
            )
    except Exception:
        pass


@admin.register(EmployeeMonthlyStat)
class EmployeeMonthlyStatAdmin(admin.ModelAdmin):
    list_display = ("employee", "period", "is_closed", "closed_at", "closed_by", "source_spreadsheet_id", "updated_at")
    list_filter = ("is_closed", "period", "employee__group")
    search_fields = ("employee__employee_id", "employee__full_name")
    autocomplete_fields = ("employee",)
    actions = [close_selected_monthly_stats, reopen_selected_monthly_stats]
    readonly_fields = ("closed_at", "closed_by")

    def changelist_view(self, request, extra_context=None):
        check_unclosed_historical_periods_and_warn(request)
        return super().changelist_view(request, extra_context=extra_context)


@admin.action(description="Parolni tiklash (Reset Password)")
def reset_rop_password_action(modeladmin, request, queryset):
    for cred in queryset:
        new_password = secrets.token_urlsafe(10)
        cred.set_password(new_password)
        cred.save(update_fields=["password", "updated_at"])
        modeladmin.message_user(
            request,
            f"Xodim {cred.employee.full_name} ({cred.employee.employee_id}) uchun yangi parol tiklandi: {new_password}",
            level=messages.SUCCESS,
        )


@admin.register(RopCredential)
class RopCredentialAdmin(admin.ModelAdmin):
    form = RopCredentialAdminForm
    list_display = ("employee", "updated_at")
    search_fields = ("employee__employee_id", "employee__full_name")
    autocomplete_fields = ("employee",)
    actions = [reset_rop_password_action]
    exclude = ("password",)
