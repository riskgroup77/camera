"""HEMIS (hemis.uz — oliy ta'lim axborot tizimi) bilan sinxronlash.

Universitet HEMIS'ining REST API'sidan talabalar, xodimlar, guruhlar va
bo'linmalar (fakultet/kafedra) o'qiladi va tizimdagi ro'yxat shunga
moslashtiriladi:

    GET {hemis_base_url}/v1/data/student-list?page=1&limit=200
    Authorization: Bearer {hemis_api_token}
    -> {"success": true, "data": {"items": [...], "pagination": {"page", "pageCount", "totalCount"}}}

MOSLASHTIRISH TARTIBI (ehtiyotkor — noto'g'ri odamga yozishdan ko'ra
yangi qator yaratish yoki o'tkazib yuborish yaxshi):

  1. hemis_id (talaba: student_id_number, xodim: employee_id_number);
  2. JSHSHIR (passport_pin, 14 raqam) — agar u qatorga boshqa hemis_id
     biriktirilmagan bo'lsa;
  3. aniq (normallashtirilgan) F.I.Sh. — faqat HEMIS ro'yxatida ham,
     bazada ham (hemis_id'siz, JSHSHIRi boshqa bo'lmagan) YAGONA bo'lsa.

Topilgan qatorda ism, JSHSHIR (bo'sh bo'lsa), fakultet, guruh/lavozim va
faollik yangilanadi. Biometrik maydonlar (yuz rasmi, vektor, holat) va
karta raqami HECH QACHON o'zgartirilmaydi. Talaba qatori xodim sifatida
(yoki aksincha) qayta yozilmaydi — hisobotda "o'tkazildi" bo'lib chiqadi.

HEMIS versiyalari maydon nomlarida farq qiladi, shuning uchun har bir
yozuv kichik sof funksiyalar (map_student, map_employee, map_group,
map_department) orqali o'qiladi — ular testlar bilan qoplangan.

Har bir ishga tushirish integration_sync_runs jadvaliga yoziladi
(holat, statistika, xato) — admin panelda tarix ko'rinadi.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import defer, noload

from app.config import settings
from app.database import SessionLocal
from app.models import Department, Faculty, IntegrationSyncRun, StudentGroup, StudentStaff
from app.services.face_matching import announce_roster_change
from app.services.integrations.http import make_client
from app.services.name_matching import name_key, name_tokens

logger = logging.getLogger("app.integrations.hemis")

SOURCE = "hemis"
# "ishlamoqda" holatidagi yozuv shundan eski bo'lsa — jarayon o'lgan deb
# hisoblanadi (server qayta ishga tushgan va h.k.) va yangi sinxronlashga
# to'sqinlik qilmaydi.
RUN_STALE_AFTER = timedelta(hours=2)
# Qo'lda va jadval bo'yicha sinxronlash bir vaqtda boshlanmasligi uchun
# (bir nechta API worker'da ham) — tranzaksiya darajasidagi advisory lock.
_RUN_LOCK_KEY = 847_552_901_338

REQUEST_TIMEOUT_SECONDS = 30.0
MAX_ATTEMPTS = 4
# 5xx / 429 / tarmoq xatosida urinishlar orasidagi kutish (soniya).
BACKOFF_SECONDS = (1.0, 3.0, 8.0)
# Cheksiz sahifalashdan himoya (noto'g'ri pageCount qaytargan server).
MAX_PAGES = 5000
MAX_MESSAGES = 50

ENTITY_ENDPOINTS = {
    "departments": "department-list",
    "groups": "group-list",
    "students": "student-list",
    "employees": "employee-list",
}
ENTITY_LABELS = {
    "faculties": "Fakultetlar",
    "departments": "Kafedralar",
    "groups": "Guruhlar",
    "students": "Talabalar",
    "employees": "Xodimlar",
    "schedule": "Dars jadvali",
}


class HemisError(Exception):
    """HEMIS bilan ishlashdagi xato — matni admin panelda ko'rsatiladi."""


class HemisAuthError(HemisError):
    """Token yaroqsiz (401/403) — qayta urinishning ma'nosi yo'q."""


class HemisNotConfiguredError(HemisError):
    pass


def hemis_configured() -> bool:
    return bool(settings.hemis_base_url.strip() and settings.hemis_api_token.strip())


# ── Sof moslashtirish funksiyalari ─────────────────────────────────────────

_APOSTROPHES = "‘’`ʻʼ´"
# Otasining ismidan keyingi qo'shimchalar — kichik harf bilan yoziladi.
_PARTICLES = {"qizi", "o'g'li", "kizi", "ogli", "o'gli", "ugli", "uli"}
_FACULTY_WORDS = ("fakultet", "faculty", "факультет")
_KAFEDRA_WORDS = ("kafedra", "кафедра", "chair", "department")
# HEMIS klassifikatori (h_structure_type): 11 — fakultet, 12 — kafedra.
_FACULTY_CODES = {"11"}
_KAFEDRA_CODES = {"12"}
# Talaba holati (h_student_status): 11 o'qimoqda, 12 akademik ta'tilda,
# 13 chetlashtirilgan, 14 bitirgan. Nomi bo'yicha tekshiruv ustun — kodlar
# universitetlarda bir xil ekani kafolatlanmagan.
_STUDENT_INACTIVE_CODES = {"13", "14"}
_STUDENT_INACTIVE_WORDS = (
    "chetlash", "bitir", "tugatgan", "expel", "graduat", "отчисл", "выпуск", "o'qishdan chiqarilgan",
)
_EMPLOYEE_INACTIVE_WORDS = ("bo'shagan", "boshagan", "ishdan ketgan", "dismiss", "fired", "уволен", "нофаол")
_MAIN_EMPLOYMENT_WORDS = ("asosiy", "основ", "main")


def _text(value: Any) -> str:
    if value is None or isinstance(value, (dict, list)):
        return ""
    return " ".join(str(value).split())


def ref_name(value: Any) -> str:
    """HEMIS'da bog'langan obyekt {"id", "code", "name"} ko'rinishida yoki
    ba'zi versiyalarda to'g'ridan-to'g'ri matn bo'ladi."""
    if isinstance(value, dict):
        return _text(value.get("name"))
    return _text(value)


def ref_code(value: Any) -> str:
    if isinstance(value, dict):
        return _text(value.get("code"))
    return ""


def ref_id(value: Any) -> str:
    if isinstance(value, dict):
        return _text(value.get("id"))
    return _text(value)


def pick(item: dict, *keys: str) -> Any:
    """Birinchi bo'sh bo'lmagan maydon — HEMIS versiyalarida nomlar farq qiladi."""
    for key in keys:
        value = item.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def clean_pinfl(value: Any) -> str | None:
    """JSHSHIR — aynan 14 raqam; boshqa har qanday qiymat e'tiborsiz."""
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return digits if len(digits) == 14 else None


