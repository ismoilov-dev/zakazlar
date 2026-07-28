#!/bin/bash
set -e

echo "=================================================="
echo "  Contabo VPS Deployment Setup (Nginx + Systemd)  "
echo "=================================================="

PROJECT_DIR="/var/www/zakazlar"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo "Xatolik: ushbu scriptni root huquqlari bilan yurgizing (sudo bash scripts/setup_contabo.sh)"
  exit 1
fi

# 1. Update packages and install python, postgresql, nginx
echo "[1/6] System paketlari hamda Nginx, PostgreSQL, Python o'rnatilmoqda..."
apt update && apt upgrade -y
apt install -y python3 python3-venv python3-pip postgresql postgresql-contrib nginx curl git

# 2. Check .env file
if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo "[2/6] .env fayli topilmadi. .env.example nusxasidan yaratilmoqda..."
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    echo "⚠️ Eslatma: .env faylini ochib o'z ma'lumotlaringizni to'ldiring!"
fi

# Load variables from .env if present
if [ -f "$PROJECT_DIR/.env" ]; then
    export $(grep -v '^#' "$PROJECT_DIR/.env" | xargs)
fi

# 3. Configure PostgreSQL Database & User
DB_NAME="${POSTGRES_DB:-sales_bot_db}"
DB_USER="${POSTGRES_USER:-sales_bot_user}"
DB_PASS="${POSTGRES_PASSWORD:-sales_bot_pass_123}"

echo "[3/6] PostgreSQL bazasi ($DB_NAME) va foydalanuvchi ($DB_USER) tekshirilmoqda..."
sudo -u postgres psql -tc "SELECT 1 FROM pg_user WHERE usename = '$DB_USER'" | grep -q 1 || \
sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';"

sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'" | grep -q 1 || \
sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;"

sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;"

# 4. Setup Python Virtual Environment
echo "[4/6] Python Virtual Environment (.venv) yaratilmoqda va kutubxonalar o'rnatilmoqda..."
cd "$PROJECT_DIR"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt

# 5. Database Migration & Collectstatic
echo "[5/6] Database migratsiyalari o'tkazilmoqda va statik fayllar yig'ilmoqda..."
python manage.py migrate --noinput
python manage.py createcachetable
python manage.py collectstatic --noinput

# 6. Configure Nginx and Systemd Services
echo "[6/6] Nginx va Systemd servislari sozlanmoqda..."

# Systemd Web service
cp deploy/systemd/zakazlar-web.service /etc/systemd/system/
# Systemd Bot service
cp deploy/systemd/zakazlar-bot.service /etc/systemd/system/
# Systemd Sync service
if [ -f "deploy/systemd/zakazlar-sync.service" ]; then
    cp deploy/systemd/zakazlar-sync.service /etc/systemd/system/
fi

# Nginx config
cp deploy/nginx.conf /etc/nginx/sites-available/zakazlar
ln -sf /etc/nginx/sites-available/zakazlar /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# Test Nginx syntax
nginx -t

# Enable & Restart Services
systemctl daemon-reload
systemctl enable zakazlar-web zakazlar-bot zakazlar-sync nginx || systemctl enable zakazlar-web zakazlar-bot nginx
systemctl restart zakazlar-web zakazlar-bot zakazlar-sync nginx || systemctl restart zakazlar-web zakazlar-bot nginx


echo "=================================================="
echo "  Tabriklaymiz! Loyiha Nginx va Systemd orqali     "
echo "  muvaffaqiyatli ishga tushirildi!               "
echo "=================================================="
echo ""
echo "Django Admin superuser yaratish uchun buyruq:"
echo "  /var/www/zakazlar/.venv/bin/python manage.py createsuperuser"
echo ""
echo "Servislar holatini ko'rish uchun buyruqlar:"
echo "  systemctl status zakazlar-web"
echo "  systemctl status zakazlar-bot"
echo "  systemctl status nginx"
echo "=================================================="
