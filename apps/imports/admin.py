"""Django Admin upload adapter for workbook imports."""

from django.contrib import admin, messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import path

from apps.common.services.exceptions import DomainError
from apps.imports.forms import WorkbookUploadForm
from apps.imports.models import ImportJob
from apps.imports.services.workbook import WorkbookImportService


@admin.register(ImportJob)
class ImportJobAdmin(admin.ModelAdmin):
    list_display = ("id", "workbook", "status", "processed_rows", "created_sales", "updated_sales", "created_at")
    list_filter = ("status", "created_at")
    readonly_fields = (
        "workbook", "checksum", "status", "uploaded_by", "processed_rows", "created_sales", "updated_sales",
        "error_details", "started_at", "completed_at", "created_at", "updated_at",
    )
    change_list_template = "admin/imports/importjob/change_list.html"

    def get_urls(self) -> list[object]:
        return [
            path("upload-workbook/", self.admin_site.admin_view(self.upload_workbook), name="imports_importjob_upload"),
        ] + super().get_urls()

    def upload_workbook(self, request: HttpRequest) -> HttpResponse:
        if request.method == "POST":
            form = WorkbookUploadForm(request.POST, request.FILES)
            if form.is_valid():
                service = WorkbookImportService()
                try:
                    job = service.create_job(workbook=form.cleaned_data["workbook"], uploaded_by=request.user)
                    service.process(job_id=job.pk)
                except DomainError as exc:
                    self.message_user(request, str(exc), level=messages.ERROR)
                else:
                    self.message_user(request, "Excel fayl muvaffaqiyatli import qilindi.", level=messages.SUCCESS)
                return redirect("..")
        else:
            form = WorkbookUploadForm()
        context = {**self.admin_site.each_context(request), "title": "Excel import", "form": form}
        return render(request, "admin/imports/importjob/upload.html", context)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: ImportJob | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: ImportJob | None = None) -> bool:
        return True

    def delete_model(self, request: HttpRequest, obj: ImportJob) -> None:
        self._cascade_delete([obj])

    def delete_queryset(self, request: HttpRequest, queryset: object) -> None:
        self._cascade_delete(list(queryset))

    @staticmethod
    def _cascade_delete(jobs: list[ImportJob]) -> None:
        from apps.employees.models import Employee
        from apps.groups.models import SalesGroup
        from apps.sales.models import Sale

        job_ids = [j.pk for j in jobs]

        # 1. Delete associated sales
        Sale.objects.filter(import_job_id__in=job_ids).delete()

        # 2. Delete the import jobs
        ImportJob.objects.filter(id__in=job_ids).delete()

        # 3. Delete any employees that have no sales left
        Employee.objects.filter(sales__isnull=True).delete()

        # 4. Clean up any empty sales groups
        SalesGroup.objects.filter(employees__isnull=True).delete()



