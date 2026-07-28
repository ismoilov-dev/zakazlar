"""Management command to check deployment prerequisites and environment configuration."""

from __future__ import annotations

import os
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Deployment holatini va zaruriy muhit o'zgaruvchilarini tekshirish."

    def handle(self, *args, **options):
        errors: list[str] = []
        warnings: list[str] = []
        successes: list[str] = []

        required_env_vars = [
            ("DJANGO_SECRET_KEY", "DJANGO_SECRET_KEY .env faylida o'rnatilishi shart."),
            ("DJANGO_USE_HTTPS", "DJANGO_USE_HTTPS .env faylida o'rnatilishi shart (true yoki false)."),
            ("DJANGO_ALLOWED_HOSTS", "DJANGO_ALLOWED_HOSTS .env faylida ko'rsatilishi shart."),
            ("TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_TOKEN .env faylida ko'rsatilishi shart."),
            ("GOOGLE_SHEET_ID", "GOOGLE_SHEET_ID .env faylida ko'rsatilishi shart."),
        ]

        for var_name, fix_msg in required_env_vars:
            val = os.getenv(var_name)
            if not val or not val.strip():
                errors.append(f"[X] {var_name} o'rnatilmagan: {fix_msg}")
            else:
                successes.append(f"[OK] {var_name}")

        json_creds = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        file_creds = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
        if not (json_creds and json_creds.strip()) and not (file_creds and file_creds.strip()):
            errors.append(
                "[X] GOOGLE_SERVICE_ACCOUNT_JSON yoki GOOGLE_SERVICE_ACCOUNT_FILE o'rnatilmagan: "
                ".env faylida kamida bittasini ko'rsating."
            )
        else:
            successes.append("[OK] Google Service Account credentials")

        https_val = os.getenv("DJANGO_USE_HTTPS", "").strip().lower()
        if https_val in {"false", "0", "no", "off"}:
            warnings.append(
                "[!] DJANGO_USE_HTTPS=false ogohlantirish: Parollar HTTP orqali ochiq matnda uzatiladi."
            )

        static_root = getattr(settings, "STATIC_ROOT", None)
        if static_root and Path(static_root).exists():
            successes.append("[OK] STATIC_ROOT papkasi mavjud.")
        else:
            errors.append(
                f"[X] STATIC_ROOT papkasi ({static_root}) mavjud emas: 'python manage.py collectstatic' bajarilishi kerak."
            )

        try:
            tables = connection.introspection.table_names()
            if "sync_cache" in tables:
                successes.append("[OK] Cache jadvali ('sync_cache') mavjud.")
            else:
                errors.append(
                    "[X] Cache jadvali ('sync_cache') mavjud emas: 'python manage.py createcachetable' bajarilishi kerak."
                )
        except Exception as exc:
            errors.append(f"[X] Cache jadvalini tekshirishda xatolik: {exc}")

        try:
            User = get_user_model()
            if User.objects.filter(is_superuser=True).exists():
                successes.append("[OK] Superuser mavjud.")
            else:
                errors.append(
                    "[X] Superuser mavjud emas: 'python manage.py createsuperuser' bajarilishi kerak."
                )
        except Exception as exc:
            errors.append(f"[X] Superuserlarni tekshirishda xatolik: {exc}")

        self.stdout.write("--- DEPLOYMENT TEKSHIRUVI NATIJALARI ---")
        for succ in successes:
            self.stdout.write(self.style.SUCCESS(succ))
        for warn in warnings:
            self.stdout.write(self.style.WARNING(warn))
        for err in errors:
            self.stderr.write(self.style.ERROR(err))

        if errors:
            raise CommandError(f"Deployment tekshiruvi muvaffaqiyatsiz tugadi ({len(errors)} ta xatolik).")