def format_person_name(raw: str) -> str:
    """"TO‘XTAYEVA MALIKA SHERZOD QIZI" -> "To'xtayeva Malika Sherzod qizi".

    HEMIS ismlarni ko'pincha bosh harflarda beradi, tizimdagi qolgan
    yozuvlar esa (scripts/import_talabalar.py) o'qiladigan ko'rinishda.
    Aralash registrda kelgan ism o'z holicha qoldiriladi."""
    text_value = raw or ""
    for ch in _APOSTROPHES:
        text_value = text_value.replace(ch, "'")
    text_value = " ".join(text_value.split())
    letters = [ch for ch in text_value if ch.isalpha()]
    if not letters or not all(ch.isupper() for ch in letters):
        return text_value
    words: list[str] = []
    for token in text_value.split():
        low = token.lower()
        if low in _PARTICLES:
            words.append(low)
            continue
        words.append("-".join(part[:1].upper() + part[1:] for part in low.split("-")))
    return " ".join(words)


def build_full_name(item: dict) -> str:
    full = _text(pick(item, "full_name", "fullName", "name"))
    if not full:
        parts = [_text(item.get(k)) for k in ("second_name", "first_name", "third_name")]
        full = " ".join(p for p in parts if p)
    return format_person_name(full)


def parse_course(level: Any) -> int | None:
    """Kurs: {"code": "13", "name": "3-kurs"} -> 3. Avval nomdagi raqam,
    keyin klassifikator kodi (11..19 -> 1..9)."""
    name = ref_name(level)
    match = re.search(r"\d+", name)
    if match:
        course = int(match.group())
        if 1 <= course <= 9:
            return course
    code = ref_code(level) or (_text(level) if not isinstance(level, dict) else "")
    if code.isdigit():
        value = int(code)
        if 11 <= value <= 19:
            return value - 10
        if 1 <= value <= 9:
            return value
    return None


def structure_kind(unit: dict | None) -> str | None:
    """Bo'linma turi: 'fakultet', 'kafedra' yoki None (bo'lim, markaz va h.k.)."""
    if not isinstance(unit, dict):
        return None
    structure = unit.get("structureType") or unit.get("structure_type")
    name = ref_name(structure).lower()
    if any(word in name for word in _FACULTY_WORDS):
        return "fakultet"
    if any(word in name for word in _KAFEDRA_WORDS):
        return "kafedra"
    code = ref_code(structure) or (_text(structure) if not isinstance(structure, dict) else "")
    if code in _FACULTY_CODES:
        return "fakultet"
    if code in _KAFEDRA_CODES:
        return "kafedra"
    return None


def _status_inactive(status: Any, words: tuple[str, ...], codes: set[str]) -> bool:
    name = ref_name(status).lower()
    for ch in _APOSTROPHES:
        name = name.replace(ch, "'")
    if name:
        return any(word in name for word in words)
    return ref_code(status) in codes


def is_student_active(item: dict) -> bool:
    if item.get("is_graduate") is True:
        return False
    status = pick(item, "studentStatus", "student_status", "status")
    if status is None:
        return True
    return not _status_inactive(status, _STUDENT_INACTIVE_WORDS, _STUDENT_INACTIVE_CODES)


def is_employee_active(item: dict) -> bool:
    if item.get("active") is False:
        return False
    status = pick(item, "employeeStatus", "employee_status", "status")
    if status is None:
        return True
    return not _status_inactive(status, _EMPLOYEE_INACTIVE_WORDS, set())


@dataclass
class HemisUnit:
    hemis_id: str
    name: str
    kind: str | None  # 'fakultet' | 'kafedra' | None
    parent_id: str | None
    # HEMIS structureType kodi (16 rektorat, 11 fakultet, 12 kafedra, 13 bo'lim, ...).
    code: str | None = None


@dataclass
class HemisGroup:
    hemis_id: str
    name: str
    faculty_name: str | None
    course: int | None


@dataclass
class HemisPerson:
    type: str  # 'talaba' | 'xodim'
    hemis_id: str
    full_name: str
    pinfl: str | None
    faculty_name: str | None
    group_name: str | None
    course: int | None
    position: str | None
    department_name: str | None
    active: bool
    main_employment: bool = True
    # HEMIS rasmi (image_full, bo'lmasa image) — yuzi yo'q odamni tanitish uchun.
    photo_url: str | None = None
    # Xodim: HEMIS department.id (tuzilmadagi bo'linmasi).
    department_id: str | None = None

    @property
    def group_or_position(self) -> str:
        """Talaba: "2-kurs, DI-2301" — tizimning qolgan qismi (kurs filtri,
        dars davomati, eksport) aynan shu shaklni o'qiydi
        (app/services/staff_export.split_course). Xodim: kafedra/bo'lim,
        bo'lmasa lavozim."""
        if self.type == "talaba":
            if self.course and self.group_name:
                return f"{self.course}-kurs, {self.group_name}"
            if self.group_name:
                return self.group_name
            if self.course:
                return f"{self.course}-kurs"
            return "Talaba"
        return self.department_name or self.position or "Xodim"


def map_department(item: dict) -> HemisUnit | None:
    unit_id = ref_id(item.get("id"))
    name = _text(item.get("name"))
    if not unit_id or not name:
        return None
    parent = item.get("parent")
    parent_id = ref_id(parent) if parent not in (None, "", 0) else None
    structure = item.get("structureType") or item.get("structure_type")
    return HemisUnit(
        hemis_id=unit_id, name=name, kind=structure_kind(item), parent_id=parent_id or None,
        code=ref_code(structure) or None,
    )


def map_group(item: dict) -> HemisGroup | None:
    group_id = ref_id(item.get("id"))
    name = _text(item.get("name"))
    if not name:
        return None
    faculty = pick(item, "faculty", "department")
    course = parse_course(pick(item, "level", "course"))
    return HemisGroup(hemis_id=group_id, name=name, faculty_name=ref_name(faculty) or None, course=course)


def photo_url(item: dict) -> str | None:
    url = _text(pick(item, "image_full", "image"))
    return url if url.startswith(("http://", "https://")) else None


def map_student(item: dict) -> HemisPerson | None:
    """None — yozuvni aniqlab bo'lmaydi (identifikator yoki ism yo'q)."""
    hemis_id = _text(pick(item, "student_id_number", "studentIdNumber", "student_id"))
    full_name = build_full_name(item)
    if not hemis_id or not full_name:
        return None
    # Talabaning "department"i HEMIS'da — fakultet.
    faculty = pick(item, "faculty") or pick(item, "department")
    group = item.get("group")
    return HemisPerson(
        type="talaba",
        hemis_id=hemis_id,
        full_name=full_name,
        pinfl=clean_pinfl(pick(item, "passport_pin", "passportPin", "pinfl", "jshshir")),
        faculty_name=ref_name(faculty) or None,
        group_name=ref_name(group) or None,
        course=parse_course(pick(item, "level", "course")),
        position=None,
        department_name=None,
        active=is_student_active(item),
        photo_url=photo_url(item),
    )


