# Sales Telegram Bot

Kompaniya savdo ma'lumotlarini PostgreSQL'da saqlash, Django Admin orqali
Excel'dan import qilish va Aiogram botda xodim hamda guruh statistikalarini
ko'rsatish uchun ichki platforma.

## Local ishga tushirish

1. Python 3.13 virtual environment yarating va dependency'larni o'rnating:

   ```bash
   python3.13 -m venv .venv
   source .venv/bin/activate
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

Admin panel: `http://127.0.0.1:8000/admin/`

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

- `/start` — Employee ID yuborish tartibini ko'rsatadi.
- `0191` — Telegram akkauntini xodimga bog'laydi.
- `/stats` — faqat o'z statistikasi.
- `/group_stats` — faqat rahbar bo'lgan guruh statistikasi va 2% bonus.

## REST API

Admin huquqiga ega autentifikatsiyalangan foydalanuvchilar uchun:

- `GET /api/v1/statistics/employees/<employee_id>/`
- `GET /api/v1/statistics/groups/by-telegram/<telegram_id>/`

Arxitektura va qatlamlar qoidalari [ARCHITECTURE.md](ARCHITECTURE.md) hamda
[docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md) fayllarida berilgan.
