"""Kamera roli (xona turi) va AI modullarini rolga qarab yo'naltirish.

MUAMMO. 2026-09-18 gacha har faol modul HAR kamerada ishlardi: 107
kameraning birortasida ham modul o'chirilmagan edi. Natijada:

  * uyqu (#20) kirish kameralarida o'tib ketayotgan odamni "uxlayapti"
    deb signal berardi (0.107, 0.113, 0.10, 0.11 — 4K kirish kameralari);
  * har bir ortiqcha tekshiruv AVX'siz CPU'da yuz tanish navbatini
    to'ldirardi — kirish eshigidagi davomat kadri shu navbatni kutardi.

YECHIM. Har kameraga xona turi beriladi (Camera.room_type) va modul faqat
o'ziga mos turdagi kamerada ishlaydi (MODULE_ROOM_TYPES). Ro'yxatda
bo'lmagan modul (masalan taqiqlangan zona) — xavfsizlik mezonlari —
har qanday kamerada, jumladan turi belgilanmagan kamerada ham ishlaydi.

Turi belgilanmagan kamera eski bayroqlardan tur oladi: kirish/chiqish
belgisi — "kirish", perimetr — "tashqi" (effective_room_type). Qolganlari
turi belgilanguncha faqat xavfsizlik mezonlarida qatnashadi: bilmagan
joyda uyqu yoki xalat qidirishdan ko'ra, admin turini belgilashini
kutgan to'g'ri.

Kunlik davomat (#6, #7) faqat kirish kameralarida — 2026-09-18 dagi
qaror: xona kameralari bir kunda ~5 kishini tanib, AI vaqtining katta
qismini olardi. Xona kameralari darslarni jadval orqali tekshiradi
(LessonSession.camera), bu yo'naltirishga bog'liq emas.
"""

from __future__ import annotations

import re

from sqlalchemy import and_, false, not_, or_, true
from sqlalchemy.sql import ColumnElement

from app.config import settings
from app.models import Camera

ROOM_TYPES: tuple[str, ...] = (
    "kirish",
    "auditoriya",
    "laboratoriya",
    "koridor",
    "ofis",
    "cheklangan",
    "tashqi",
)

ROOM_TYPE_LABELS: dict[str, str] = {
    "kirish": "Kirish/chiqish",
    "auditoriya": "Auditoriya (dars xonasi)",
    "laboratoriya": "Laboratoriya/klinika",
    "koridor": "Koridor/zina",
    "ofis": "Ofis/kafedra",
    "cheklangan": "Cheklangan xona",
    "tashqi": "Tashqi hudud (perimetr)",
}

# Modul kodi -> qaysi xona turlarida ishlaydi. Bu yerda YO'Q modul hamma
# kamerada ishlaydi (turi belgilanmagani ham).
MODULE_ROOM_TYPES: dict[int, frozenset[str]] = {
    # Begona shaxs — binoga kirish joylari va cheklangan xonalar.
    1: frozenset({"kirish", "tashqi", "cheklangan"}),
    # Kunlik davomat — faqat kirish eshigi (2026-09-18 qarori).
    6: frozenset({"kirish"}),
    7: frozenset({"kirish"}),
    # Uyqu — faqat dars xonasi.
    20: frozenset({"auditoriya"}),
}


def effective_room_type(camera) -> str | None:
    """Kameraning amaldagi turi: belgilangan tur, bo'lmasa eski bayroqlardan."""
    room_type = getattr(camera, "room_type", None)
    if room_type:
        return room_type
    if getattr(camera, "is_entrance", False) or getattr(camera, "is_exit", False):
        return "kirish"
    if getattr(camera, "is_perimeter", False):
        return "tashqi"
    return None


# Kamera NOMIDAN eshik kamerasini tanish: "Asosiy kirish", "2-kirish",
# "Entrance", "Вход". Productionda (2026-09-24) 107 kameradan birortasi ham
# kirish deb belgilanmagan, "Asosiy kirish" esa oddiy xona kamerasi kabi
# navbat kutib, substreamda tahlil qilinardi. "koridor" so'zi bo'lsa — bu
# yo'lak kamerasi, eshik emas.
_DOOR_NAME = re.compile(r"(?<![a-z])(kirish|entrance|vxod|вход)(?![a-z])", re.IGNORECASE)
_NOT_DOOR_NAME = re.compile(r"koridor|yo'lak", re.IGNORECASE)


def door_by_name(name: str | None) -> bool:
    return bool(name) and bool(_DOOR_NAME.search(name)) and not _NOT_DOOR_NAME.search(name)


def is_door_camera(camera) -> bool:
    """Eshik kamerasi: kirish/chiqish bayrog'i, "kirish" turi yoki nomida
    "kirish" (tur aniq boshqa deb belgilanmagan bo'lsa). Bunday kamera asosiy
    (4K) oqimda, navbatsiz tahlil qilinadi — odam eshikdan 2-3 s da o'tadi va
    yuzi faqat shu yerda oldidan ko'rinadi."""
    if getattr(camera, "is_entrance", False) is True or getattr(camera, "is_exit", False) is True:
        return True
    room_type = getattr(camera, "room_type", None)
    if room_type == "kirish":
        return True
    name = getattr(camera, "name", None)
    return room_type in (None, "") and isinstance(name, str) and door_by_name(name)


