# Kunlik video tahlil (NVR yozuvlari asosida)

## Nima uchun

Real vaqt rejimida har bir kamera kun bo'yi uzluksiz tahlil qilinardi: 107 ta
kamera, har 30 soniyada yuz aniqlash, kirish kameralarida doimiy kuzatuvchilar.
Server (GPU yo'q, AVX'siz CPU) bu yukni ko'tara olmadi — navbatlar to'lib,
natija kechikardi.

Yangi rejimda (`ANALYSIS_MODE=kunlik`, standart) kun davomida AI ishlamaydi.
Kun tugagach (standart 20:00) tizim NVR qattiq diskidagi o'sha kunning
yozuvlarini oladi va har bir xodim va talaba bo'yicha barcha kriteriyalarni
hisoblaydi. Jonli video ko'rish (MediaMTX) o'zgarmaydi, faqat ustidagi yuz
ramkalari o'chadi (ular har kadrda tahlil talab qilardi).

## Kriteriyalar (buyurtmachi ro'yxati, 2026-10-04)

| № | Kriteriya | Qanday hisoblanadi | Qayerga yoziladi |
|---|-----------|--------------------|------------------|
| 6 | Xodim/o'qituvchi davomati | Kirish/chiqish kameralari 07:00–20:00 uzluksiz (tig'iz soatda 2 kadr/s, qolgan vaqtda 1 kadr/s, harakatsiz kadrlar tashlab o'tiladi); kunning birinchi va oxirgi ishonchli ko'rinishi | `attendance_records`, `presence_visits` |
| 7 | Talaba davomati | Xuddi shu + dars xonalari; darsda kamida 2 alohida klipda tanilgan talaba darsda bo'lgan | `attendance_records`, `lesson_attendance` |
| 8 | Darsga kechikish | Boshlanishdan −10…+20 daqiqa, har daqiqada 3 s klip; birinchi ko'rinish boshlanish + 5 daqiqadan keyin **va** kamera bu oraliqni haqiqatan ko'rgan | `lesson_attendance.status` |
| 9 | Darsdan/ishdan erta ketish | Darsning oxirgi 15 daqiqasi har daqiqada; ishdan — `early_leave_verdict` (oxirgi chiqish, kamida 2 ko'rinish) | `lesson_attendance.left_early`, `daily_person_criteria.early_leave` |
| 10 | Oq xalat | Tanilgan yuz ostidagi tana sohasi (YOLO odam ramkasi bilan kesilgan), yorug'lik tuzatilgan Lab rang tahlili; har kuzatuv ovoz beradi, kunda ≥3 ovoz; talab — talabalar va o'qituvchi lavozimlari | `daily_person_criteria.coat_status`, hodisa #10 (dalil rasmi bilan) |
| 15 | Chekish | Tashqi hudud/koridor: har 5 daqiqada 20 s klip (2 kadr/s), poza kuzatuvi — qo'l og'izga ≥2 marta (0,5–6 s); telefon/stakan/shisha qo'l yonida bo'lsa rad; bir necha klipda takrorlansa ishonch oshadi | hodisa #15 (sinov rejimida, operator tasdiqlaydi) |
| 19 | Talabaning darsga diqqati | Dars o'rtasida har 5 daqiqada klip: har talabaning yuz yo'nalishi; telefon faqat **o'sha talabaning** yonida bo'lsa hisoblanadi (100 / 40 / 20 ball) | `lesson_attendance.attention_score`, `lesson_sessions.attention_score` |
| 21 | O'qituvchi faolligi | O'sha kliplarda o'qituvchining pozasi: harakat (yelka kengligiga nisbatan) 60% + xonada bo'lish ulushi 40% | `lesson_sessions.teacher_activity_score` |
| 22 | O'qituvchining darsga aniq kelishi | Boshlanish oynasida birinchi ko'rinish ≤ boshlanish + 10 daqiqa; ko'rinmasa va dars o'lchangan bo'lsa — kelmadi (xonada boshqa xodim bo'lsa nomi aytiladi) | `lesson_sessions.teacher_on_time`, hodisa #22 |

Olib tashlanganlar: 1, 2, 3, 4, 5, 11, 12, 13, 14, 16, 17, 18, 20, 23, 24, 25 (va 26).

## Arxitektura

