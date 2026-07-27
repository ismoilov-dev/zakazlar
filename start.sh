#!/bin/bash
set -e

echo "=== Running Database Migrations ==="
python manage.py migrate --noinput

echo "=== Collecting Static Files ==="
python manage.py collectstatic --noinput

echo "=== Starting Telegram Bot ==="
python manage.py run_bot &

echo "=== Starting Gunicorn Web Server ==="
exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 120
