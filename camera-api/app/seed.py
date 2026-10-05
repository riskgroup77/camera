"""Idempotent startup seed — safe to run on every boot.

Seeds the default permission matrix (matching src/lib/permissions.ts
DEFAULT_PERMISSIONS), two demo accounts (matching the frontend's
DEMO_CREDENTIALS in src/lib/auth.tsx so the existing login screen keeps
working once wired to this API), and the starting org-structure reference
data (matching src/mock/admin.ts) — only when each table is still empty.
"""

import logging

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import AIModuleConfig, Building, Faculty, Permission, User
from app.security import hash_password
from app.services.security_checks import DEMO_PASSWORDS

logger = logging.getLogger("app.seed")

# (super_admin, admin, kamera_masuli)
DEFAULT_PERMISSIONS = {
    "manageCameras": (True, True, False),
    "configureAi": (True, True, False),
    "registerPeople": (True, True, False),
    "systemSettings": (True, False, False),
    "viewReports": (True, True, False),
    "viewLive": (True, True, False),
    "manageRoles": (True, False, False),
    "exportData": (True, False, False),
    # Kamera ma'lumotlarini to'g'rilash: bino, qavat, zona, nom. Kamera
    # qo'shish/o'chirish va ulanish sozlamalari bunga KIRMAYDI — shuning
    # uchun bu alohida huquq (app/routers/cameras.py location endpointi).
    "editCameraLocation": (True, True, True),
    # 2026-09-17: shu sahifalar ilgari faqat "tizimga kirgan" bo'lishni
    # talab qilardi, ya'ni kamera mas'uli ham hodisalarni o'chira,
    # davomatni tuzata va fakultetlarni o'chira olardi. Alembic
    # n7b8c9d0e1f2 mavjud bazalarga aynan shu qiymatlarni qo'shadi.
    "reviewEvents": (True, True, False),
    # Hodisa — dalil. Admin uni tasdiqlaydi yoki rad etadi, o'chirmaydi.
    "deleteEvents": (True, False, False),
    "manageAttendance": (True, True, False),
    # Faqat O'ZGARTIRISH: binolar va kafedralar ro'yxatini kamera
    # mas'uli ham o'qiydi — kamerani joylashtirish uchun kerak.
    "manageOrgStructure": (True, True, False),
    "manageLessons": (True, True, False),
    # Platforma kengaytmasi (2026-09-19, alembic s1a2b3c4d5e6).
    "manageNotifications": (True, True, False),
    "manageIntegrations": (True, False, False),
    "controlPtz": (True, True, False),
    "managePrivacy": (True, False, False),
}

# Faqat settings.seed_demo_users yoqilganda (lokal ishlab chiqish, testlar).
DEMO_USERS = [
    {"login": "admin", "password": DEMO_PASSWORDS["admin"], "full_name": "Jamshid Alimov", "role": "super-admin"},
    {"login": "operator", "password": DEMO_PASSWORDS["operator"], "full_name": "Behzod Karimov", "role": "admin"},
]

DEFAULT_FACULTIES = [
    {"name": "Davolash ishi", "course_count": 6, "student_count": 1520},
    {"name": "Farmatsiya", "course_count": 5, "student_count": 890},
    {"name": "Pediatriya", "course_count": 6, "student_count": 1140},
    {"name": "Jamoat salomatligi", "course_count": 4, "student_count": 668},
]

DEFAULT_BUILDINGS = [
    {"name": "1-Bino (Asosiy korpus)", "camera_count": 12, "floors": 4, "sort_order": 1},
    {"name": "2-Bino (Klinika va Laboratoriya)", "camera_count": 18, "floors": 3, "sort_order": 2},
    {"name": "3-Bino (Ma'muriy bino)", "camera_count": 8, "floors": 2, "sort_order": 3},
]