```
20:00  ┌──────────────┐   reja    ┌──────────────┐  kadrlar   ┌─────────────┐
──────►│  Orkestrator │──────────►│ NVR o'quvchi │───────────►│ Tahlilchi   │
       │ (ai-worker)  │ vazifalar │ (ffmpeg)     │ (vaqti bilan)│ yuz/iz/poza │
       └──────┬───────┘           └──────────────┘            └──────┬──────┘
              │ hammasi tugagach (yoki 08:00 muddat)    kuzatuvlar  │
              ▼                                                     ▼
       ┌──────────────┐  davomat, dars, ballar, hodisalar  ┌─────────────┐
       │ Agregatsiya  │◄──────────────────────────────────│ video_      │
       │ (qoidalar)   │                                    │ observations│
       └──────────────┘                                    └─────────────┘
```

| Fayl | Vazifasi |
|------|----------|
| `app/services/nvr/isapi.py` | Hikvision ISAPI: kanallar (IP bilan), yozuv qidiruvi, yuklab olish (Digest) |
| `app/services/nvr/sources.py` | Kadr o'qish: RTSP playback, ISAPI download (ffmpeg stdin), eksport papkasi |
| `app/batch/planner.py` | Reja: kamera turi va dars jadvalidan kliplar |
| `app/batch/tracking.py` | Klip ichida yuz izlari, vektorlarni birlashtirish |
| `app/batch/analyzer.py` | Vazifa tahlili: yuz, telefon, xalat, poza, chekish |
| `app/batch/coat.py`, `smoking.py` | Xalat va chekish qoidalari |
| `app/batch/rules.py` | Kriteriyalar qoidalari (sof funksiyalar) |
| `app/batch/aggregate.py` | Natijalarni bazaga yozish (idempotent) |
| `app/jobs/video_analysis.py` | Orkestrator: 20:00, davom ettirish, muddat, ustuvorlik |
| `app/routers/video_analysis.py` | API: `/api/video-tahlil/*` |
| `src/pages/analysis/VideoAnalysisPage.tsx` | «Kunlik tahlil» sahifasi |

## Ishonchlilik qoidalari

* Yuz qabul qilinadi: o'xshashlik ≥ 0,50 va farq ≥ 0,05 (qat'iy) yoki
  ≥ 0,42 va farq ≥ 0,08 (yumshoq) — yumshoq moslik faqat 3 daqiqa ichida
  boshqa kamerada yoki ≥ 10 s keyin ikkinchi marta ko'rinsa.
* Bir klipdagi bir odamning kadrlari bitta izga bog'lanadi va vektorlari
  o'rtachalanadi — kichik/qiya yuz bitta kadrdan ko'ra ishonchli tanilad.
  Bir paytda bir odam ikki joyda bo'lmaydi (kuchsizrog'i tashlanadi).
* "Kelmadi", "erta ketdi", "kech qoldi" faqat kamera o'sha oraliqni haqiqatan
  ko'rgan bo'lsa (qamrov) yoziladi. Yozuv yo'q oraliq — "aniqlanmadi".
* Qo'lda kiritilgan yozuvlar (`source=qolda`) o'zgarmaydi; turniket yozuvi
  bilan birlashtiriladi (eng erta kelish, eng kech ketish).
* Kunni qayta hisoblash idempotent: o'sha kunning video natijalari
  o'chiriladi va qaytadan yoziladi. Videoda hech kim tanilmasa (NVR
  sozlanmagan) — kunning mavjud ma'lumotlariga tegilmaydi.
* Oldingi tahlilning xom kuzatuvlari yangi tahlil muvaffaqiyatli
  tugagandagina o'chiriladi — yangisi yiqilsa yoki bekor qilinsa, ular
  saqlanib qoladi.
* Agregatsiya yiqilsa (tahlil "xato"), kun `VIDEO_ANALYSIS_DAY_RETRIES`
  marta, har safar `VIDEO_ANALYSIS_RETRY_MINUTES` daqiqadan keyin avtomatik
  qayta uriniladi. Kuzatuvlar bazada bo'lgani uchun video qayta
  o'qilmaydi. Admin bekor qilgan kun avtomatik qayta boshlanmaydi.

## Dalillar: rasm + 2 daqiqalik video