def map_employee(item: dict, units: dict[str, HemisUnit] | None = None) -> HemisPerson | None:
    """`units` — department-list natijasi (id bo'yicha): kafedraning
    fakulteti uning "parent"idan topiladi."""
    hemis_id = _text(pick(item, "employee_id_number", "employeeIdNumber", "employee_id"))
    full_name = build_full_name(item)
    if not hemis_id or not full_name:
        return None
    department = item.get("department")
    department_name = ref_name(department) or None
    faculty_name: str | None = None
    kind = structure_kind(department) if isinstance(department, dict) else None
    if kind == "fakultet":
        faculty_name = department_name
    elif isinstance(department, dict) and units:
        unit = units.get(ref_id(department.get("id")))
        if unit is not None and unit.kind == "fakultet":
            faculty_name = unit.name
        else:
            parent_id = ref_id(department.get("parent")) or (unit.parent_id if unit else None)
            parent = units.get(parent_id) if parent_id else None
            if parent is not None and parent.kind == "fakultet":
                faculty_name = parent.name
    employment = ref_name(pick(item, "employmentForm", "employment_form")).lower()
    return HemisPerson(
        type="xodim",
        hemis_id=hemis_id,
        full_name=full_name,
        pinfl=clean_pinfl(pick(item, "passport_pin", "passportPin", "pinfl", "jshshir")),
        faculty_name=faculty_name,
        group_name=None,
        course=None,
        position=ref_name(pick(item, "staffPosition", "staff_position", "position")) or None,
        department_name=department_name,
        active=is_employee_active(item),
        main_employment=not employment or any(word in employment for word in _MAIN_EMPLOYMENT_WORDS),
        photo_url=photo_url(item),
        department_id=ref_id(department.get("id")) if isinstance(department, dict) else None,
    )


_KINSHIP = {"ogli", "ugli", "ogl", "kizi", "qizi", "kiz"}


def fuzzy_name_key(full_name: str | None) -> str:
    """Imlo farqlariga chidamli kalit: "USAROV BARKAMOL BAXODIR O'G'LI" va
    "Usarov Barkamol Bahodir o'g'li" bir xil. O'g'li/qizi va ota ismining
    -ovich/-ovna qo'shimchasi e'tiborsiz."""
    tokens = [t for t in name_tokens(full_name) if t not in _KINSHIP]
    tokens = [re.sub(r"(ovich|evich|ovna|evna)$", "", t) for t in tokens]
    return " ".join(tokens)


def short_name_key(full_name: str | None) -> str:
    """Familiya + ism (imloga chidamli) — otasining ismisiz."""
    return " ".join(fuzzy_name_key(full_name).split()[:2])


def patronymic_compatible(a: str | None, b: str | None) -> bool:
    """Otasining ismi zid emas: bittasida yo'q yoki birinchi 4 harfi bir xil
    ("Bahodir"/"Baxodirovich" -> "bahodir"/"bahodir")."""
    pa, pb = fuzzy_name_key(a).split()[2:3], fuzzy_name_key(b).split()[2:3]
    return not pa or not pb or pa[0][:4] == pb[0][:4]


def group_code(text: str | None) -> str:
    """Guruh kodi: "2-kurs, DI-2301" va "DI-2301" -> "2301"."""
    found = re.findall(r"[0-9]{3,}[a-z]?", (text or "").lower())
    return found[-1] if found else ""


def dedupe_people(people: list[HemisPerson]) -> tuple[list[HemisPerson], int]:
    """Xodim HEMIS'da har bir lavozimi uchun alohida qator bo'lib keladi
    (asosiy + o'rindoshlik). Bitta odam — bitta yozuv: asosiy ish joyi
    ustun, faol qator faol bo'lmaganidan ustun."""
    chosen: dict[str, HemisPerson] = {}
    duplicates = 0
    for person in people:
        current = chosen.get(person.hemis_id)
        if current is None:
            chosen[person.hemis_id] = person
            continue
        duplicates += 1
        better = (person.active, person.main_employment) > (current.active, current.main_employment)
        if better:
            chosen[person.hemis_id] = person
    return list(chosen.values()), duplicates


def faculty_key(name: str) -> str:
    """"Davolash ishi fakulteti" va "Davolash ishi" — bitta fakultet
    (scripts/import_xodimlar._fac_key bilan bir xil qoida)."""
    key = " ".join(name.strip().lower().split())
    for ch in _APOSTROPHES:
        key = key.replace(ch, "'")
    for suffix in (" fakulteti", " fakultet", " faculty", " факультет"):
        if key.endswith(suffix):
            key = key[: -len(suffix)]
    return key.strip()


@dataclass
class HemisPage:
    items: list[dict]
    page: int
    page_count: int
    total_count: int


def parse_page(payload: Any, *, requested_page: int = 1) -> HemisPage:
    if not isinstance(payload, dict):
        raise HemisError("HEMIS javobi kutilgan ko'rinishda emas")
    if payload.get("success") is False:
        message = _text(payload.get("error")) or _text(payload.get("message")) or "noma'lum xato"
        raise HemisError(f"HEMIS xato qaytardi: {message}")
    data = payload.get("data")
    if isinstance(data, list):
        return HemisPage(items=[i for i in data if isinstance(i, dict)], page=requested_page, page_count=1, total_count=len(data))
    if not isinstance(data, dict):
        raise HemisError("HEMIS javobida 'data' yo'q")
    items = data.get("items") or []
    if not isinstance(items, list):
        raise HemisError("HEMIS javobida 'items' ro'yxat emas")
    pagination = data.get("pagination") or {}

    def _int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    return HemisPage(
        items=[i for i in items if isinstance(i, dict)],
        page=_int(pagination.get("page"), requested_page),
        page_count=max(1, _int(pagination.get("pageCount"), 1)),
        total_count=_int(pagination.get("totalCount"), len(items)),
    )


# ── HTTP mijoz ──────────────────────────────────────────────────────────────


