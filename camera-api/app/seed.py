"""Idempotent startup seed — safe to run on every boot.

Seeds the default permission matrix (matching src/lib/permissions.ts
DEFAULT_PERMISSIONS), two demo accounts (matching the frontend's
DEMO_CREDENTIALS in src/lib/auth.tsx so the existing login screen keeps
working once wired to this API), and the starting org-structure reference
data (matching src/mock/admin.ts) — only when each table is still empty.
"""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AIModuleConfig, Building, Faculty, Permission, User
from app.security import hash_password

DEFAULT_PERMISSIONS = {
    "manageCameras": (True, True),
    "configureAi": (True, True),
    "registerPeople": (True, True),
    "systemSettings": (True, False),
    "viewReports": (True, True),
    "viewLive": (True, True),
    "manageRoles": (True, False),
    "exportData": (True, False),
}

DEMO_USERS = [
    {"login": "admin", "password": "admin123", "full_name": "Jamshid Alimov", "role": "super-admin"},
    {"login": "operator", "password": "operator123", "full_name": "Behzod Karimov", "role": "admin"},
]

DEFAULT_FACULTIES = [
    {"name": "Davolash ishi", "course_count": 6, "student_count": 1520},
    {"name": "Farmatsiya", "course_count": 5, "student_count": 890},
    {"name": "Pediatriya", "course_count": 6, "student_count": 1140},
    {"name": "Jamoat salomatligi", "course_count": 4, "student_count": 668},
]

DEFAULT_BUILDINGS = [
    {"name": "1-Bino (Asosiy korpus)", "camera_count": 12},
    {"name": "2-Bino (Klinika va Laboratoriya)", "camera_count": 18},
    {"name": "3-Bino (Ma'muriy bino)", "camera_count": 8},
]