Har aniqlangan holat (ishga/darsga kech kelish, erta ketish, darsga
kelmaslik, xalatsizlik, chekish, past diqqat, o'qituvchining kechikishi yoki
past faolligi) odamning kunlik natijasiga yoziladi: kriteriya, sabab, payt,
kamera (`daily_person_criteria.details.dalillar`). Agregatsiyadan keyin har
holat uchun yozuvdan **2 daqiqalik video** kesiladi (holatdan 1 daqiqa oldin
va keyin, 720p H.264) va MinIO'da saqlanadi — rasm dalilidan tashqari
ikkinchi dalil (`app/batch/evidence.py`). Bir kamerada 30 s ichidagi
holatlar bitta klipni bo'lishadi; hodisalar (xalat, chekish, o'qituvchi)
o'sha klipni `clip_key` sifatida oladi.

Ko'rish: odam kartasi → «Kunlik video tahlil» (holatlar va video), Excel
«Holatlar» varag'i, `scripts/video_tahlil.py hisobot --html sahifa.html`.

## Hamma kameralarda hamma kriteriyalar

`VIDEO_ANALYSIS_EVERYWHERE=true` (yoki `tahlil --hamma-joyda`): kamera turi
belgilanmagan bo'lsa ham har kamera butun oyna davomida chekish, xalat va
tanish kliplari bilan ko'riladi; dars xonasida darslardan tashqari vaqtda
ham. Dars kriteriyalari baribir dars jadvalidan (xona kamerasi) olinadi.

## Yuklama va muddat

Vazifalar tartibi: **darslar → kirish kameralari → boshqa kameralar →
chekish**. Ertasi kuni `VIDEO_ANALYSIS_DEADLINE` (08:00) gacha tugamasa,
qolgan (past ustuvor) vazifalar bekor qilinadi va natija bor ma'lumotdan
chiqariladi — ertalab hisobot tayyor bo'ladi. Sahifadagi «Tahlil jarayoni»
tabida taxminiy qolgan vaqt ko'rsatiladi.

## Ishga tushirish (bir martalik sozlash)

1. **NVR qo'shish**: «Kunlik tahlil» → «NVR» → «+ NVR»: IP (masalan
   `192.168.0.94`), login, parol. «Tekshirish» tugmasi — ulanish va kanallar
   soni.
