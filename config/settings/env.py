"""Environment loading and small parsing helpers for Django settings."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"


def load_environment() -> None:
    """Load local environment variables without overriding deployment values."""
    load_dotenv(ENV_FILE, override=False)


def get_bool(name: str, *, default: bool = False) -> bool:
    """Read a boolean environment variable with explicit accepted values."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_csv(name: str, *, default: tuple[str, ...] = ()) -> list[str]:
    """Read a comma-separated environment variable, excluding empty values."""
    value = os.getenv(name)
    if value is None:
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]