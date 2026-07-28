#!/bin/bash
set -e

echo "=== Running Database Migrations ==="
python manage.py migrate --noinput

echo "=== Creating Cache Table ==="
python manage.py createcachetable || true

echo "=== Collecting Static Files ==="
if ! python manage.py collectstatic --noinput; then
    echo "[ERROR] collectstatic bajarishda xatolik yuz berdi! Admin panel statik fayllari yig'ilmadi." >&2
    exit 1
fi


echo "=== Starting Telegram Bot ==="
python manage.py run_bot &

echo "=== Starting Gunicorn Web Server ==="
exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 120