# TT hujjat 3-bo'lim: 25 ta AI kriteriya (A-F toifalar). `active`/`threshold`/
# `sensitivity` — admin sozlashi mumkin bo'lgan konfiguratsiya; accuracy=0
# ko'pincha real aniqlash logikasi yo'qligini emas, hali o'lchanmaganini
# anglatadi (pastdagi `has_detector: False` bo'lganlar bundan mustasno —
# ular uchun haqiqatan ham hech qanday aniqlash kodi yozilmagan).
DEFAULT_AI_MODULES = [
    {"code": 1, "group": "A", "name": "Notanish/begona shaxsni aniqlash", "description": "Yuzni tanish (Face-ID) — xodimlar/talabalar bazasida yo'q shaxs binoga kirsa signal. attendance_ai.py bilan bir xil InsightFace pipeline, teskari mantiq bilan: mos kelmagan yuz = begona. Ikki kadrli tasdiqlash (bad-angle/yorug'lik xatosini kamaytirish uchun), lekin real kuzatuv/identifikatsiya (tracking) yo'q — bir xil begona odam har safar yangi deb hisoblanishi mumkin", "method": "InsightFace + face_matching (teskari moslik) + ikki-kadrli tasdiqlash (app/jobs/unauthorized_person_ai.py)", "accuracy": 0, "threshold": 85, "sensitivity": "yuqori", "camera_count": 0, "active": True},
    {"code": 2, "group": "A", "name": "Taqiqlangan zonaga kirish", "description": "Rentgen xonasi, laboratoriya, arxiv kabi cheklangan hududlarga ruxsatsiz kirish — mediapipe Pose orqali odamning oyoq (yoki son, agar oyoq ko'rinmasa) o'rni kamera poligoniga (Camera.restricted_zone_polygon) solishtiriladi. Hozircha poligon chizish uchun admin interfeysi yo'q — bu haqiqiy, ishlaydigan aniqlash logikasi, faqat konfiguratsiya ma'lumoti kutmoqda. To'liq DeepSORT kuzatuvi emas, ikki-kadrli tasdiqlash bilan", "method": "mediapipe Pose + nuqta-poligon tekshiruvi + ikki-kadrli tasdiqlash (app/jobs/zone_entry_ai.py, app/services/zone_detection.py)", "accuracy": 0, "threshold": 80, "sensitivity": "yuqori", "camera_count": 0, "active": True},
    {"code": 3, "group": "A", "name": "Notekis/kechki vaqtda kirish", "description": "Ish vaqtidan tashqari binoga kirish holatlari", "method": "Yuzni tanish orqali avtomatik davomat (app/jobs/attendance_ai.py) + ish vaqti oynasi qoidasi", "accuracy": 96.4, "threshold": 70, "sensitivity": "o'rta", "camera_count": 28, "active": True},
    {"code": 4, "group": "A", "name": "Egasiz qoldirilgan buyum", "description": "Koridor/hovlida uzoq vaqt qoldirilgan sumka, quti — OpenCV MOG2 fon-ajratish (classical CV, YOLO kabi obyekt modeli talab qilinmaydi). Bir vaqtda faqat bitta (eng katta) statik hudud kuzatiladi — to'liq multi-object tracking emas. Yuz aniqlash bilan tekshiriladi: hudud ustida odam yuzi ko'rinsa, bu buyum emas, odam deb hisoblanadi. Sinov jarayonida haqiqiy topilma: MOG2'ning avtomatik o'rganish tezligi 30s oralig'idagi kadrlar uchun juda tez, shuning uchun aniq past qiymat qo'llanildi", "method": "OpenCV MOG2 fon-ajratish + statik hudud kuzatuvi + yuz-orqali odam filtri (app/jobs/abandoned_object_ai.py)", "accuracy": 0, "threshold": 75, "sensitivity": "o'rta", "camera_count": 0, "active": True},
    {"code": 5, "group": "A", "name": "Olomon zichligi anomaliyasi", "description": "Hovli yoki koridorda favqulodda to'planish — dedicated crowd-density modeli (CSRNet) o'rniga, InsightFace'ning yuz sonini har bir kamera uchun o'z tarixiy o'rtachasi bilan solishtiradi (real-vaqtli anomaliya, qattiq son chegarasi emas). Yuz soni haqiqiy odam sonining pastki chegarasi — kameraga orqa o'girib turgan odamlar hisobga olinmaydi", "method": "InsightFace yuz-soni + kamera-ichi tarixiy anomaliya (app/jobs/crowd_density_ai.py)", "accuracy": 0, "threshold": 78, "sensitivity": "o'rta", "camera_count": 0, "active": True},
    {"code": 6, "group": "B", "name": "Xodim/o'qituvchi davomati", "description": "Ish boshlanish/tugash vaqtini yuz orqali avtomatik qayd etish", "method": "Face recognition + timestamp log", "accuracy": 98.6, "threshold": 88, "sensitivity": "yuqori", "camera_count": 30, "active": True},
    {"code": 7, "group": "B", "name": "Talaba davomati", "description": "Auditoriyaga kirish/darsda ishtirok etish avtomatik qaydi", "method": "Face recognition (sinf kamerasi)", "accuracy": 99.2, "threshold": 90, "sensitivity": "yuqori", "camera_count": 28, "active": True},
    {"code": 8, "group": "B", "name": "Darsga kechikish", "description": "Belgilangan vaqtdan N daqiqa keyin kirish holati", "method": "Jadval bilan solishtirish (rule-based)", "accuracy": 96.4, "threshold": 85, "sensitivity": "o'rta", "camera_count": 28, "active": True},
    {"code": 9, "group": "B", "name": "Darsdan/ishdan erta ketish", "description": "Belgilangan tugash vaqtidan oldin xonani tark etish — oxirgi ko'rilgan vaqt (check_out) tugash vaqtidan oldin bo'lsa belgilanadi", "method": "Kirish-chiqish log tahlili (app/routers/attendance.py) — attendance_ai.py to'plagan check_out vaqtiga asoslangan qoida", "accuracy": 96.4, "threshold": 80, "sensitivity": "o'rta", "camera_count": 28, "active": True},
    {"code": 10, "group": "C", "name": "Oq xalat kiyilganligi", "description": "Faqat TANILGAN XODIM (yuz orqali) uchun tekshiriladi, talaba/mehmon uchun emas — fine-tuned YOLO/CLIP model o'rniga klassik HSV rang tahlili: mediapipe poza orqali topilgan tana (elka-son) hududining necha foizi \"oq\" diapazonda ekanligi o'lchanadi. Haqiqiy trening ma'lumoti (minglab belgilangan CCTV kadri) mavjud emasligi sababli haqiqiy klassifikator emas — faqat sintetik test rasmlarida tekshirilgan, haqiqiy institut kamerasida hali kalibrlanmagan. Yorug'lik/oq balans sharoitiga sezgir", "method": "mediapipe Pose + HSV rang evristikasi, faqat xodim-filtrlangan (app/jobs/dress_code_ai.py, app/services/coat_detection.py)", "accuracy": 0, "threshold": 55, "sensitivity": "past", "camera_count": 0, "active": True},
    {"code": 11, "group": "C", "name": "Bosh kiyim (kalpakcha) borligi", "description": "Faqat TANILGAN XODIM uchun tekshiriladi — object detection klassifikatori o'rniga bosh tepasi hududining rang BIR XILLIGI (uniformity) o'lchanadi: silliq mato (kalpakcha) sochga qaraganda ancha bir tekis rangda bo'ladi. Kalpakcha istalgan rangda bo'lishi mumkinligi sababli aniq rang emas, faqat bir xillik tekshiriladi. Juda bir tekis qisqa soch xato ijobiy, murakkab sochlar xato salbiy berishi mumkin — haqiqiy kamerada hali kalibrlanmagan", "method": "mediapipe Pose + rang bir xillik evristikasi, faqat xodim-filtrlangan (app/jobs/dress_code_ai.py, app/services/head_covering_detection.py)", "accuracy": 0, "threshold": 55, "sensitivity": "past", "camera_count": 0, "active": True},
    {"code": 12, "group": "C", "name": "ID-badge taqilganligi", "description": "Ko'krak hududida ID-karta taxminiy tekshiruv — haqiqiy badge detektori emas, kontur evristikasi", "method": "mediapipe Pose + ko'krak ROI kontur evristikasi (app/jobs/badge_ai.py, app/services/badge_detection.py)", "accuracy": 0, "threshold": 70, "sensitivity": "o'rta", "camera_count": 0, "active": False, "has_detector": True},
    {"code": 13, "group": "C", "name": "Qo'lqop/niqob (kerakli xonalarda)", "description": "Sanitariya zonalarida SIZ — ixtiyoriy custom YOLO yoki yuz-pastki qism rang evristikasi", "method": "YOLO PPE (ixtiyoriy) yoki niqob rang evristikasi (app/jobs/ppe_ai.py)", "accuracy": 0, "threshold": 85, "sensitivity": "yuqori", "camera_count": 0, "active": False, "has_detector": True},
    {"code": 14, "group": "D", "name": "Jang/nizolashish holati", "description": "Jismoniy toqnashuv yoki tajovuzkor harakatlar — TIZIMDAGI ENG ISHONCHSIZ mezon: haqiqiy action-recognition modeli emas, ikkita zaif signal birikmasi (odamlar yaqin turishi + #17 bilan bir xil harakat-anomaliya tekshiruvi). Real jang videosida sinalmagan, sport/bayram/olomon shoshilishi kabi oddiy faoliyatlarda xato signal berish ehtimoli yuqori va o'lchanmagan. Shu sabab eng past ishonch darajasida (35) signal beradi — bu \"kamera diqqat bilan qaralsin\" degani, \"jang tasdiqlandi\" emas", "method": "mediapipe Pose (yaqinlik) + optik oqim anomaliyasi (app/jobs/fight_ai.py, app/jobs/disorder_ai.py bilan bo'lishilgan)", "accuracy": 0, "threshold": 88, "sensitivity": "yuqori", "camera_count": 0, "active": True},
    {"code": 15, "group": "D", "name": "Chekish / elektron sigareta", "description": "Qo'l og'iz/burunga yaqin postura — sigareta obyektini aniqlamaydi, ikki-kadrli tasdiqlash", "method": "mediapipe Pose bilak-burun masofasi (app/jobs/smoking_ai.py)", "accuracy": 0, "threshold": 75, "sensitivity": "o'rta", "camera_count": 0, "active": False, "has_detector": True},
    {"code": 16, "group": "D", "name": "Imtihonda telefondan foydalanish", "description": "Nazorat ishi vaqtida ruxsatsiz qurilma ishlatish — YOLOv8 (COCO oldindan o'qitilgan) \"cell phone\" klassi, ikki-kadrli tasdiqlash bilan. E'tibor: bu faqat \"kadrda telefon ko'rindi\" signalini beradi, \"aynan imtihon vaqtida\" ekanligini bilmaydi — bunga haqiqiy imtihon jadvali kerak bo'ladi (hali yo'q)", "method": "YOLOv8 obyekt aniqlash + ikki-kadrli tasdiqlash (app/jobs/phone_ai.py)", "accuracy": 0, "threshold": 80, "sensitivity": "yuqori", "camera_count": 0, "active": True},
    {"code": 17, "group": "D", "name": "Tartib-intizom buzilishi", "description": "Yugurish, xavfli harakat, koridorda shovqin-suron — pose estimation modeli o'rniga, kadrlararo optik oqim (Farneback, classical CV) o'rtacha kattaligi kamera-ichi tarixiy o'rtacha bilan solishtiriladi. Butun kadr bo'yicha o'rtacha — bitta odamning yugurishi va bir nechta odamning oddiy yurishi orasidagi farqni aniq ajratmasligi mumkin", "method": "Farneback optik oqim + kamera-ichi tarixiy anomaliya (app/jobs/disorder_ai.py)", "accuracy": 0, "threshold": 65, "sensitivity": "past", "camera_count": 0, "active": True},
    {"code": 18, "group": "D", "name": "Kiyim-bosh (dress code) umumiy", "description": "Tanilgan talaba uchun yuqori/pastki tana yorqinlik kontrasti evristikasi", "method": "Face-ID talaba filtri + HSV kontrast (app/jobs/student_dress_code_ai.py)", "accuracy": 0, "threshold": 70, "sensitivity": "o'rta", "camera_count": 0, "active": False, "has_detector": True},
    {"code": 19, "group": "E", "name": "Talabaning darsga diqqati", "description": "Boshning yo'nalishi, ko'z harakati, telefon bilan chalg'ishi asosida diqqat balli — dedicated gaze-estimation modeli o'rniga ikkita mavjud signal qo'shiladi: InsightFace orqali yuz yo'nalishi (frontality) + YOLO orqali telefon ko'rinishi (#16 bilan bir xil). Telefon signali butun kadr bo'yicha — aynan qaysi talaba ushlab turganini bilmaydi. LessonSession.attention_score'ga davomiy o'rtacha sifatida yoziladi, faqat dars faol vaqti oynasida (jadval kerak)", "method": "InsightFace frontality + YOLO telefon aniqlash + davomiy o'rtacha (app/jobs/lesson_quality_ai.py)", "accuracy": 0, "threshold": 60, "sensitivity": "o'rta", "camera_count": 0, "active": True},
    {"code": 20, "group": "E", "name": "Talabaning uxlab qolishi", "description": "Ko'zning uzoq muddat yopiq qolishi (EAR) orqali uxlab qolishni aniqlash — bir necha kadrli (burst) ko'pchilik ovoz qoidasi + boshning kameraga qaragan-qaramaganini tekshiruvchi filtr bilan kuchaytirilgan (avvalgi 2-kadrli usuldan farqli); accuracy raqami hali yangi usul bilan qayta o'lchanmagan, eski qiymat sifatida qoldirilgan", "method": "Facial landmark + eye-closure (EAR) + burst-vote + pose-gate tahlili (app/jobs/vision_ai.py, app/services/sleep_detection.py)", "accuracy": 65.0, "threshold": 70, "sensitivity": "past", "camera_count": 28, "active": True},
    {"code": 21, "group": "E", "name": "O'qituvchi faolligi", "description": "Doska oldida faol harakat, talabalar bilan interaktivlik vaqti — mediapipe Pose orqali o'qituvchining (yuz orqali aniqlangan) tanasi ikki kadr orasida qancha harakatlanganini o'lchaydi. LessonSession.teacher_activity_score'ga davomiy o'rtacha sifatida yoziladi, faqat dars faol vaqti oynasida (jadval kerak) — #19 bilan bir xil sweep, bitta kamera so'rovi", "method": "mediapipe Pose + landmark harakati + davomiy o'rtacha (app/jobs/lesson_quality_ai.py)", "accuracy": 0, "threshold": 60, "sensitivity": "past", "camera_count": 0, "active": True},
    {"code": 22, "group": "E", "name": "O'qituvchining darsga aniq kelishi", "description": "Dars boshlanishi bilan xonada mavjudligi — attendance_ai.py bilan bir xil InsightFace pipeline'dan foydalanadi, faqat aniq dars jadvali (teacher_id/camera_id/scheduled_start_time — LessonSession jadvalida) kiritilgan darslarni tekshiradi. Hozircha jadval kiritish uchun admin interfeysi yo'q, shu sabab hech qanday dars avtomatik tekshirilmaydi — model tayyor va sinovdan o'tgan, faqat ma'lumot kiritilishini kutmoqda", "method": "Face recognition + jadval taqqoslash (app/jobs/teacher_punctuality_ai.py)", "accuracy": 0, "threshold": 85, "sensitivity": "o'rta", "camera_count": 0, "active": True},
    {"code": 23, "group": "F", "name": "Yong'in / tutun aniqlash", "description": "Rang (olov spektri) va vaqt bo'yicha chayqalish (flicker) birgalikda tekshiriladi — faqat rangga asoslangan usul odam terisida yolg'on signal berishi aniqlanib, rad etilgan edi; haqiqiy yong'in videosida sinab ko'rilmagan, shu sabab har bir signal operator tasdig'ini talab qiladi", "method": "HSV rang + kadrlararo yorqinlik o'zgarishi (flicker) tahlili (app/jobs/fire_ai.py)", "accuracy": 0, "threshold": 90, "sensitivity": "yuqori", "camera_count": 28, "active": True},
    {"code": 24, "group": "F", "name": "Yiqilib tushish (fall detection)", "description": "Xodim yoki bemorning yiqilib qolishi — mediapipe Pose (33 tana nuqtasi): tana burchagi vertikaldan qiyaligi + tana quti kengligi/balandligi nisbati, ikki-kadrli tasdiqlash bilan. Real yiqilish videosida sinalmagan — pol ustida cho'zilish yoki egilish ham xato signal berishi mumkin, shu sabab har bir signal operator tasdig'ini talab qiladi", "method": "mediapipe Pose + tana-burchak geometriyasi + ikki-kadrli tasdiqlash (app/jobs/fall_ai.py, app/services/fall_detection.py)", "accuracy": 0, "threshold": 85, "sensitivity": "yuqori", "camera_count": 0, "active": True},
    {"code": 25, "group": "F", "name": "Hovlida transport harakati", "description": "Avtomobil/mototsikl piyodalar zonasida yoki taqiqlangan joyda — YOLOv8 (COCO) \"car\"/\"motorcycle\" klasslari, ikki-kadrli tasdiqlash bilan. E'tibor: bu faqat \"kadrda transport ko'rindi\" signalini beradi — qaysi kameralar piyodalar zonasi ekanligini bilmaydi (bunday zona-belgilash hali yo'q), shuning uchun barcha kameralarda ishlaydi", "method": "YOLOv8 obyekt aniqlash + ikki-kadrli tasdiqlash (app/jobs/vehicle_ai.py)", "accuracy": 0, "threshold": 75, "sensitivity": "o'rta", "camera_count": 0, "active": True},
]


