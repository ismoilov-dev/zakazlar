"""Throwaway management command to discover Google Sheets structure and raw data types."""

from __future__ import annotations

import json
import os
from typing import Any

from django.core.management.base import BaseCommand, CommandError
import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def clean_sheet_id(raw_id: str) -> str:
    """Extract clean Google Sheet ID from raw env string or full URL."""
    s = raw_id.strip()
    if "/d/" in s:
        s = s.split("/d/")[1].split("/")[0]
    return s.strip("/ ")


def get_gspread_client() -> gspread.Client:
    """Authenticate gspread using JSON string or service account file."""
    json_str = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if json_str and json_str.strip():
        try:
            info = json.loads(json_str)
            creds = Credentials.from_service_account_info(info, scopes=SCOPES)
            return gspread.authorize(creds)
        except Exception as exc:
            raise CommandError(f"Failed to parse GOOGLE_SERVICE_ACCOUNT_JSON: {exc}") from exc

    file_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials/service-account.json")
    if file_path and os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        try:
            creds = Credentials.from_service_account_file(file_path, scopes=SCOPES)
            return gspread.authorize(creds)
        except Exception as exc:
            raise CommandError(f"Failed to load GOOGLE_SERVICE_ACCOUNT_FILE ({file_path}): {exc}") from exc

    raise CommandError(
        "No valid Google Service Account credentials found. "
        "Provide raw JSON in GOOGLE_SERVICE_ACCOUNT_JSON or a non-empty file at GOOGLE_SERVICE_ACCOUNT_FILE."
    )


class Command(BaseCommand):
    help = "Discover Google Sheets worksheets, header names, and raw cell values/types."

    def handle(self, *args: Any, **options: Any) -> None:
        sheet_id_raw = os.getenv("GOOGLE_SHEET_ID", "")
        if not sheet_id_raw:
            raise CommandError("GOOGLE_SHEET_ID environment variable is not set.")

        sheet_id = clean_sheet_id(sheet_id_raw)
        self.stdout.write(f"Connecting to Google Sheet ID: {sheet_id}")

        gc = get_gspread_client()

        try:
            spreadsheet = gc.open_by_key(sheet_id)
        except Exception as exc:
            raise CommandError(f"Unable to open spreadsheet '{sheet_id}': {exc}") from exc

        worksheets = spreadsheet.worksheets()
        titles = [ws.title for ws in worksheets]
        self.stdout.write(self.style.SUCCESS(f"\nWorksheets found ({len(titles)}): {titles}"))

        target_tabs = ["Ish haqi", "List1"]
        for tab_name in target_tabs:
            self.stdout.write("\n" + "=" * 60)
            self.stdout.write(self.style.MIGRATE_HEADING(f"TAB: '{tab_name}'"))
            self.stdout.write("=" * 60)

            matching_ws = next((ws for ws in worksheets if ws.title.strip().lower() == tab_name.strip().lower()), None)

            if not matching_ws:
                self.stdout.write(self.style.WARNING(f"Tab '{tab_name}' not found in spreadsheet."))
                continue

            # Fetch raw values (formatted vs unformatted)
            try:
                raw_values = matching_ws.get_all_values()[:5]
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"Error fetching values for tab '{tab_name}': {exc}"))
                continue

            if not raw_values:
                self.stdout.write("Tab is empty.")
                continue

            self.stdout.write(f"First {len(raw_values)} raw rows:")
            for row_idx, row in enumerate(raw_values, start=1):
                cell_details = [f"{repr(cell)} ({type(cell).__name__})" for cell in row]
                self.stdout.write(f"  Row {row_idx}: [{', '.join(cell_details)}]")

            # Also fetch unformatted raw API values for detailed inspection
            try:
                unformatted_resp = matching_ws.get("A1:Z5", value_render_option="UNFORMATTED_VALUE")
                self.stdout.write("\nUnformatted API values (UNFORMATTED_VALUE option):")
                for row_idx, row in enumerate(unformatted_resp, start=1):
                    cell_details = [f"{repr(cell)} ({type(cell).__name__})" for cell in row]
                    self.stdout.write(f"  Row {row_idx}: [{', '.join(cell_details)}]")
            except Exception as exc:
                self.stdout.write(f"Could not fetch UNFORMATTED_VALUE: {exc}")
