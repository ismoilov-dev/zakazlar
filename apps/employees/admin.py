"""Django Admin presentation for employees."""

import secrets
from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts.models import TelegramAccount
from apps.employees.models import Employee, EmployeeMonthlyStat, RopCredential
from apps.groups.models import SalesGroup


class EmployeeAdminForm(forms.ModelForm):
    rop_password = forms.CharField(
        label="ROP uchun parol (ROP Password)",
        widget=forms.PasswordInput(render_value=False),
        required=False,
        help_text="Faqat ROP rahbarlari uchun. Yangi parol kiriting, saqlanganda shifrlanadi.",
    )

    class Meta:
        model = Employee
        fields = (
            "employee_id",
            "full_name",
            "monthly_salary",
            "summary_data",
            "group",
            "is_active",
            "rop_password",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            has_cred = hasattr(self.instance, "rop_credential") and self.instance.rop_credential is not None
            if has_cred:
                self.fields["rop_password"].help_text = "🔒 Parol o'rnatilgan. O'zgartirish uchun yangi parol kiriting."


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

    def clean_employee(self):
        employee = self.cleaned_data.get("employee")
        if employee:
            is_leader = SalesGroup.objects.filter(leader=employee, is_active=True).exists()
            if not is_leader:
                raise ValidationError("Faqat guruh rahbarlari (SalesGroup.leader) uchun parol o'rnatish mumkin.")
        return employee

    def save(self, commit=True):
        instance = super().save(commit=False)
        raw_password = self.cleaned_data.get("raw_password")
        if raw_password:
            instance.set_password(raw_password)
        if commit:
            instance.save()
        return instance


class TelegramAccountInline(admin.TabularInline):
    model = TelegramAccount
    extra = 0
    readonly_fields = ("telegram_id", "username", "bound_at")
    can_delete = True


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    form = EmployeeAdminForm
    list_display = ("employee_id", "full_name", "group", "monthly_salary", "is_active", "updated_at")
    list_filter = ("is_active", "group")
    search_fields = ("employee_id", "full_name")
    list_select_related = ("group",)
    ordering = ("employee_id",)
    fields = (
        "employee_id",
        "full_name",
        "monthly_salary",
        "summary_data",
        "group",
        "is_active",
        "rop_password",
    )
    inlines = [TelegramAccountInline]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        rop_password = form.cleaned_data.get("rop_password")
        if rop_password:
            cred, _ = RopCredential.objects.get_or_create(employee=obj)
            cred.set_password(rop_password)
            cred.save()
            messages.success(request, f"{obj.full_name} uchun ROP paroli muvaffaqiyatli saqlandi!")


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
    actions = [reset_rop_password_action]
    exclude = ("password",)
