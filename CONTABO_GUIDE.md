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

### 5-qadam: Admin foydalanuvchisini yaratish
```bash
/var/www/zakazlar/.venv/bin/python manage.py createsuperuser
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
- **Nginx xatolarini ko'rish:**
  ```bash
  tail -f /var/log/nginx/error.log
  ```

### Servislarni qayta ishga tushirish (Update yuborilganda):
```bash
cd /var/www/zakazlar
git pull
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python manage.py migrate --noinput
./.venv/bin/python manage.py collectstatic --noinput
systemctl restart zakazlar-web zakazlar-bot
```

---

## 🔒 Domeningizga Tekin SSL (HTTPS) Sertifikatini O'rnatish

Agar domeningizni server IP manziliga yo'naltirgan bo'lsangiz, tekin Let's Encrypt SSL sertifikatini ulash:

```bash
sudo apt update
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com
```

Certbot avtomatik ravishda Nginx konfiguratsiyasiga HTTPS sozlamalarini va avtomatik yangilanishni qo'shib beradi.

---

Barcha sozlamalar yakunlandi. Loyiha Nginx va Systemd yordamida Contabo VPS'da maksimal darajada tez va barqaror ishlaydi!
