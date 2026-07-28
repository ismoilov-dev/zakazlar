# Contabo VPS ga Telegram Bot va Django ilovasini Nginx orqali yuklash bo'yicha to'liq qo'llanma

Ushbu qo'llanmada loyihani Contabo VPS (Ubuntu Linux) serveriga **Docker-yisiz**, to'g'ridan-to'g'ri **Nginx + Gunicorn + Systemd + PostgreSQL** arxitekturasi yordamida maksimal tezkorlik bilan o'rnatish tartibi berilgan.

---

## ⚡ Qayta tezkor o'rnatish (Avtomatik 1-klik script)

### 1-qadam: SSH orqali Contabo VPS ga ulaning
```bash
ssh root@YOUR_CONTABO_IP
```

### 2-qadam: Loyihani serverdagi `/var/www/zakazlar` katalogiga yuklang
```bash
mkdir -p /var/www/zakazlar
cd /var/www/zakazlar
# Agar Git ishlatayotgan bo'lsangiz:
git clone <LOYIHA_GIT_URL> .
```

### 3-qadam: Environment variables (`.env`) sozlang
```bash
cp .env.example .env
nano .env
```
`nano` da quyidagi o'zgaruvchilarni o'z ma'lumotlaringizga almashtiring:
- `DJANGO_SECRET_KEY`: Murakkab tasodifiy kalit so'z.
- `DJANGO_ALLOWED_HOSTS`: Serveringiz IP manzili yoki domeningiz (masalan `161.97.xx.xx,yourdomain.com`).
- `DJANGO_CSRF_TRUSTED_ORIGINS`: `http://161.97.xx.xx` yoki `https://yourdomain.com`.
- `POSTGRES_DB`: Database nomi (masalan `sales_bot_db`).
- `POSTGRES_USER`: Database foydalanuvchisi (masalan `sales_bot_user`).
- `POSTGRES_PASSWORD`: Database paroli.
- `POSTGRES_HOST`: `127.0.0.1`
- `TELEGRAM_BOT_TOKEN`: BotFather bergan token.

Saqlash: `Ctrl+O` -> `Enter`, chiqish: `Ctrl+X`.

### 4-qadam: Avtomatik o'rnatuvchi scriptni ishga tushiring
```bash
sudo bash scripts/setup_contabo.sh
```
Ushbu script avtomatik ravishda:
1. System paketlarini yangilaydi hamda Python 3, PostgreSQL, Nginx paketlarini o'rnatadi.
2. PostgreSQL'da ma'lumotlar bazasi va foydalanuvchini yaratadi.
3. Python Virtual Environment (`.venv`) va barcha kutubxonalarni o'rnatadi.
4. Database migratsiyalarini bajaradi va statik fayllarni yig'adi.
5. Systemd Web (`zakazlar-web.service`) va Bot (`zakazlar-bot.service`) servislarini hamda Nginx'ni sozlab ishga tushiradi.

### 5-qadam: Admin panelga birinchi marta kirish tartibi
1. `.env` faylini to'ldiring (`DJANGO_USE_HTTPS=false`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_SECRET_KEY`, va hokazo).
2. Deploy holatini tekshiring:
   ```bash
   python manage.py check_deploy
   ```
3. Database migratsiyasini bajaring:
   ```bash
   python manage.py migrate --noinput
   ```
4. Cache jadvalini yarating:
   ```bash
   python manage.py createcachetable
   ```
5. Statik fayllarni yig'ing:
   ```bash
   python manage.py collectstatic --noinput
   ```
6. Superuser adminda foydalanuvchi yarating:
   ```bash
   python manage.py createsuperuser
   ```
7. Web xizmatini qayta ishga tushiring:
   ```bash
   systemctl restart zakazlar-web
   ```
8. Brauzerda Admin panelga kiring:
   `http://<IP>/panel/`


---

## ⚠️ JIDDIY XAVFSIZLIK OGOHLANTIRISHI (HTTP vs HTTPS)

> **DIQQAT:** `DJANGO_USE_HTTPS=false` holatida Admin panel HTTP orqali ishlaydi va parollar ochiq matnda uzatiladi. Bu faqat domen olingunga qadar **vaqtinchalik yechim** hisoblanadi.
> 
> Domen yo'naltirilib, SSL (Let's Encrypt) sertifikati o'rnatilgach, `.env` faylida **`DJANGO_USE_HTTPS=true`** qilinishi SHART!

---

## ⚙️ Systemd Servislari Konfiguratsiyasi

Serverda Web, Telegram Bot va Google Sheets Sinxronizatsiya daemon xizmatlari alohida Systemd unit'lari sifatida ishlaydi.