# `threshold` haqida (2026-09 auditidan keyin): bu qiymat endi HAQIQATAN
# ishlaydi — app/services/event_bus.py undan pastdagi aniqlashni yozmaydi.
# Ilgari u faqat admin panelda ko'rsatilar va saqlanar, hech kim o'qimasdi.
#
# Shuning uchun har bir chegara modul CHIQARA OLADIGAN eng past qiymatga
# tenglashtirildi, ya'ni standart sozlama hech narsani yo'qotmaydi.
# Chegarani KO'TARISH — modulni jimlatishning to'g'ri usuli (ko'p modul
# doimiy ishonch qiymati beradi, shuning uchun u dial emas, tugma).
#
# Bu tekshiruvsiz qo'yilgan raqamlarning nechog'lik xavfli bo'lishini
# yong'in moduli ko'rsatdi: chegara 90 edi, moduli esa 0.015 piksel
# ulushidan boshlab signal beradi — ya'ni ishonch 15 dan boshlanadi.
# Chegara yoqilganda haqiqiy yong'in signali kadrning 9% ini egallamasa
# jimgina o'chirilgan bo'lardi.

# TT hujjat 3-bo'lim: 19 ta AI kriteriya (A-F toifalar).
#
# 2026-09-07 da buyurtmachi qarori bilan yettitasi olib tashlandi: #4
# (egasiz buyum), #5 (olomon zichligi), #11 (bosh kiyim), #16 (imtihonda
# telefon), #18 (talaba kiyim-boshi), #24 (yiqilib tushish), #25 (hovlida
# transport). Ularning sweep kodi ham o'chirildi — konfiguratsiyada
# `active: False` qoldirish yetarli emas edi, chunki bu ularning kamera
# so'rovlarini va inference yukini saqlab qolardi.
#
# O'rniga #26 ("O'qituvchi o'rniga boshqasi kirgani") qo'shildi — u #22
# bilan AYNAN BIR XIL kadrni ishlatadi, ya'ni qo'shimcha kamera so'rovi
# yoki inference yuki keltirmaydi.
#
# `active`/`threshold`/
# `sensitivity` — admin sozlashi mumkin bo'lgan konfiguratsiya; accuracy=0
# ko'pincha real aniqlash logikasi yo'qligini emas, hali o'lchanmaganini
# anglatadi (pastdagi `has_detector: False` bo'lganlar bundan mustasno —
# ular uchun haqiqatan ham hech qanday aniqlash kodi yozilmagan).
# Kalibrlanmagan klassik evristikalar sinov rejimida boshlanadi — mavjud
# bazalarda buni alembic h1b2c3d4e5f6 bajaradi.
# 2026-10-04 (buyurtmachi ro'yxati): qoldi 6, 7, 8, 9, 10, 15, 19, 21, 22;
# 1, 2, 3, 20, 26 olib tashlandi (alembic z1a2b3c4d5e6). Ular kun oxirida
# NVR yozuvlaridan hisoblanadi (app/batch/, docs/KUNLIK_VIDEO_TAHLIL.md).
# 2026-10-06: buyurtmachi qarori bilan 1 (begona shaxs) qaytdi — tanilmagan
# yuzlar "begona shaxs" bo'lib chiqadi (alembic z3a2b3c4d5e6).
TRIAL_MODULE_CODES = {10, 15, 19, 21}

