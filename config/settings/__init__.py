"""Select the Django settings profile from the environment."""

from __future__ import annotations

import os

from .env import load_environment

load_environment()

environment = os.getenv("DJANGO_ENV", "development").strip().lower()

if environment == "production":
    from .production import *  # noqa: F403
elif environment == "development":
    from .development import *  # noqa: F403
else:
    message = "DJANGO_ENV must be either 'development' or 'production'."
    raise RuntimeError(message)