### 1. Web Servis (`/etc/systemd/system/zakazlar-web.service`)
```ini
[Unit]
Description=Zakazlar Django Web Application
After=network.target postgresql.service

[Service]
User=root
WorkingDirectory=/var/www/zakazlar
ExecStart=/var/www/zakazlar/venv/bin/gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 120
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 2. Telegram Bot Servis (`/etc/systemd/system/zakazlar-bot.service`)
```ini
[Unit]
Description=Zakazlar Telegram Bot Worker
After=network.target postgresql.service

[Service]
User=root
WorkingDirectory=/var/www/zakazlar
ExecStart=/var/www/zakazlar/venv/bin/python manage.py run_bot
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 3. Fon Sinxronizatsiya Daemon (`/etc/systemd/system/zakazlar-sync.service`)
```ini
[Unit]
Description=Zakazlar Live Google Sheets Sync Daemon
After=network.target postgresql.service

[Service]
User=root
WorkingDirectory=/var/www/zakazlar
ExecStart=/var/www/zakazlar/venv/bin/python manage.py sync_sheets --watch --interval 30
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Servislarni faollashtirish va ishga tushirish:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now zakazlar-web zakazlar-bot zakazlar-sync
```

---

## 🛠️ Boshqaruv va Monitoring Buyruqlari

### Servislar holatini ko'rish:
- **Django Web (Gunicorn):**
  ```bash
  systemctl status zakazlar-web
  ```
- **Telegram Bot worker:**
  ```bash
  systemctl status zakazlar-bot
  ```
- **Live Sync Daemon:**
  ```bash
  systemctl status zakazlar-sync
  ```
- **Nginx Web Server:**
  ```bash
  systemctl status nginx
  ```

### Loglarni (Xatolik va faoliyatni) real-vaqt rejimida kuzatish:
- **Bot loglarini ko'rish:**
  ```bash
  journalctl -u zakazlar-bot -f
  ```
- **Web loglarini ko'rish:**
  ```bash
  journalctl -u zakazlar-web -f
  ```
- **Sync loglarini ko'rish:**
  ```bash
  journalctl -u zakazlar-sync -f
  ```
- **Nginx xatolarini ko'rish:**
  ```bash
  tail -f /var/log/nginx/error.log
  ```

### Muammo bo'lganda ishlatiladigan diagnostika buyruqlari:
```bash
# Web servis holatini tekshirish
systemctl status zakazlar-web

# Web servisning oxirgi 50 qator loglarini ko'rish
journalctl -u zakazlar-web -n 50

# Nginx sintaksisini tekshirish
nginx -t

# Gunicorn lokal interfeysda ishlayotganini tekshirish
curl -I http://127.0.0.1:8005/panel/
```

### Servislarni qayta ishga tushirish (Update yuborilganda):
```bash
cd /var/www/zakazlar
git pull
./venv/bin/pip install -r requirements.txt
./venv/bin/python manage.py migrate --noinput
./venv/bin/python manage.py createcachetable
./venv/bin/python manage.py collectstatic --noinput
systemctl restart zakazlar-web zakazlar-bot zakazlar-sync
```

---

## 🔗 Google Apps Script Webhook Sozlash

Google Sheets o'zgarganda Django backendiga darhol `POST` signal yuborish uchun Google Sheet'dagi Apps Script (Extensions -> Apps Script) bo'limiga ushbu skriptni joylashtiring:

```javascript
function onSheetChange(e) {
  var url = "http://169.58.72.177/api/v1/imports/sheet-changed/";
  var secret = "YOUR_SHEETS_WEBHOOK_SECRET"; // .env dagi SHEETS_WEBHOOK_SECRET bilan bir xil bo'lsin
  
  var options = {
    "method": "post",
    "headers": {
      "X-Webhook-Secret": secret
    },
    "muteHttpExceptions": true
  };
  
  try {
    UrlFetchApp.fetch(url, options);
  } catch (err) {
    Logger.log("Webhook error: " + err);
  }
}
```

Trigger o'rnatish:
1. Apps Script interfeysida chap menyudagi ⏰ **Triggers** bo'limiga o'ting.
2. **Add Trigger** tugmasini bosing.
3. Choose function: `onSheetChange`.
4. Select event type: **On change**.
5. Saqlang va Google hisobingizga ruxsat bering.

---

## 🔒 Domeningizga Tekin SSL (HTTPS) Sertifikatini O'rnatish

Agar domeningizni server IP manziliga yo'naltirgan bo'lsangiz, tekin Let's Encrypt SSL sertifikatini ulash:

```bash
sudo apt update
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com
```

Certbot avtomatik ravishda Nginx konfiguratsiyasiga HTTPS sozlamalarini va avtomatik yangilanishni qo'shib beradi. Sertifikat o'rnatilgach `.env` da `DJANGO_USE_HTTPS=true` ga o'zgartiring va servislarni qayta ishga tushiring!

---

Barcha sozlamalar yakunlandi. Loyiha Nginx va Systemd yordamida Contabo VPS'da maksimal darajada tez va barqaror ishlaydi!