async def seed_all(db: AsyncSession) -> None:
    """Safe to run on every boot, AND safe to run concurrently — in a
    multi-worker deployment (see app/main.py's lifespan), every worker
    process calls this independently at startup. Each table commits on
    its own instead of one all-or-nothing transaction: if two workers'
    count()==0 checks both pass before either commits (a real race, since
    they're separate DB connections), the loser hits a unique-constraint
    conflict at commit time — caught and treated as "another worker
    already seeded this," not a startup failure."""
    for seed_table in (_seed_permissions, _seed_users, _seed_faculties, _seed_buildings, _seed_ai_modules):
        try:
            await seed_table(db)
            await db.commit()
        except IntegrityError:
            await db.rollback()


async def _seed_permissions(db: AsyncSession) -> None:
    count = await db.scalar(select(func.count()).select_from(Permission))
    if count:
        return
    for key, (super_admin, admin) in DEFAULT_PERMISSIONS.items():
        db.add(Permission(key=key, super_admin=super_admin, admin=admin))


async def _seed_users(db: AsyncSession) -> None:
    count = await db.scalar(select(func.count()).select_from(User))
    if count:
        return
    for u in DEMO_USERS:
        db.add(
            User(
                login=u["login"],
                password_hash=hash_password(u["password"]),
                full_name=u["full_name"],
                role=u["role"],
            )
        )


async def _seed_faculties(db: AsyncSession) -> None:
    count = await db.scalar(select(func.count()).select_from(Faculty))
    if count:
        return
    for f in DEFAULT_FACULTIES:
        db.add(Faculty(**f))


async def _seed_buildings(db: AsyncSession) -> None:
    count = await db.scalar(select(func.count()).select_from(Building))
    if count:
        return
    for b in DEFAULT_BUILDINGS:
        db.add(Building(**b))


async def _seed_ai_modules(db: AsyncSession) -> None:
    count = await db.scalar(select(func.count()).select_from(AIModuleConfig))
    if count:
        return
    for m in DEFAULT_AI_MODULES:
        db.add(AIModuleConfig(**m))