class HemisClient:
    """HEMIS REST API mijozi: sahifalash, qayta urinish (5xx, 429, tarmoq),
    401/403 uchun aniq xato."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        page_size: int | None = None,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.base_url = (base_url if base_url is not None else settings.hemis_base_url).strip().rstrip("/")
        self.token = (token if token is not None else settings.hemis_api_token).strip()
        self.page_size = max(1, min(page_size or settings.hemis_page_size, 1000))
        self._sleep = sleep
        self._client: httpx.AsyncClient | None = None
        if not self.base_url or not self.token:
            raise HemisNotConfiguredError("HEMIS sozlanmagan: HEMIS_BASE_URL va HEMIS_API_TOKEN kerak")

    async def __aenter__(self) -> HemisClient:
        self._client = make_client(
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
        )
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _url(self, endpoint: str) -> str:
        return f"{self.base_url}/v1/data/{endpoint}"

    async def _get_json(self, endpoint: str, params: dict[str, Any]) -> Any:
        assert self._client is not None, "HemisClient `async with` ichida ishlatiladi"
        url = self._url(endpoint)
        last_error = ""
        for attempt in range(MAX_ATTEMPTS):
            retryable = False
            try:
                response = await self._client.get(url, params=params)
            except httpx.TimeoutException:
                last_error = f"HEMIS javob bermadi ({REQUEST_TIMEOUT_SECONDS:.0f} s)"
                retryable = True
            except httpx.TransportError as exc:
                last_error = f"HEMIS'ga ulanib bo'lmadi: {type(exc).__name__}"
                retryable = True
            else:
                if response.status_code == 401:
                    raise HemisAuthError("HEMIS token yaroqsiz yoki muddati o'tgan (401) — HEMIS_API_TOKEN ni tekshiring")
                if response.status_code == 403:
                    raise HemisAuthError("HEMIS token bu ma'lumotga ruxsat bermaydi (403)")
                if response.status_code == 404:
                    raise HemisError(f"HEMIS manzili topilmadi (404): {url} — HEMIS_BASE_URL ni tekshiring")
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = f"HEMIS server xatosi ({response.status_code})"
                    retryable = True
                elif response.status_code >= 400:
                    raise HemisError(f"HEMIS so'rovni rad etdi ({response.status_code})")
                else:
                    try:
                        return response.json()
                    except ValueError:
                        raise HemisError("HEMIS javobi JSON emas — HEMIS_BASE_URL API manzilimi?") from None
            if retryable and attempt < MAX_ATTEMPTS - 1:
                delay = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
                logger.warning(
                    "HEMIS request failed, retrying",
                    extra={"event": "hemis_retry", "endpoint": endpoint, "attempt": attempt + 1, "error": last_error},
                )
                await self._sleep(delay)
        raise HemisError(f"{last_error} — {MAX_ATTEMPTS} marta urinildi")

    async def fetch_page(
        self, endpoint: str, page: int = 1, limit: int | None = None, params: dict[str, Any] | None = None
    ) -> HemisPage:
        payload = await self._get_json(endpoint, {**(params or {}), "page": page, "limit": limit or self.page_size})
        return parse_page(payload, requested_page=page)

    async def fetch_all(
        self,
        endpoint: str,
        on_page: Callable[[int, int], Awaitable[None]] | None = None,
        params: dict[str, Any] | None = None,
    ) -> list[dict]:
        """Barcha sahifalar. `on_page(page, page_count)` — jarayonni ko'rsatish uchun.
        `params` — qo'shimcha filtrlar (masalan employee-list uchun type)."""
        items: list[dict] = []
        page = 1
        expected = 0
        while True:
            result = await self.fetch_page(endpoint, page, params=params)
            items.extend(result.items)
            expected = max(expected, result.total_count)
            if on_page is not None:
                await on_page(page, result.page_count)
            if page >= result.page_count or not result.items or page >= MAX_PAGES:
                break
            page += 1
        # Kichik farqqa (HEMIS totalCount ba'zan bir-ikki yozuvga noaniq) chidaymiz.
        if expected and len(items) < expected - max(5, expected // 50):
            # Chala javob (bo'sh sahifa o'rtada, pageCount yo'q): keyingi
            # qadamlar ro'yxatda yo'qlarni faolsizlantiradi — shuning uchun
            # to'xtatamiz, qisman ro'yxat bilan ishlamaymiz.
            raise HemisError(f"HEMIS {endpoint}: {len(items)} ta keldi, {expected} ta kutilgan — chala javob")
        return items


def _looks_complete(fetched: int, stored: int) -> bool:
    """HEMIS ro'yxati to'liqmi — "ro'yxatda yo'q" = "ketgan" deyish uchun.
    Bittadan ortiq sinxronda yarmidan ko'pi birdan yo'qolmaydi: bunday
    javob uzilgan/chala deb hisoblanadi (hemis_schedule bilan bir qoida)."""
    return stored < 20 or fetched >= stored * 0.8


# employee-list "type" parametrisiz 400 qaytaradi ("Kerakli parametrlar
# yetishmayapti: type"). fjsti'da (2026-09-25): teacher — 669, employee — 323;
# bir odam ikkalasida bo'lishi mumkin, shuning uchun HEMIS id bo'yicha birlashtiriladi.
EMPLOYEE_TYPES = ("teacher", "employee")


def employee_numbers(items: list[dict]) -> dict[str, str]:
    """HEMIS employee.id -> employee_id_number (StudentStaff.hemis_id)."""
    out: dict[str, str] = {}
    for item in items:
        number = _text(pick(item, "employee_id_number", "employeeIdNumber", "employee_id"))
        if item.get("id") is not None and number:
            out[str(item["id"])] = number
    return out


async def fetch_employees(
    client: HemisClient, on_page: Callable[[int, int], Awaitable[None]] | None = None
) -> list[dict]:
    seen: set = set()
    items: list[dict] = []
    for kind in EMPLOYEE_TYPES:
        for item in await client.fetch_all(ENTITY_ENDPOINTS["employees"], on_page=on_page, params={"type": kind}):
            key = item.get("id") if item.get("id") is not None else id(item)
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
    return items


# ── Sinxronlash ─────────────────────────────────────────────────────────────

_ENTITY_COUNTERS = ("fetched", "created", "updated", "unchanged", "deactivated", "skipped", "errors")


def empty_stats() -> dict:
    return {
        **{entity: {key: 0 for key in _ENTITY_COUNTERS} for entity in ENTITY_LABELS},
        "progress": {"stage": "boshlanmoqda", "done": 0, "total": 0},
        "messages": [],
    }


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Fon vazifalari — GC ularni yo'q qilmasligi uchun havola saqlanadi.
_background_tasks: set[asyncio.Task] = set()
# Testlar o'z bazasini beradi.
session_factory: async_sessionmaker[AsyncSession] = SessionLocal


async def start_run(db: AsyncSession, triggered_by: str) -> IntegrationSyncRun | None:
    """Yangi sinxronlash yozuvi; None — boshqasi hozir ishlamoqda.

    Advisory lock tranzaksiya oxirigacha ushlanadi: ikki worker bir paytda
    "ishlayotgan yo'q" deb ko'rib, ikkalasi ham boshlab yubormaydi."""
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _RUN_LOCK_KEY})
    now = _utcnow()
    running = (
        await db.execute(
            select(IntegrationSyncRun)
            .where(IntegrationSyncRun.source == SOURCE)
            .where(IntegrationSyncRun.status == "ishlamoqda")
        )
    ).scalars().all()
    for run in running:
        if run.started_at is not None and run.started_at > now - RUN_STALE_AFTER:
            # commit (rollback emas): lock bo'shaydi, chaqiruvchining
            # obyektlari esa eskirgan (expired) holatga tushmaydi.
            await db.commit()
            return None
        run.status = "xato"
        run.finished_at = now
        run.error = "Sinxronlash yakunlanmay qolgan (jarayon to'xtagan)"
    run = IntegrationSyncRun(
        source=SOURCE, status="ishlamoqda", triggered_by=triggered_by[:200], started_at=now, stats=empty_stats()
    )
    db.add(run)
    await db.commit()
    return run


