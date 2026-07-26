# Sales Telegram Bot — loyiha arxitekturasi

## Maqsad

Excel savdo hisobotlarini Django Admin orqali import qilib, ularni PostgreSQL'da
saqlash va xodimlar hamda guruh rahbarlariga Telegram bot orqali tezkor,
ruxsatga asoslangan statistika ko'rsatish.

## Asosiy qarorlar

- **Modulli Django monolith** tanlanadi. 200+ bir vaqtdagi foydalanuvchi uchun
  bu soddaroq, kuzatish oson va yetarlicha samarali. Keyinchalik komponentlarni
  mustaqil servisga ajratish mumkin.
- Bitta Docker image'dan uchta alohida jarayon ishlaydi: `web` (Django/DRF),
  `bot` (Aiogram polling) va zarurat bo'lsa import worker. Ular bir xil Django
  kod bazasi va PostgreSQL sxemasidan foydalanadi.
- Excel — faqat import kirish formati. U yuklanganidan va tekshirilganidan so'ng
  biznes ma'lumotlarning yagona manbasi PostgreSQL bo'ladi. Bot Excel faylini
  ochmaydi, yuklamaydi yoki tahlil qilmaydi.
- Bot ham, REST API ham bitta application/service qatlamidan foydalanadi.
  Bot o'z API'siga HTTP so'rov yubormaydi; Django ORM orqali servisga murojaat
  qiladi. Bu ortiqcha tarmoq kechikishini yo'qotadi va biznes qoidalarni yagona
  joyda saqlaydi.
- Pul qiymatlari `Decimal`/PostgreSQL `NUMERIC` ko'rinishida saqlanadi; `float`
  ishlatilmaydi.

## Komponentlar va ma'lumot oqimi

```text
Django Admin
    │ .xlsx upload
    ▼
Import application
    ├─ fayl sxemasi va satrlarni tekshiradi
    ├─ import natijasini/auditini saqlaydi
    └─ transaction + batch upsert
              │
              ▼
        PostgreSQL  ◄────────── DRF API
              ▲                       ▲
              │                       │
        Statistics service       tashqi admin/kelajak UI
              ▲
              │
       Aiogram bot process
              │
       Telegram xodim/rahbar
```

## Qatlamlar (Clean Architecture)

Har Django app ichida mas'uliyat quyidagicha ajratiladi:

| Qatlam | Vazifasi | Misollar |
|---|---|---|
| Presentation | Tashqi kirish nuqtasi; qoidalarni hisoblamaydi | Django Admin, DRF view/serializer, Aiogram handler |
| Application | Use-case va tranzaksiya orkestratsiyasi | `ImportSalesWorkbook`, `GetEmployeeDashboard`, `GetTeamDashboard` |
| Domain | Biznes qoidalari va qiymat obyektlari | bonus hisoblash, rollar, statistika DTOlari |
| Infrastructure | Django ORM, Excel parser, Telegram adapteri | repository/query implementations, `openpyxl` adapter |

Views, admin actions va Telegram handlerlar yupqa bo'ladi: ular kirishni
tekshiradi, application servisni chaqiradi va natijani formatlaydi. Import va
hisoblash logikasi handler yoki model `save()` metodlariga joylashtirilmaydi.

## Dastlabki bounded contextlar

- **employees** — xodim, Employee ID, Telegram akkaunt bog'lanishi va rol.
- **teams** — guruh va rahbar tayinlanishi.
- **sales** — import qilingan savdo satrlari yoki hisobot davri ma'lumotlari.
- **imports** — yuklangan fayl, import holati, xatolar va audit.
- **reporting** — xodim/guruh statistikasi va bonus use-case'lari.
- **api** — DRF endpointlari va ularning serializatorlari.
- **bot** — Aiogram dispatcher, router, handler va Telegram taqdimot qatlami.

Model va indekslarning aniq tarkibi 5-bosqichda belgilanadi.

## Statistik va ruxsat qoidalari

- Xodim faqat o'z `Employee ID`iga tegishli statistikani ko'radi.
- Rahbar faqat o'zi rahbar bo'lgan guruh bo'yicha agregatlarni ko'radi.
- Guruh bonusi = guruhning muvaffaqiyatli savdolaridan olingan umumiy foyda ×
  `0.02`. Stavka konfiguratsiyalanadigan `Decimal` qiymat sifatida saqlanadi.
- Rahbar sotuvchi bo'lsa, shaxsiy savdo foydasi va rahbarlik bonusi ikkita
  mustaqil satr sifatida qaytariladi; ular avtomatik qo'shib yuborilmaydi.
- Telegram `user_id` xodimga bog'lanadi. Employee ID yolg'iz o'zi maxfiy
  autentifikatsiya omili emasligi sabab, productionda admin beradigan PIN yoki
  bir martalik tasdiqlash kodi qo'shilishi tavsiya etiladi. Birinchi MVP'da
  bog'lanishni admin qayta tiklashi mumkin.

## Ishlash va ishonchlilik

- `Employee.employee_id` uchun unique indeks, savdo qidiruvlari uchun xodim,
  guruh va davrga mos composite indekslar qo'yiladi.
- Guruh statistikasi PostgreSQL aggregation (`SUM`, `COUNT`, filtrlangan
  aggregate) bilan hisoblanadi; Python'da minglab savdo satrlari yuklanmaydi.
- Excel import satrma-satr validatsiya qilinadi, xatolar import jurnalida
  yoziladi va ma'lumotlar `transaction.atomic()` ichida batch usulda yoziladi.
- Import idempotent bo'ladi: fayl hash'i va biznes kaliti orqali bir faylni
  qayta yuklash dublikat savdo yaratmaydi.
- Aiogram async handlerlari Django'ning sinxron ORM chaqiruvini xavfsiz adapter
  orqali bajaradi. Har so'rov qisqa, indekslangan querylarga tayanadi.
- Redis keyingi bosqichda rate-limit, qisqa TTL cache, FSM state va fon
  vazifalari uchun qo'shiladi; hozir u biznes ma'lumotlar manbasi emas.

## Konfiguratsiya va xavfsizlik

- Maxfiy qiymatlar faqat environment variable'larda: `DJANGO_SECRET_KEY`,
  `DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `DJANGO_DEBUG`.
- `.env` Git'ga kiritilmaydi; `.env.example` kiritiladi.
- Django Admin upload huquqi faqat `is_staff` foydalanuvchilariga beriladi.
- Import fayli turi, o'lchami, sarlavhalari va qiymatlari tekshiriladi.
- Muhim amallar (import, Telegram binding, ruxsat o'zgarishi) audit logga
  yoziladi.

## Joylashtirish ko'rinishi

```text
Docker Compose
  ├─ postgres       (persistent volume)
  ├─ web            (Django Admin + DRF, Gunicorn)
  ├─ bot            (Aiogram long polling)
  └─ redis          (keyingi bosqichda yoqiladi)
```

Webhook kerak bo'lganda bot polling'dan webhook'ga o'zgarishi mumkin; handler
va use-case'lar o'zgarmaydi.
