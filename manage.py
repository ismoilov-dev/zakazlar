#!/usr/bin/env python
"""Django management commands entry point."""

from __future__ import annotations

import os
import sys


def main() -> None:
    """Set the settings module and delegate to Django's command runner."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        message = (
            "Django could not be imported. Install the project's dependencies "
            "with Python 3.13 before running management commands."
        )
        raise ImportError(message) from exc

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