2. **Kameralarni bog'lash**: «Kameralarga bog'lash» — NVR kanallaridagi
   kamera IP manzillari tizimdagi kameralarga avtomatik moslanadi (topilmasa
   — nom bo'yicha). «Kanallar» tugmasi bog'lanmagan kanallarni ko'rsatadi.
3. **Kamera turlari**: «Sozlamalar → Kameralar»da har kameraga xona turi
   (kirish, auditoriya, tashqi, koridor...) — reja shunga qarab tuziladi.
   Dars xonasi kamerasi HEMIS auditoriyasiga bog'langan bo'lishi kerak.
4. Birinchi tahlilni darhol ko'rish uchun: «Tahlil jarayoni» → kunni tanlab
   «Shu kunni tahlil qilish».

NVR tarmoqqa ulanmagan bo'lsa: yozuvlarni NVR'dan USB ga eksport qilib,
serverdagi `/opt/camera/nvr-eksport/<kanal>/<YYYYMMDD>_<HHMMSS>.mp4` ga
joylang va «Eksport qilingan yozuvlar papkasi» turidagi NVR qo'shing
(konteyner ichida `/data/nvr-eksport`).

## Yozib olingan videolar bilan ishlash (`scripts/video_tahlil.py`)

NVR'ga ulanmasdan, oldindan yozib olingan videolar ustida tahlil va hisobot:

```bash
# 1. Videoni kameraga biriktirish (vaqt fayl nomidan: ch01_20261005085000.mp4,
#    20261005_085000.mp4 — yoki --boshlanish bilan)
python scripts/video_tahlil.py import --kamera "Asosiy kirish" kirish.mp4 --boshlanish "2026-10-05 07:50"
python scripts/video_tahlil.py import --kamera "201-xona" --yangi --tur auditoriya dars.mp4 --boshlanish "2026-10-05 08:50"

# 2. Dars jadvalda bo'lmasa — qo'shish (kechikish, diqqat, o'qituvchi uchun)
python scripts/video_tahlil.py dars --kamera "201-xona" --kun 2026-10-05 --vaqt 09:00-10:20 --guruh DI-101 --oqituvchi "Familiya"

# 3. Tahlil (oyna — shu kungi videolar oralig'i) va Excel hisobot
python scripts/video_tahlil.py tahlil --kun 2026-10-05
python scripts/video_tahlil.py hisobot --kun 2026-10-05 --chiqish natija.xlsx

# Import qilinganlar ro'yxati
python scripts/video_tahlil.py holat
```

Serverda: videolarni `/opt/camera/nvr-eksport/` ga joylab,
`docker compose exec ai-worker python scripts/video_tahlil.py import ... /data/nvr-eksport/<fayl>`.
Natijalar «Kunlik tahlil» sahifasida ham ko'rinadi, Excel tugmasi bilan yuklab olinadi.

Video talablari: ffmpeg o'qiy oladigan format (Hikvision `.mp4`, H.264/H.265).
Dars kriteriyalari (kechikish, diqqat, erta chiqish) o'lchanishi uchun video
darsning boshidan (−10 daqiqa) oxirigacha bo'lishi kerak — qisqa video bilan dars
"o'lchanmadi" deb chiqadi (bu atayin: dalilsiz ayblov yo'q).

## Sozlamalar

| Kalit | Standart | Ma'nosi |
|-------|----------|---------|
| `ANALYSIS_MODE` | `kunlik` | `realtime` — eski rejim |
| `VIDEO_ANALYSIS_START` | `20:00` | Tahlil boshlanishi (kun oynasining oxiri) |
| `VIDEO_ANALYSIS_DAY_START` | `07:00` | Kun oynasining boshi |
| `VIDEO_ANALYSIS_DEADLINE` | `08:00` | Ertasi kuni shu paytgacha yangi vazifa boshlanadi |
| `VIDEO_ANALYSIS_CONCURRENCY` | `6` | Parallel vazifalar |
| `VIDEO_ANALYSIS_ENTRANCE_FPS` / `_PEAK_FPS` | `1` / `2` | Kirish kameralari kadr/s |
| `VIDEO_ANALYSIS_ENTRANCE_PEAK_WINDOWS` | `07:00-09:30,16:00-19:00` | Tig'iz soatlar |
| `VIDEO_ANALYSIS_CATCHUP_DAYS` | `2` | O'tkazib yuborilgan kunlar |
| `VIDEO_ANALYSIS_DAY_RETRIES` / `_RETRY_MINUTES` | `2` / `30` | Yiqilgan kun tahlilini qayta urinish |
| `VIDEO_ANALYSIS_EVERYWHERE` | `false` | Hamma kriteriyalar hamma kamerada |
| `VIDEO_EVIDENCE_CLIPS` / `_CLIP_SECONDS` / `_CLIPS_MAX` | `true` / `120` / `600` | Video dalil kliplari |
| `VIDEO_ATTENTION_LOW_SCORE` / `VIDEO_TEACHER_ACTIVITY_LOW_SCORE` | `60` / `40` | Shundan past — holat |
| `VIDEO_OBSERVATION_RETENTION_DAYS` | `30` | Xom kuzatuvlar saqlanishi |
| `COAT_REQUIRED_TYPES` / `COAT_REQUIRED_POSITIONS` | `talaba` / o'qituvchi lavozimlari | Kim uchun xalat majburiy |
| `COAT_MODEL_PATH` | — | Ixtiyoriy o'qitilgan klassifikator (YOLO-cls) |
| `SMOKING_MODEL_PATH` | — | Ixtiyoriy sigaret/vape detektori (YOLO) |

## Cheklovlar (halol)

* **Oq xalat** — rang qoidasi: oq ko'ylak/oq kofta ham oq ko'rinadi. Kun
  bo'yi ko'p namuna va odam ramkasi xatoni kamaytiradi, lekin aniq ajratish
  uchun o'qitilgan model kerak (`COAT_MODEL_PATH`) — hodisalar sinov
  rejimida boshlanadi.
* **Chekish** — sigaretning o'zi kadrda bir necha piksel, shuning uchun
  harakat bo'yicha aniqlanadi; ovqatlanish/yuz artish kabi holatlar
  nomzod bo'lishi mumkin. Hodisa doim operator tekshiruviga boradi.
* Haqiqiy NVR bilan oxirgi sinov institut tarmog'ida o'tkazilishi kerak:
  NVR vaqti (mahalliy/UTC) va trek raqamlari modelga qarab farq qiladi —
  ikkalasi ham NVR sozlamasida o'zgartiriladi.
