"""Tests for check_deploy management command."""

from __future__ import annotations

import io
import os
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.test import TestCase


class CheckDeployCommandTestCase(TestCase):
    def setUp(self):
        self.env_override = {
            "DJANGO_SECRET_KEY": "test-secret-key",
            "DJANGO_USE_HTTPS": "false",
            "DJANGO_ALLOWED_HOSTS": "localhost",
            "TELEGRAM_BOT_TOKEN": "123456:ABC",
            "GOOGLE_SHEET_ID": "sheet_123",
            "GOOGLE_SERVICE_ACCOUNT_FILE": "credentials/service_account.json",
        }

    def test_missing_mandatory_env_var_fails(self):
        env = self.env_override.copy()
        del env["TELEGRAM_BOT_TOKEN"]

        out = io.StringIO()
        err = io.StringIO()
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(CommandError):
                call_command("check_deploy", stdout=out, stderr=err)

        output = err.getvalue() + out.getvalue()
        self.assertIn("TELEGRAM_BOT_TOKEN", output)

    def test_missing_google_creds_fails(self):
        env = self.env_override.copy()
        del env["GOOGLE_SERVICE_ACCOUNT_FILE"]

        out = io.StringIO()
        err = io.StringIO()
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(CommandError):
                call_command("check_deploy", stdout=out, stderr=err)

        output = err.getvalue() + out.getvalue()
        self.assertIn("GOOGLE_SERVICE_ACCOUNT", output)