async def launch_sync(db: AsyncSession, triggered_by: str) -> IntegrationSyncRun | None:
    """Qo'lda sinxronlash: yozuv yaratiladi, ish esa fonda bajariladi."""
    run = await start_run(db, triggered_by)
    if run is None:
        return None
    task = asyncio.create_task(run_sync(run.id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return run


async def run_sync(run_id: uuid.UUID, factory: async_sessionmaker[AsyncSession] | None = None) -> None:
    """Sinxronlashni bajaradi va natijani run yozuviga saqlaydi. Hech qachon
    istisno chiqarmaydi — xato run.error'ga yoziladi."""
    factory = factory or session_factory
    async with factory() as db:
        run = await db.get(IntegrationSyncRun, run_id)
        if run is None:
            return
        sync = _HemisSync(db, run)
        try:
            async with HemisClient() as client:
                await sync.run(client)
        except HemisError as exc:
            sync.fail(str(exc))
        except Exception as exc:  # noqa: BLE001 — har qanday xato tarixda ko'rinishi kerak
            logger.exception("HEMIS sync crashed", extra={"event": "hemis_sync_crash"})
            try:
                await db.rollback()
            except Exception:
                logger.warning("rollback failed after HEMIS sync crash", exc_info=True)
            sync.fail(f"Kutilmagan xato: {type(exc).__name__}: {exc}"[:500])
        await sync.finish()


class _HemisSync:
    def __init__(self, db: AsyncSession, run: IntegrationSyncRun) -> None:
        self.db = db
        self.run_id = run.id
        self.stats = empty_stats()
        self.step_errors: list[str] = []
        self.fatal_error: str | None = None
        self.units: dict[str, HemisUnit] = {}
        # HEMIS department id -> OrgUnit.id (tuzilma; app/services/org_structure.py).
        self.org_units: dict[str, uuid.UUID] = {}
        # HEMIS employee.id -> employee_id_number (dars jadvalidagi o'qituvchini topish uchun).
        self.employee_numbers: dict[str, str] = {}
        self.touched_faculty_ids: set[uuid.UUID] = set()
        # Talabalar ro'yxatidan: guruh nomi -> kurslar, faol talabalar soni.
        self.group_courses: dict[str, Counter] = defaultdict(Counter)
        self.group_members: Counter = Counter()
        self.students_loaded = False
        self._faculties: dict[str, Faculty] | None = None
        # Kimdir faollashtirildi/faolsizlantirildi — yuz tanish keshi
        # yangilanishi kerak (faol bo'lmagan odam tanilmasligi uchun).
        self.roster_changed = False

    # ── holat ──
    def message(self, text_value: str) -> None:
        messages = self.stats["messages"]
        if len(messages) < MAX_MESSAGES:
            messages.append(text_value[:300])

    def fail(self, error: str) -> None:
        self.fatal_error = error

    async def _save_progress(self, stage: str, done: int, total: int) -> None:
        self.stats["progress"] = {"stage": stage, "done": done, "total": total}
        run = await self.db.get(IntegrationSyncRun, self.run_id)
        if run is not None:
            run.stats = _copy_stats(self.stats)
        await self.db.commit()

    async def finish(self) -> None:
        errors = ([self.fatal_error] if self.fatal_error else []) + self.step_errors
        self.stats["progress"] = {"stage": "tugadi", "done": 0, "total": 0}
        try:
            run = await self.db.get(IntegrationSyncRun, self.run_id)
            if run is None:
                return
            run.stats = _copy_stats(self.stats)
            run.finished_at = _utcnow()
            run.status = "xato" if errors else "muvaffaqiyatli"
            run.error = "; ".join(errors)[:2000] if errors else None
            await self.db.commit()
        except Exception:
            logger.exception("could not store HEMIS sync result", extra={"event": "hemis_sync_store_failed"})
        if self.roster_changed:
            # Commit'dan keyin: boshqa jarayonlar keshni qayta yuklaganda
            # yangi holatni ko'rsin.
            try:
                await announce_roster_change()
            except Exception:
                logger.warning("face roster change announcement failed", exc_info=True)
        logger.info(
            "HEMIS sync finished",
            extra={"event": "hemis_sync_done", "status": "xato" if errors else "muvaffaqiyatli", "stats": self.stats},
        )

    # ── asosiy oqim ──
    async def run(self, client: HemisClient) -> None:
        for entity, handler in (
            ("departments", self._sync_departments),
            ("students", self._sync_students),
            ("groups", self._sync_groups),
            ("employees", self._sync_employees),
            ("schedule", self._sync_schedule),
        ):
            try:
                await handler(client)
            except HemisAuthError:
                raise
            except HemisError as exc:
                self.stats[entity]["errors"] += 1
                self.step_errors.append(f"{ENTITY_LABELS[entity]}: {exc}")
            except Exception as exc:  # noqa: BLE001 — bitta bosqich xatosi qolganlarini to'xtatmaydi
                logger.exception("HEMIS sync step failed", extra={"event": "hemis_step_failed", "entity": entity})
                await self.db.rollback()
                self._faculties = None
                self.stats[entity]["errors"] += 1
                self.step_errors.append(f"{ENTITY_LABELS[entity]}: {type(exc).__name__}: {exc}"[:500])
        await self._update_faculty_counts()
        await self.db.commit()

    async def _fetch(self, client: HemisClient, entity: str) -> list[dict]:
        label = ENTITY_LABELS[entity]

        async def on_page(page: int, page_count: int) -> None:
            await self._save_progress(f"{label}: yuklab olinmoqda", page, page_count)

        if entity == "employees":
            items = await fetch_employees(client, on_page=on_page)
        else:
            items = await client.fetch_all(ENTITY_ENDPOINTS[entity], on_page=on_page)
        self.stats[entity]["fetched"] = len(items)
        return items

    # ── fakultet / kafedra ──
    async def _faculty_map(self) -> dict[str, Faculty]:
        if self._faculties is None:
            rows = (await self.db.execute(select(Faculty))).scalars().all()
            self._faculties = {faculty_key(f.name): f for f in rows}
        return self._faculties

    async def ensure_faculty(self, name: str | None) -> Faculty | None:
        if not name or not faculty_key(name):
            return None
        faculties = await self._faculty_map()
        key = faculty_key(name)
        faculty = faculties.get(key)
        if faculty is None:
            faculty = Faculty(name=name[:200], course_count=0, student_count=0)
            async with self.db.begin_nested():
                self.db.add(faculty)
            faculties[key] = faculty
            self.stats["faculties"]["created"] += 1
        return faculty

    async def _sync_departments(self, client: HemisClient) -> None:
        items = await self._fetch(client, "departments")
        departments = {
            " ".join(d.name.lower().split()): d for d in (await self.db.execute(select(Department))).scalars().all()
        }
        faculties_before = await self._faculty_map()
        for item in items:
            unit = map_department(item)
            if unit is None:
                self.stats["departments"]["skipped"] += 1
                continue
            self.units[unit.hemis_id] = unit
            if unit.kind == "fakultet":
                if faculty_key(unit.name) in faculties_before:
                    self.stats["faculties"]["unchanged"] += 1
                faculty = await self.ensure_faculty(unit.name)
                if faculty is not None:
                    self.touched_faculty_ids.add(faculty.id)
            elif unit.kind == "kafedra":
                key = " ".join(unit.name.lower().split())
                if key in departments:
                    self.stats["departments"]["unchanged"] += 1
                    continue
                department = Department(name=unit.name[:300])
                async with self.db.begin_nested():
                    self.db.add(department)
                departments[key] = department
                self.stats["departments"]["created"] += 1
        await self._sync_org_units()
        await self.db.commit()

    async def _sync_org_units(self) -> None:
        """Butun tuzilma (rektorat, fakultet, kafedra, bo'lim, markaz, ...)
        OrgUnit jadvaliga: hemis_id bo'yicha yangilanadi, ota bo'linma bog'lanadi,
        HEMIS'dan yo'qolgani faolsizlantiriladi."""
        from app.models import OrgUnit
        from app.services.org_structure import org_kind

        existing = {u.hemis_id: u for u in (await self.db.execute(select(OrgUnit))).scalars().all() if u.hemis_id}
        for unit in self.units.values():
            kind = org_kind(unit.code, unit.name)
            row = existing.get(unit.hemis_id)
            if row is None:
                row = OrgUnit(hemis_id=unit.hemis_id, name=unit.name[:300], kind=kind, active=True)
                self.db.add(row)
                existing[unit.hemis_id] = row
            else:
                row.name, row.kind, row.active = unit.name[:300], kind, True
        await self.db.flush()
        for unit in self.units.values():
            row = existing[unit.hemis_id]
            parent = existing.get(unit.parent_id) if unit.parent_id else None
            row.parent_id = parent.id if parent is not None and parent.id != row.id else None
        stored_active = sum(1 for row in existing.values() if row.active)
        if _looks_complete(len(self.units), stored_active):
            for hemis_id, row in existing.items():
                if hemis_id not in self.units:
                    row.active = False
        else:
            self.message(
                f"Bo'linmalar: {len(self.units)} ta keldi, bazada {stored_active} ta faol — "
                "chala javob bo'lishi mumkin, hech biri faolsizlantirilmadi"
            )
        self.org_units = {hemis_id: row.id for hemis_id, row in existing.items()}

    # ── guruhlar ──
    async def _sync_groups(self, client: HemisClient) -> None:
        items = await self._fetch(client, "groups")
        stats = self.stats["groups"]
        existing: dict[str, StudentGroup] = {}
        for group in (await self.db.execute(select(StudentGroup).options(noload(StudentGroup.faculty)))).scalars().all():
            existing.setdefault(group.name, group)
        seen: set[str] = set()
        for item in items:
            mapped = map_group(item)
            if mapped is None or mapped.name in seen:
                stats["skipped"] += 1
                continue
            seen.add(mapped.name)
            faculty = await self.ensure_faculty(mapped.faculty_name)
            course_counts = self.group_courses.get(mapped.name)
            course = course_counts.most_common(1)[0][0] if course_counts else mapped.course
            current = existing.get(mapped.name)
            if faculty is None:
                stats["skipped"] += 1
                self.message(f"Guruh {mapped.name}: fakulteti aniqlanmadi — o'tkazildi")
                continue
            self.touched_faculty_ids.add(faculty.id)
            if current is None:
                if not course:
                    stats["skipped"] += 1
                    self.message(f"Guruh {mapped.name}: kursi aniqlanmadi — o'tkazildi")
                    continue
                async with self.db.begin_nested():
                    self.db.add(
                        StudentGroup(
                            name=mapped.name[:200],
                            faculty_id=faculty.id,
                            course=course,
                            student_count=self.group_members.get(mapped.name, 0),
                        )
                    )
                stats["created"] += 1
                continue
            changed = False
            if current.faculty_id != faculty.id:
                current.faculty_id = faculty.id
                changed = True
            if course and current.course != course:
                current.course = course
                changed = True
            if self.students_loaded and current.student_count != self.group_members.get(mapped.name, 0):
                current.student_count = self.group_members.get(mapped.name, 0)
                changed = True
            stats["updated" if changed else "unchanged"] += 1
        await self.db.commit()

    # ── odamlar ──
    async def _sync_students(self, client: HemisClient) -> None:
        items = await self._fetch(client, "students")
        people: list[HemisPerson] = []
        for item in items:
            person = map_student(item)
            if person is None:
                self.stats["students"]["skipped"] += 1
                continue
            people.append(person)
        people, duplicates = dedupe_people(people)
        if duplicates:
            self.stats["students"]["skipped"] += duplicates
        for person in people:
            if person.active and person.group_name:
                self.group_members[person.group_name] += 1
                if person.course:
                    self.group_courses[person.group_name][person.course] += 1
        self.students_loaded = True
        await self._sync_people("students", "talaba", people)

    async def _sync_employees(self, client: HemisClient) -> None:
        items = await self._fetch(client, "employees")
        self.employee_numbers = employee_numbers(items)
        people: list[HemisPerson] = []
        for item in items:
            person = map_employee(item, self.units)
            if person is None:
                self.stats["employees"]["skipped"] += 1
                continue
            people.append(person)
        # Bir odamning bir nechta lavozimi — xato emas, alohida hisoblanmaydi.
        people, _ = dedupe_people(people)
        await self._sync_people("employees", "xodim", people)
        from app.services.org_structure import link_unassigned_staff

        linked = await link_unassigned_staff(self.db)
        if linked:
            self.message(f"HEMIS'da yo'q {linked} xodim bo'lim nomi bo'yicha tuzilmaga bog'landi")
        await self.db.commit()

    async def _sync_schedule(self, client: HemisClient) -> None:
        from app.services.integrations import hemis_schedule

        first, last = hemis_schedule.schedule_window()
        label = ENTITY_LABELS["schedule"]

        async def on_page(page: int, page_count: int) -> None:
            await self._save_progress(f"{label}: yuklab olinmoqda", page, page_count)

        items = await hemis_schedule.fetch_lessons(client, first, last, on_page=on_page)
        if not self.employee_numbers:
            self.employee_numbers = employee_numbers(await fetch_employees(client))
        result = await hemis_schedule.sync_schedule(self.db, items, self.employee_numbers, first=first, last=last)
        for key in ("fetched", "created", "updated", "unchanged", "deactivated", "skipped", "errors"):
            self.stats["schedule"][key] = result[key]
        lessons = result["created"] + result["updated"] + result["unchanged"]
        self.message(
            f"Dars jadvali {first:%d.%m}-{last:%d.%m}: {lessons} dars, kamerasi topilgan — {result['with_camera']}, "
            f"o'qituvchisi topilgan — {result['with_teacher']}"
        )
        await self.db.commit()

    async def _sync_people(self, entity: str, person_type: str, people: list[HemisPerson]) -> None:
        stats = self.stats[entity]
        label = ENTITY_LABELS[entity]
        rows = (
            await self.db.execute(
                select(StudentStaff).options(
                    noload(StudentStaff.faculty),
                    defer(StudentStaff.biometric_embedding),
                )
            )
        ).scalars().all()
        by_hemis: dict[str, StudentStaff] = {r.hemis_id: r for r in rows if r.hemis_id}
        by_pinfl: dict[str, StudentStaff] = {r.pinfl: r for r in rows if r.pinfl}
        by_name: dict[str, list[StudentStaff]] = defaultdict(list)
        by_fuzzy: dict[str, list[StudentStaff]] = defaultdict(list)
        by_short: dict[str, list[StudentStaff]] = defaultdict(list)
        for row in rows:
            if row.type == person_type:
                by_name[name_key(row.full_name)].append(row)
                by_fuzzy[fuzzy_name_key(row.full_name)].append(row)
                by_short[short_name_key(row.full_name)].append(row)
        name_counts = Counter(name_key(p.full_name) for p in people)
        fuzzy_counts = Counter(fuzzy_name_key(p.full_name) for p in people)
        short_counts = Counter(short_name_key(p.full_name) for p in people)
        claimed: set[uuid.UUID] = set()
        seen_hemis: set[str] = set()
        now = _utcnow()

        for index, person in enumerate(people):
            if index % 200 == 0:
                await self._save_progress(f"{label}: yozilmoqda", index, len(people))
            seen_hemis.add(person.hemis_id)
            match, conflict = self._match(
                person, by_hemis, by_pinfl, by_name, name_counts, by_fuzzy, fuzzy_counts, by_short, short_counts
            )
            if conflict:
                stats["skipped"] += 1
                self.message(f"{person.full_name} ({person.hemis_id}): {conflict}")
                continue
            if match is not None and match.type != person_type:
                stats["skipped"] += 1
                self.message(
                    f"{person.full_name} ({person.hemis_id}): tizimda "
                    f"{'xodim' if match.type == 'xodim' else 'talaba'} sifatida bor — o'zgartirilmadi"
                )
                continue
            if match is not None and match.id in claimed:
                stats["skipped"] += 1
                self.message(f"{person.full_name} ({person.hemis_id}): bu yozuv boshqa HEMIS qatoriga biriktirildi")
                continue
            faculty = await self.ensure_faculty(person.faculty_name)
            if faculty is not None:
                self.touched_faculty_ids.add(faculty.id)
            try:
                if match is None:
                    if not person.active:
                        # Bitirgan / chetlashtirilgan va tizimda yo'q — yaratilmaydi.
                        stats["skipped"] += 1
                        continue
                    pinfl = person.pinfl if person.pinfl and person.pinfl not in by_pinfl else None
                    record = StudentStaff(
                        full_name=person.full_name,
                        type=person_type,
                        hemis_id=person.hemis_id,
                        pinfl=pinfl,
                        faculty_id=faculty.id if faculty else None,
                        group_or_position=person.group_or_position[:300],
                        biometrics_status="yoq",
                        active=True,
                        hemis_photo_url=person.photo_url,
                        org_unit_id=self.org_units.get(person.department_id or ""),
                        position=(person.position or None) if person_type == "xodim" else None,
                    )
                    async with self.db.begin_nested():
                        self.db.add(record)
                    stats["created"] += 1
                    by_hemis[person.hemis_id] = record
                    if pinfl:
                        by_pinfl[pinfl] = record
                    claimed.add(record.id)
                    continue

                claimed.add(match.id)
                outcome = await self._apply_update(match, person, faculty, by_pinfl, now)
                stats[outcome] += 1
                by_hemis[person.hemis_id] = match
            except Exception as exc:  # noqa: BLE001 — bitta qator butun ro'yxatni to'xtatmasin
                stats["errors"] += 1
                self.message(f"{person.full_name} ({person.hemis_id}): yozib bo'lmadi — {type(exc).__name__}")
                logger.warning("HEMIS person write failed", exc_info=True, extra={"hemis_id": person.hemis_id})
                if match is not None:
                    try:
                        await self.db.refresh(match)
                    except Exception:
                        logger.warning("refresh after failed HEMIS write failed", exc_info=True)

        stored = sum(1 for row in rows if row.type == person_type and row.hemis_id and row.active)
        if settings.hemis_deactivate_missing and seen_hemis and not _looks_complete(len(seen_hemis), stored):
            self.message(
                f"{label}: {len(seen_hemis)} ta keldi, bazada {stored} ta faol — chala javob bo'lishi mumkin, "
                "hech kim faolsizlantirilmadi"
            )
        elif settings.hemis_deactivate_missing and seen_hemis:
            for row in rows:
                if row.type == person_type and row.hemis_id and row.hemis_id not in seen_hemis and row.active:
                    row.active = False
                    row.deactivated_at = now
                    stats["deactivated"] += 1
                    self.roster_changed = True
        await self._save_progress(f"{label}: yozildi", len(people), len(people))

    @staticmethod
    def _match(
        person: HemisPerson,
        by_hemis: dict[str, StudentStaff],
        by_pinfl: dict[str, StudentStaff],
        by_name: dict[str, list[StudentStaff]],
        name_counts: Counter,
        by_fuzzy: dict[str, list[StudentStaff]] | None = None,
        fuzzy_counts: Counter | None = None,
        by_short: dict[str, list[StudentStaff]] | None = None,
        short_counts: Counter | None = None,
    ) -> tuple[StudentStaff | None, str | None]:
        """(yozuv, ziddiyat sababi).

        Ism bo'yicha moslik — faqat ikkala tomonda ham YAGONA bo'lsa. HEMIS
        REST javobida JSHSHIR yo'q (fjsti, 2026-09-25): ilgari bazadagi
        JSHSHIRli yozuv ism bo'yicha umuman tanlanmasdi va sinxronlash
        deyarli har bir talabani yangi (dublikat) qator qilib yaratgan
        bo'lardi. Endi JSHSHIR faqat IKKALA tomonda bo'lib, farq qilsagina
        to'siq. Aniq ism topilmasa — imlo farqlariga chidamli kalit
        (x/h, q/k, kirill/lotin, o'g'li/qizi), u ham faqat yagona bo'lsa.

        Uchinchi bosqich — familiya + ism (2026-09-25 quruq sinovi: 2276
        moslashmagan talabadan 1111 tasining bazada yagona "egizagi" bor edi,
        farq faqat otasining ismida — bittasida yo'q yoki qisqartirilgan).
        Qabul qilinadi: ikkala tomonda yagona (yoki bir nechta bo'lsa — guruh
        kodi bittasiga mos), otasining ismi zid emas va guruh kodi qarshi
        dalil bermaydi (otasining ismi bir tomonda yo'q bo'lsa, guruh ham
        farq qilsa — dalil yetarli emas)."""
        match = by_hemis.get(person.hemis_id)
        if match is not None:
            return match, None
        if person.pinfl:
            match = by_pinfl.get(person.pinfl)
            if match is not None:
                if match.hemis_id and match.hemis_id != person.hemis_id:
                    return None, f"JSHSHIR boshqa HEMIS yozuviga ({match.hemis_id}) biriktirilgan — o'tkazildi"
                return match, None
        def free(row: StudentStaff) -> bool:
            return row.hemis_id is None and (not person.pinfl or not row.pinfl or row.pinfl == person.pinfl)

        key = name_key(person.full_name)
        if key and name_counts.get(key) == 1:
            candidates = [row for row in by_name.get(key, []) if free(row)]
            if len(candidates) == 1:
                return candidates[0], None
        if by_fuzzy is not None and fuzzy_counts is not None:
            fuzzy = fuzzy_name_key(person.full_name)
            if fuzzy and fuzzy_counts.get(fuzzy) == 1:
                candidates = [row for row in by_fuzzy.get(fuzzy, []) if free(row)]
                if len(candidates) == 1:
                    return candidates[0], None
        if by_short is not None and short_counts is not None:
            short = short_name_key(person.full_name)
            if short and len(short.split()) == 2:
                candidates = [
                    row
                    for row in by_short.get(short, [])
                    if free(row) and patronymic_compatible(person.full_name, row.full_name)
                ]
                wanted = group_code(person.group_name)
                if len(candidates) > 1 or short_counts.get(short, 0) > 1:
                    same_group = [row for row in candidates if wanted and group_code(row.group_or_position) == wanted]
                    candidates = same_group if len(same_group) == 1 else []
                if len(candidates) == 1:
                    row = candidates[0]
                    theirs = group_code(row.group_or_position)
                    one_lacks = len(fuzzy_name_key(person.full_name).split()) < 3 or len(fuzzy_name_key(row.full_name).split()) < 3
                    if not (one_lacks and wanted and theirs and wanted != theirs):
                        return row, None
        return None, None

    async def _apply_update(
        self,
        record: StudentStaff,
        person: HemisPerson,
        faculty: Faculty | None,
        by_pinfl: dict[str, StudentStaff],
        now: datetime,
    ) -> str:
        """'updated' | 'unchanged' | 'deactivated'. Biometrikaga tegilmaydi."""
        changes: dict[str, Any] = {}
        if record.hemis_id != person.hemis_id:
            changes["hemis_id"] = person.hemis_id
        if record.full_name != person.full_name:
            changes["full_name"] = person.full_name
        if person.pinfl and not record.pinfl and person.pinfl not in by_pinfl:
            changes["pinfl"] = person.pinfl
        if faculty is not None and record.faculty_id != faculty.id:
            changes["faculty_id"] = faculty.id
        position = person.group_or_position[:300]
        if record.group_or_position != position:
            changes["group_or_position"] = position
        if person.type == "xodim":
            unit_id = self.org_units.get(person.department_id or "")
            if unit_id is not None and record.org_unit_id != unit_id:
                changes["org_unit_id"] = unit_id
            if person.position and record.position != person.position[:300]:
                changes["position"] = person.position[:300]
        if person.photo_url and record.hemis_photo_url != person.photo_url:
            # Yangi rasm — rasmdan tanitish qayta urinib ko'radi (app/jobs/hemis_photos.py).
            changes["hemis_photo_url"] = person.photo_url
            changes["hemis_photo_checked_at"] = None
            changes["hemis_photo_error"] = None
        outcome = "updated"
        if person.active and not record.active and not record.manually_deactivated:
            # Administrator qo'lda faolsizlantirgan odam HEMIS'da "faol" bo'lsa
            # ham qayta faollashtirilmaydi — qaror adminniki.
            changes["active"] = True
            changes["deactivated_at"] = None
        elif not person.active and record.active:
            changes["active"] = False
            changes["deactivated_at"] = now
            outcome = "deactivated"
        if not changes:
            return "unchanged"
        async with self.db.begin_nested():
            for attr, value in changes.items():
                setattr(record, attr, value)
        if "pinfl" in changes:
            by_pinfl[person.pinfl] = record
        if "active" in changes:
            self.roster_changed = True
        return outcome

    async def _update_faculty_counts(self) -> None:
        """Fakultetdagi talabalar va kurslar soni — HEMIS'dagi haqiqiy ro'yxatdan."""
        if not self.touched_faculty_ids or not self.students_loaded:
            return
        await self.db.flush()
        for faculty_id in self.touched_faculty_ids:
            faculty = await self.db.get(Faculty, faculty_id)
            if faculty is None:
                continue
            students = await self.db.scalar(
                select(func.count())
                .select_from(StudentStaff)
                .where(StudentStaff.type == "talaba")
                .where(StudentStaff.active.is_(True))
                .where(StudentStaff.faculty_id == faculty_id)
            )
            max_course = await self.db.scalar(
                select(func.max(StudentGroup.course)).where(StudentGroup.faculty_id == faculty_id)
            )
            faculty.student_count = students or 0
            if max_course:
                faculty.course_count = max_course


def _copy_stats(stats: dict) -> dict:
    """JSONB ustuni o'zgargani sezilishi uchun har safar yangi obyekt."""
    return {
        key: (dict(value) if isinstance(value, dict) else list(value) if isinstance(value, list) else value)
        for key, value in stats.items()
    }


# ── Ulanishni tekshirish ────────────────────────────────────────────────────


async def test_connection() -> dict:
    """Har bir ro'yxatdan bittadan yozuv so'raladi — token va manzil
    to'g'riligini hamda umumiy sonlarni ko'rsatadi. Bazaga yozilmaydi."""
    result: dict[str, Any] = {"ok": True, "entities": {}}
    try:
        client = HemisClient()
    except HemisNotConfiguredError as exc:
        return {"ok": False, "error": str(exc), "entities": {}}
    async with client:
        for entity, endpoint in ENTITY_ENDPOINTS.items():
            try:
                page = await client.fetch_page(endpoint, 1, limit=1)
                result["entities"][entity] = {"ok": True, "total": page.total_count, "error": None}
            except HemisAuthError as exc:
                result["ok"] = False
                result["error"] = str(exc)
                result["entities"][entity] = {"ok": False, "total": None, "error": str(exc)}
                break
            except HemisError as exc:
                result["ok"] = False
                result["entities"][entity] = {"ok": False, "total": None, "error": str(exc)}
    return result
