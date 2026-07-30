#!/bin/bash
set -e

echo "=================================================="
echo "  Contabo VPS Deployment Setup (Nginx + Systemd)  "
echo "=================================================="

# Dynamically determine project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

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
echo "[4/6] Python Virtual Environment (venv) yaratilmoqda va kutubxonalar o'rnatilmoqda..."
cd "$PROJECT_DIR"
VENV_DIR="$PROJECT_DIR/venv"
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi


PYTHON_BIN="$VENV_DIR/bin/python"
PIP_BIN="$VENV_DIR/bin/pip"
GUNICORN_BIN="$VENV_DIR/bin/gunicorn"

"$PIP_BIN" install --upgrade pip
"$PIP_BIN" install -r requirements.txt

# 5. Database Migration & Collectstatic
echo "[5/6] Database migratsiyalari o'tkazilmoqda va statik fayllar yig'ilmoqda..."
"$PYTHON_BIN" manage.py migrate --noinput
"$PYTHON_BIN" manage.py createcachetable || true
"$PYTHON_BIN" manage.py collectstatic --noinput

# 6. Configure Nginx and Systemd Services
echo "[6/6] Nginx va Systemd servislari sozlanmoqda..."
echo "⚠️ OGOHLANTIRISH: Ushbu serverda boshqa Nginx saytlari ham bo'lishi mumkin. Skript ularning konfiguratsiyalariga tegmaydi va ularni o'chirmaydi."

NGINX_PORT="${1:-8080}"

# Generate Systemd Web service
cat <<EOF > /etc/systemd/system/zakazlar-web.service
[Unit]
Description=Zakazlar Django Gunicorn Web Service
After=network.target postgresql.service

[Service]
User=root
WorkingDirectory=$PROJECT_DIR
EnvironmentFile=$PROJECT_DIR/.env
ExecStart=$GUNICORN_BIN config.wsgi:application --bind 127.0.0.1:8005 --workers 2 --timeout 120
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# Generate Systemd Bot service
cat <<EOF > /etc/systemd/system/zakazlar-bot.service
[Unit]
Description=Zakazlar Telegram Bot Worker
After=network.target postgresql.service

[Service]
User=root
WorkingDirectory=$PROJECT_DIR
EnvironmentFile=$PROJECT_DIR/.env
ExecStart=$PYTHON_BIN manage.py run_bot
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# Generate Systemd Sync service
cat <<EOF > /etc/systemd/system/zakazlar-sync.service
[Unit]
Description=Zakazlar Live Google Sheets Sync Daemon
After=network.target postgresql.service

[Service]
User=root
WorkingDirectory=$PROJECT_DIR
EnvironmentFile=$PROJECT_DIR/.env
ExecStart=$PYTHON_BIN manage.py sync_sheets --watch --interval 30
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# Generate Nginx config
cat <<EOF > /etc/nginx/sites-available/zakazlar
server {
    listen $NGINX_PORT;
    listen [::]:$NGINX_PORT;
    server_name _;

    client_max_body_size 50M;

    location /static/ {
        alias $PROJECT_DIR/staticfiles/;
        expires 30d;
        add_header Cache-Control "public, no-transform";
    }

    location /media/ {
        alias $PROJECT_DIR/media/;
        expires 30d;
        add_header Cache-Control "public, no-transform";
    }

    location / {
        proxy_pass http://127.0.0.1:8005;

        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_redirect off;
    }
}
EOF

# Create symlink and test Nginx syntax
ln -sf /etc/nginx/sites-available/zakazlar /etc/nginx/sites-enabled/

if ! nginx -t; then
    echo "❌ XATOLIK: Nginx sintaksisida yoki konfiguratsiyasida xatolik yuz berdi (nginx -t yiqildi)."
    echo "Mumkin bo'lgan sabablar:"
    echo " - /etc/nginx/sites-enabled/ katalogidagi qaysidir faylda 'duplicate default server' yoki sintaktik xato bor."
    echo " - Port $NGINX_PORT band bo'lishi mumkin."
    echo "Iltimos, boshqa loyiha konfiguratsiyalarini tekshiring."
    rm -f /etc/nginx/sites-enabled/zakazlar
    exit 1
fi

# Enable & Reload/Restart Services
systemctl daemon-reload
systemctl enable zakazlar-web zakazlar-bot zakazlar-sync nginx
systemctl restart zakazlar-web zakazlar-bot zakazlar-sync
systemctl reload nginx

echo "=================================================="
echo "  Tabriklaymiz! Loyiha Nginx va Systemd orqali     "
echo "  muvaffaqiyatli ishga tushirildi!               "
echo "=================================================="
echo ""
echo "Django Admin superuser yaratish uchun buyruq:"
echo "  $PYTHON_BIN manage.py createsuperuser"
echo ""
echo "Servislar holatini ko'rish uchun buyruqlar:"
echo "  systemctl status zakazlar-web"
echo "  systemctl status zakazlar-bot"
echo "  systemctl status zakazlar-sync"
echo "  systemctl status nginx"
echo "=================================================="
