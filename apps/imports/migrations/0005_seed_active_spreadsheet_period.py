import os
from datetime import date
from django.conf import settings
from django.db import migrations


def seed_active_period(apps, schema_editor):
    SpreadsheetPeriod = apps.get_model("imports", "SpreadsheetPeriod")
    if SpreadsheetPeriod.objects.filter(is_active=True).exists():
        return

    sheet_id = (getattr(settings, "GOOGLE_SHEET_ID", "") or os.environ.get("GOOGLE_SHEET_ID") or "").strip().strip("/")
    if not sheet_id:
        return

    today = date.today()
    period_date = date(today.year, today.month, 1)

    SpreadsheetPeriod.objects.create(
        period=period_date,
        spreadsheet_id=sheet_id,
        spreadsheet_url=f"https://docs.google.com/spreadsheets/d/{sheet_id}",
        is_active=True,
        note="Seeded from GOOGLE_SHEET_ID on migration",
    )


def reverse_seed(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0004_spreadsheetperiod"),
    ]

    operations = [
        migrations.RunPython(seed_active_period, reverse_code=reverse_seed),
    ]
