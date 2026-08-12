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

# TT hujjat 3-bo'lim: 25 ta AI kriteriya (A-F toifalar). Bu — REGISTR, inference
# emas: `active`/`threshold`/`sensitivity` faqat konfiguratsiya, haqiqiy model
# ulanmagani uchun accuracy=0 bo'lgan qatorlar hali hech narsani aniqlamaydi.
DEFAULT_AI_MODULES = [
    {"code": 1, "group": "A", "name": "Notanish/begona shaxsni aniqlash", "description": "Yuzni tanish (Face-ID) — xodimlar/talabalar bazasida yo'q shaxs binoga kirsa signal", "method": "YOLOv8-face + ArcFace, mahalliy GPU", "accuracy": 0, "threshold": 85, "sensitivity": "yuqori", "camera_count": 0, "active": False},
    {"code": 2, "group": "A", "name": "Taqiqlangan zonaga kirish", "description": "Rentgen xonasi, laboratoriya, arxiv kabi cheklangan hududlarga ruxsatsiz kirish", "method": "Zona-poligon + object tracking (DeepSORT)", "accuracy": 0, "threshold": 80, "sensitivity": "yuqori", "camera_count": 0, "active": False},
    {"code": 3, "group": "A", "name": "Notekis/kechki vaqtda kirish", "description": "Ish vaqtidan tashqari binoga kirish holatlari", "method": "Yuzni tanish orqali avtomatik davomat (app/jobs/attendance_ai.py) + ish vaqti oynasi qoidasi", "accuracy": 96.4, "threshold": 70, "sensitivity": "o'rta", "camera_count": 28, "active": True},
    {"code": 4, "group": "A", "name": "Egasiz qoldirilgan buyum", "description": "Koridor/hovlida uzoq vaqt qoldirilgan sumka, quti", "method": "Statik-obyekt aniqlash (background subtraction)", "accuracy": 0, "threshold": 75, "sensitivity": "o'rta", "camera_count": 0, "active": False},
    {"code": 5, "group": "A", "name": "Olomon zichligi anomaliyasi", "description": "Hovli yoki koridorda favqulodda to'planish", "method": "Crowd density estimation (CSRNet/YOLO-crowd)", "accuracy": 0, "threshold": 78, "sensitivity": "o'rta", "camera_count": 0, "active": False},
    {"code": 6, "group": "B", "name": "Xodim/o'qituvchi davomati", "description": "Ish boshlanish/tugash vaqtini yuz orqali avtomatik qayd etish", "method": "Face recognition + timestamp log", "accuracy": 98.6, "threshold": 88, "sensitivity": "yuqori", "camera_count": 30, "active": True},
    {"code": 7, "group": "B", "name": "Talaba davomati", "description": "Auditoriyaga kirish/darsda ishtirok etish avtomatik qaydi", "method": "Face recognition (sinf kamerasi)", "accuracy": 99.2, "threshold": 90, "sensitivity": "yuqori", "camera_count": 28, "active": True},
    {"code": 8, "group": "B", "name": "Darsga kechikish", "description": "Belgilangan vaqtdan N daqiqa keyin kirish holati", "method": "Jadval bilan solishtirish (rule-based)", "accuracy": 96.4, "threshold": 85, "sensitivity": "o'rta", "camera_count": 28, "active": True},
    {"code": 9, "group": "B", "name": "Darsdan/ishdan erta ketish", "description": "Belgilangan tugash vaqtidan oldin xonani tark etish — oxirgi ko'rilgan vaqt (check_out) tugash vaqtidan oldin bo'lsa belgilanadi", "method": "Kirish-chiqish log tahlili (app/routers/attendance.py) — attendance_ai.py to'plagan check_out vaqtiga asoslangan qoida", "accuracy": 96.4, "threshold": 80, "sensitivity": "o'rta", "camera_count": 28, "active": True},
    {"code": 10, "group": "C", "name": "Oq xalat kiyilganligi", "description": "Tibbiy xodim/talabaning oq xalatda ekanligini aniqlash", "method": "Kiyim klassifikatsiyasi (fine-tuned YOLO/CLIP)", "accuracy": 0, "threshold": 82, "sensitivity": "yuqori", "camera_count": 0, "active": False},
    {"code": 11, "group": "C", "name": "Bosh kiyim (kalpakcha) borligi", "description": "Amaliyot/laboratoriya xonalarida bosh kiyim taqilganligi", "method": "Object detection (head-region classifier)", "accuracy": 0, "threshold": 80, "sensitivity": "o'rta", "camera_count": 0, "active": False},
    {"code": 12, "group": "C", "name": "ID-badge taqilganligi", "description": "Xodim/talaba identifikatsiya kartochkasi ko'rinishda ekanligi", "method": "Object detection (kichik obyekt, yaqin kamera talab qiladi)", "accuracy": 0, "threshold": 70, "sensitivity": "o'rta", "camera_count": 0, "active": False},
    {"code": 13, "group": "C", "name": "Qo'lqop/niqob (kerakli xonalarda)", "description": "Sanitariya talab qiladigan zonalarda SIZ mavjudligi", "method": "PPE detection modeli", "accuracy": 0, "threshold": 85, "sensitivity": "yuqori", "camera_count": 0, "active": False},
    {"code": 14, "group": "D", "name": "Jang/nizolashish holati", "description": "Jismoniy toqnashuv yoki tajovuzkor harakatlar", "method": "Action recognition (pose + optical flow)", "accuracy": 0, "threshold": 88, "sensitivity": "yuqori", "camera_count": 0, "active": False},
    {"code": 15, "group": "D", "name": "Chekish / elektron sigareta", "description": "Bino ichida yoki hovlida chekish holatlari", "method": "Obyekt + tutun/harakat klassifikatori", "accuracy": 0, "threshold": 75, "sensitivity": "o'rta", "camera_count": 0, "active": False},
    {"code": 16, "group": "D", "name": "Imtihonda telefondan foydalanish", "description": "Nazorat ishi vaqtida ruxsatsiz qurilma ishlatish", "method": "Telefon obyekt detektsiyasi (YOLO)", "accuracy": 0, "threshold": 80, "sensitivity": "yuqori", "camera_count": 0, "active": False},
    {"code": 17, "group": "D", "name": "Tartib-intizom buzilishi", "description": "Yugurish, xavfli harakat, koridorda shovqin-suron", "method": "Harakat anomaliyasi (pose estimation)", "accuracy": 0, "threshold": 65, "sensitivity": "past", "camera_count": 0, "active": False},
    {"code": 18, "group": "D", "name": "Kiyim-bosh (dress code) umumiy", "description": "Talabalarning institut nizomiga mos kiyingani", "method": "Kiyim klassifikatsiyasi", "accuracy": 0, "threshold": 70, "sensitivity": "o'rta", "camera_count": 0, "active": False},
    {"code": 19, "group": "E", "name": "Talabaning darsga diqqati", "description": "Boshning yo'nalishi, ko'z harakati, telefon bilan chalg'ishi asosida diqqat balli", "method": "Gaze estimation + pose (engagement score)", "accuracy": 0, "threshold": 60, "sensitivity": "o'rta", "camera_count": 0, "active": False},
    {"code": 20, "group": "E", "name": "Talabaning uxlab qolishi", "description": "Ko'zning uzoq muddat yopiq qolishi (EAR) orqali uxlab qolishni aniqlash — bitta kadr tahlili, ko'z qisish (blink) bilan chalkashishi mumkin, shu sabab past ishonch darajasida signal beradi", "method": "Facial landmark + eye-closure (EAR) tahlili (app/jobs/vision_ai.py)", "accuracy": 65.0, "threshold": 70, "sensitivity": "past", "camera_count": 28, "active": True},
    {"code": 21, "group": "E", "name": "O'qituvchi faolligi", "description": "Doska oldida faol harakat, talabalar bilan interaktivlik vaqti", "method": "Pose tracking + zona-vaqt tahlili", "accuracy": 0, "threshold": 60, "sensitivity": "past", "camera_count": 0, "active": False},
    {"code": 22, "group": "E", "name": "O'qituvchining darsga aniq kelishi", "description": "Dars boshlanishi bilan xonada mavjudligi", "method": "Face recognition + jadval taqqoslash", "accuracy": 0, "threshold": 85, "sensitivity": "o'rta", "camera_count": 0, "active": False},
    {"code": 23, "group": "F", "name": "Yong'in / tutun aniqlash", "description": "Rang (olov spektri) va vaqt bo'yicha chayqalish (flicker) birgalikda tekshiriladi — faqat rangga asoslangan usul odam terisida yolg'on signal berishi aniqlanib, rad etilgan edi; haqiqiy yong'in videosida sinab ko'rilmagan, shu sabab har bir signal operator tasdig'ini talab qiladi", "method": "HSV rang + kadrlararo yorqinlik o'zgarishi (flicker) tahlili (app/jobs/fire_ai.py)", "accuracy": 0, "threshold": 90, "sensitivity": "yuqori", "camera_count": 28, "active": True},
    {"code": 24, "group": "F", "name": "Yiqilib tushish (fall detection)", "description": "Xodim yoki bemorning yiqilib qolishi", "method": "Pose-based fall detection", "accuracy": 0, "threshold": 85, "sensitivity": "yuqori", "camera_count": 0, "active": False},
    {"code": 25, "group": "F", "name": "Hovlida transport harakati", "description": "Avtomobil/mototsikl piyodalar zonasida yoki taqiqlangan joyda", "method": "Vehicle detection + zona qoidasi", "accuracy": 0, "threshold": 75, "sensitivity": "o'rta", "camera_count": 0, "active": False},
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