ATTENDANCE_MODULE_CODES = frozenset({6, 7})


def _rooms_for(module_code: int) -> frozenset[str] | None:
    """None — modul hamma kamerada. ATTENDANCE_ALL_CAMERAS yoqilgan bo'lsa,
    kunlik davomat (#6, #7) xona turidan qat'i nazar hamma kamerada."""
    if module_code in ATTENDANCE_MODULE_CODES and settings.attendance_all_cameras:
        return None
    return MODULE_ROOM_TYPES.get(module_code)


def role_allows(camera, module_code: int) -> bool:
    """Modul shu kameraning turida ishlaydimi (Python tomonidagi tekshiruv)."""
    allowed = _rooms_for(module_code)
    if allowed is None:
        return True
    return effective_room_type(camera) in allowed


def role_allows_clause(module_code: int) -> ColumnElement[bool]:
    """role_allows() ning SQL ko'rinishi — sweeplarning kamera so'roviga
    (module_status.camera_allows_module orqali) qo'shiladi. Ikkalasi bir xil
    natija berishi test bilan tekshiriladi (tests/test_camera_roles.py)."""
    allowed = _rooms_for(module_code)
    if allowed is None:
        return true()
    entrance = or_(Camera.is_entrance.is_(True), Camera.is_exit.is_(True))
    derived: list[ColumnElement[bool]] = []
    if "kirish" in allowed:
        derived.append(entrance)
    if "tashqi" in allowed:
        derived.append(and_(Camera.is_perimeter.is_(True), not_(entrance)))
    unset = and_(Camera.room_type.is_(None), or_(*derived)) if derived else false()
    return or_(Camera.room_type.in_(sorted(allowed)), unset)


# So'z oldida harf bo'lmasa: "211-xona" dagi "xona" olib tashlanadi,
# "Oshxona" esa o'zgarmaydi.
_ROOM_WORDS = re.compile(
    r"(?<![a-zа-яёўқғҳ])(xonasi|xona|auditoriyasi|auditoriya|aud|kabinet|каб|ауд)\.?|№", re.IGNORECASE
)
_NON_ALNUM = re.compile(r"[^0-9a-zа-яёўқғҳ]+", re.IGNORECASE)


def normalize_room_code(value: str | None) -> str | None:
    """Xona raqamini solishtirish uchun bir xil ko'rinishga keltiradi.

    Jadvalda "211", "211-xona", "Aud. 211", "211 xonasi" — hammasi bitta
    xona. Harflar kichik, "xona/auditoriya/aud" so'zlari va tinish
    belgilari olib tashlanadi: "A-201" -> "a201", "3-xona" -> "3"."""
    if value is None:
        return None
    text = _ROOM_WORDS.sub(" ", str(value).strip().lower())
    text = _NON_ALNUM.sub("", text)
    return text or None


_ROOM_NAME = re.compile(r"^\s*(\d{1,4}[a-zа-я]?)\s*-?\s*(xona|xonasi)?\s*$", re.IGNORECASE)


def guess_room_from_name(name: str | None) -> tuple[str | None, str | None]:
    """Kamera nomidan boshlang'ich tur va xona raqami: "27-xona" va "211"
    -> ("auditoriya", "27"/"211"). Faqat migratsiyadagi boshlang'ich
    to'ldirish uchun — admin keyin CSV yoki sahifada tuzatadi."""
    match = _ROOM_NAME.match(name or "")
    if not match:
        return None, None
    return "auditoriya", normalize_room_code(match.group(1))


FACE_ROI_MARGIN = 0.03
"""Eshik hududi chetidan qo'shimcha joy — chegarada turgan yuz qirqilib qolmasin."""


def face_roi_box(camera) -> tuple[float, float, float, float] | None:
    """Camera.face_roi poligonining normallashgan chegara to'rtburchagi
    (x1, y1, x2, y2), biroz kengaytirilgan. None — belgilanmagan yoki
    deyarli butun kadr (qirqishdan foyda yo'q)."""
    polygon = getattr(camera, "face_roi", None)
    if not polygon or len(polygon) < 3:
        return None
    try:
        xs = [float(point[0]) for point in polygon]
        ys = [float(point[1]) for point in polygon]
    except (TypeError, ValueError, IndexError):
        return None
    x1 = max(0.0, min(xs) - FACE_ROI_MARGIN)
    y1 = max(0.0, min(ys) - FACE_ROI_MARGIN)
    x2 = min(1.0, max(xs) + FACE_ROI_MARGIN)
    y2 = min(1.0, max(ys) + FACE_ROI_MARGIN)
    if x2 - x1 < 0.05 or y2 - y1 < 0.05:
        return None
    if (x2 - x1) * (y2 - y1) > 0.95:
        return None
    return (x1, y1, x2, y2)
