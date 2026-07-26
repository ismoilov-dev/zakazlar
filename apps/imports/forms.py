"""Django Admin input forms for workbook upload."""

from django import forms


class WorkbookUploadForm(forms.Form):
    """Accept a single Excel workbook through Django Admin."""

    workbook = forms.FileField(allow_empty_file=False)
