# Sales Telegram Bot

Kompaniya savdo ma'lumotlarini PostgreSQL'da saqlash, Django Admin orqali
Excel'dan import qilish va Aiogram botda xodim hamda guruh statistikalarini
ko'rsatish uchun ichki platforma.

## Local ishga tushirish

1. Python 3.13 virtual environment yarating va dependency'larni o'rnating:

   ```bash
   python3.13 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. `.env.example` nusxasidan `.env` yarating va barcha placeholder qiymatlarni
   to'ldiring. `.env` hech qachon Git'ga kiritilmaydi.

3. Local PostgreSQL serverda `.env`dagi user va database'ni yarating; user
   `public` schema uchun `USAGE` va `CREATE` huquqlariga ega bo'lishi kerak.

4. Migration va admin foydalanuvchisini yarating:

   ```bash
   python manage.py migrate
   python manage.py createsuperuser
   ```

5. Ikki alohida terminalda web va bot jarayonlarini ishga tushiring:

   ```bash
   python manage.py runserver
   python manage.py run_bot
   ```

Admin panel: `http://127.0.0.1:8000/panel/`


## Excel formati

Admin paneldagi **Imports → Excel yuklash** orqali `.xlsx` yuboring. Birinchi
sheet quyidagi sarlavhalarga ega bo'lishi shart:

```text
employee_id | employee_name | group_code | order_id | status | sale_amount | profit_amount | ordered_at
```

- `employee_id`: faqat raqam, masalan `0191`.
- `status`: `successful`, `cancelled` yoki `pending`.
- `ordered_at`: Excel datetime qiymati.
- `order_id`: noyob tashqi buyurtma raqami; qayta importda shu kalit bo'yicha
  savdo yangilanadi, yangi dublikat yaratilmaydi.

## Bot buyruqlari

- `/start` — Rol tanlash va Employee ID bog'lash jarayonini boshlaydi.
- `/stats` — Xizmatlar menyusi.
- `/shaxsiy` — Shaxsiy xizmatlar menyusi.
- `/rop` — ROP paneli (guruh rahbari uchun).
- `/chiqish` — ROP sessiyasidan chiqish.

## ROP oyligi hisoblash

Guruh rahbari (ROP) oyligi guruhdagi barcha faol xodimlarning **Uspeshka summasi** (`successful_sales`) yig'indisining 2% qismi (`ROP_SALARY_RATE`) sifatida hisoblanadi:
`ROP oyligi = SUM(guruhdagi Uspeshka summasi) × 0.02`

## REST API

Admin huquqiga ega autentifikatsiyalangan foydalanuvchilar uchun:

- `GET /api/v1/statistics/employees/<employee_id>/`
- `GET /api/v1/statistics/groups/by-telegram/<telegram_id>/`

Arxitektura va qatlamlar qoidalari [ARCHITECTURE.md](ARCHITECTURE.md) hamda
[docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md) fayllarida berilgan.

## Known limitations

- **Unverified Identity Binding**: Employee identity confirmation relies on user-typed name matching against `List2` records. While this prevents simple typos from binding to a colleague's account, it is not strong authentication. Anyone who knows a colleague's ID and full name could potentially bind to that record.
- **Intended Enhancements**: Phone verification via Telegram `request_contact` or explicit administrator approval is planned as the intended follow-up authentication layer.

## Contabo VPS ga Deploy Qilish

Contabo VPS serveriga Nginx, Gunicorn, PostgreSQL va Systemd orqali to'g'ridan-to'g me'morchilikda o'rnatish yo'riqnomasi [CONTABO_GUIDE.md](CONTABO_GUIDE.md) faylida keltirilgan.