DEFAULT_AI_MODULES = [
    {"code": 1, "group": "A", "name": "Notanish/begona shaxsni aniqlash", "description": "Yuzni tanish (Face-ID) — xodimlar/talabalar bazasida yo'q shaxs binoga kirsa signal. attendance_ai.py bilan bir xil InsightFace pipeline, teskari mantiq bilan: mos kelmagan yuz = begona. Ikki kadrli tasdiqlash (bad-angle/yorug'lik xatosini kamaytirish uchun), lekin real kuzatuv/identifikatsiya (tracking) yo'q — bir xil begona odam har safar yangi deb hisoblanishi mumkin", "method": "InsightFace + face_matching (teskari moslik) + ikki-kadrli tasdiqlash (app/jobs/unauthorized_person_ai.py)", "accuracy": 0, "threshold": 70, "sensitivity": "yuqori", "camera_count": 0, "active": True},
    {"code": 6, "group": "B", "name": "Xodim/o'qituvchi davomati", "description": "Ish boshlanish/tugash vaqtini yuz orqali avtomatik qayd etish — kun oxirida kirish/chiqish kameralarining butun kunlik yozuvi (2 kadr/s) tahlil qilinadi; kunning birinchi va oxirgi ishonchli ko'rinishi kelish va ketish vaqti", "method": "Yuz tanish + klip ichida kuzatuv (embedding birlashtirish) + ikki marta tasdiqlash (app/batch/analyzer.py, app/batch/aggregate.py)", "accuracy": 0, "threshold": 88, "sensitivity": "yuqori", "camera_count": 0, "active": True},
    {"code": 7, "group": "B", "name": "Talaba davomati", "description": "Auditoriyaga kirish/darsda ishtirok etish avtomatik qaydi — dars xonasi kamerasining dars vaqtidagi yozuvidan; kamida ikki alohida klipda tanilgan talaba darsda bo'lgan hisoblanadi", "method": "Yuz tanish (sinf kamerasi, dars jadvali bo'yicha kliplar) (app/batch/aggregate.py)", "accuracy": 0, "threshold": 90, "sensitivity": "yuqori", "camera_count": 0, "active": True},
    {"code": 8, "group": "B", "name": "Darsga kechikish", "description": "Belgilangan vaqtdan N daqiqa keyin kirish holati — dars boshlanishidan 10 daqiqa oldin va 20 daqiqa keyin har daqiqada klip; birinchi ko'rinish boshlanish + 5 daqiqadan keyin bo'lsa kechikkan", "method": "Jadval bilan solishtirish (rule-based) (app/batch/aggregate.py)", "accuracy": 0, "threshold": 85, "sensitivity": "o'rta", "camera_count": 0, "active": True},
    {"code": 9, "group": "B", "name": "Darsdan/ishdan erta ketish", "description": "Belgilangan tugash vaqtidan oldin xonani tark etish — darsning oxirgi 15 daqiqasi har daqiqada tekshiriladi; ishdan erta ketish kunning oxirgi ko'rinishi va kamera qamrovi bo'yicha (dalil yetmasa — aniqlanmadi)", "method": "Kirish-chiqish log tahlili (app/batch/aggregate.py, early_leave_verdict)", "accuracy": 0, "threshold": 80, "sensitivity": "o'rta", "camera_count": 0, "active": True},
    {"code": 10, "group": "C", "name": "Oq xalat kiyilganligi", "description": "Tibbiy xodim/talabaning oq xalatda ekanligi — tanilgan yuz ostidagi tana sohasi (YOLO odam ramkasi bilan chegaralangan) oq rang ulushi o'lchanadi, kun bo'yi ko'p namunadan ovoz beriladi", "method": "Yuz tanish + YOLO odam ramkasi + rang tahlili (yoki o'qitilgan klassifikator) + kunlik ovoz berish (app/batch/coat.py)", "accuracy": 0, "threshold": 50, "sensitivity": "o'rta", "camera_count": 0, "active": True},
    {"code": 15, "group": "D", "name": "Chekish / elektron sigareta", "description": "Bino ichida yoki hovlida chekish holatlari — tashqi va koridor kameralarining 20 soniyalik kliplarida odam pozasi kuzatiladi: qo'lning og'izga takroriy ko'tarilishi; telefon/stakan bo'lsa rad etiladi", "method": "YOLO poza + qo'l-og'iz takroriy harakati + obyekt istisnolari (ixtiyoriy sigaret modeli) (app/batch/smoking.py)", "accuracy": 0, "threshold": 50, "sensitivity": "past", "camera_count": 0, "active": True},
    {"code": 19, "group": "E", "name": "Talabaning darsga diqqati", "description": "Boshning yo'nalishi va telefon bilan chalg'ishi asosida diqqat balli — dars davomida har 5 daqiqada klip; har talaba uchun alohida: yuz kameraga qaragan kadrlar ulushi, talabaning o'z yonidagi telefon ballni tushiradi", "method": "InsightFace yuz yo'nalishi + YOLO telefon (talabaga bog'langan) (app/batch/analyzer.py)", "accuracy": 0, "threshold": 60, "sensitivity": "o'rta", "camera_count": 0, "active": True},
    {"code": 21, "group": "E", "name": "O'qituvchi faolligi", "description": "Doska oldida faol harakat, talabalar bilan interaktivlik vaqti — dars o'rtasidagi kliplarda o'qituvchining tanasi qancha harakatlangani va xonada bo'lish ulushi", "method": "Poza kuzatuvi + xonada bo'lish ulushi (app/batch/analyzer.py)", "accuracy": 0, "threshold": 60, "sensitivity": "past", "camera_count": 0, "active": True},
    {"code": 22, "group": "E", "name": "O'qituvchining darsga aniq kelishi", "description": "Dars boshlanishi bilan xonada mavjudligi — boshlanish oynasidagi kliplarda o'qituvchining birinchi ko'rinishi; xonada boshqa xodim ko'rinsa hodisa tafsilotida aytiladi", "method": "Yuz tanish + jadval taqqoslash (app/batch/aggregate.py)", "accuracy": 0, "threshold": 70, "sensitivity": "o'rta", "camera_count": 0, "active": True},
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
    for seed_table in (
        _seed_permissions,
        _seed_users,
        _seed_faculties,
        _seed_buildings,
        _seed_ai_modules,
        _sync_ai_module_docs,
    ):
        try:
            await seed_table(db)
            await db.commit()
        except IntegrityError:
            await db.rollback()


async def _seed_permissions(db: AsyncSession) -> None:
    """Matritsada YO'Q kalitlarni standart qiymat bilan qo'shadi, mavjudlariga
    tegmaydi (admin ularni o'zgartirgan bo'lishi mumkin).

    Ilgari faqat jadval butunlay bo'sh bo'lsa to'ldirilardi. Lekin yangi
    bazada `alembic upgrade head` ba'zi kalitlarni migratsiyalarning o'zi
    yozadi (n7b8c9d0e1f2 va boshqalar) — jadval bo'sh bo'lmay qoladi va
    viewLive, manageRoles kabi asosiy huquqlar hech qachon yaratilmasdi:
    Super Admin ham yarim menyuni ko'rmasdi."""
    existing = set((await db.execute(select(Permission.key))).scalars().all())
    for key, (super_admin, admin, camera_steward) in DEFAULT_PERMISSIONS.items():
        if key in existing:
            continue
        db.add(
            Permission(key=key, super_admin=super_admin, admin=admin, camera_steward=camera_steward)
        )


async def _seed_users(db: AsyncSession) -> None:
    count = await db.scalar(select(func.count()).select_from(User))
    if count:
        return
    if settings.initial_admin_login and settings.initial_admin_password:
        db.add(
            User(
                login=settings.initial_admin_login,
                password_hash=hash_password(settings.initial_admin_password),
                full_name="Bosh administrator",
                role="super-admin",
            )
        )
        return
    if not settings.seed_demo_users:
        logger.error(
            "no users exist and no initial admin is configured — set INITIAL_ADMIN_LOGIN and "
            "INITIAL_ADMIN_PASSWORD (or SEED_DEMO_USERS=true for local development)"
        )
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
    """Yo'q modullarni qo'shadi, mavjudlarining sozlamasiga tegmaydi.
    Sabab _seed_permissions'dagi bilan bir xil: yangi bazada migratsiya
    bitta modulni o'zi yozadi va "jadval bo'shmi?" tekshiruvi qolganlarini
    hech qachon yaratmasdi."""
    existing = set((await db.execute(select(AIModuleConfig.code))).scalars().all())
    for m in DEFAULT_AI_MODULES:
        if m["code"] in existing:
            continue
        db.add(AIModuleConfig(**m, mode="sinov" if m["code"] in TRIAL_MODULE_CODES else "ishchi"))


# Kod egalik qiladigan hujjat maydonlari. Admin panel ularni tahrirlamaydi
# (AIModuleUpdateIn — faqat active/threshold/sensitivity/mode).
AI_MODULE_DOC_FIELDS = ("group", "name", "description", "method")


async def _sync_ai_module_docs(db: AsyncSession) -> None:
    """Mavjud bazadagi modul tavsiflarini koddagi (yuqoridagi) matn bilan
    tenglashtiradi.

    _seed_ai_modules faqat BO'SH jadvalni to'ldiradi, shuning uchun seed.py
    dagi tuzatilgan tavsiflar production bazasiga hech qachon yetib
    bormagan: 2026-09-17 da 18 ta modulning 7 tasida kodda yo'q texnologiya
    yozilgan edi ("YOLOv8-face, mahalliy GPU", "DeepSORT", "Gaze
    estimation"...). Admin sozlamalariga (active, threshold, sensitivity,
    mode) va o'lchangan ko'rsatkichlarga tegilmaydi."""
    for module in DEFAULT_AI_MODULES:
        await db.execute(
            update(AIModuleConfig)
            .where(AIModuleConfig.code == module["code"])
            .values(
                **{field: module[field] for field in AI_MODULE_DOC_FIELDS},
                has_detector=module.get("has_detector", True),
            )
        )
