"""Institut tuzilmasi: bo'linma turlari, lavozim toifalari va xodimlarni
bo'linmaga bog'lash.

MANBA. HEMIS department-list (2026-09-26: 85 bo'linma) — structureType
kodi: 16 rektorat, 11 fakultet, 12 kafedra (parent — fakultet), 13 bo'lim,
14 boshqarma, 15 markaz, 10 boshqa (talabalar turar joylari, vivariy...).
HEMIS "fakultet" deb bergan Magistratura / Ordinatura / Malaka oshirish —
fakultet emas, o'quv bo'linmasi ("oquv"): institutda 4 ta fakultet, ularning
29 ta kafedrasi bor (fermi.uz bilan bir xil).

Xodim HEMIS employee-list dagi department.id orqali bog'lanadi. HEMIS'da
yo'q xodim (avval qo'lda kiritilgan) — bo'lim nomi (group_or_position)
bo'yicha: "Pediatriya kafedrasi" -> "Pediatriya" (qo'shimchalar, apostrof
va bo'sh joylar hisobga olinmaydi).

Lavozim toifasi (filtr uchun): professor-o'qituvchilar, ma'muriy xodimlar,
texnik xodimlar (farrosh, qorovul, ...).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OrgUnit, StudentStaff

KIND_BY_CODE = {
    "16": "rektorat",
    "11": "fakultet",
    "12": "kafedra",
    "13": "bolim",
    "14": "boshqarma",
    "15": "markaz",
    "10": "boshqa",
}
KIND_LABELS = {
    "rektorat": "Rahbariyat",
    "fakultet": "Fakultetlar",
    "kafedra": "Kafedralar",
    "oquv": "O‘quv bo‘linmalari",
    "boshqarma": "Boshqarma",
    "bolim": "Bo‘limlar",
    "markaz": "Markazlar",
    "turar_joy": "Talabalar turar joylari",
    "boshqa": "Boshqa bo‘linmalar",
}
# Ro'yxatdagi tartib (kafedralar o'z fakulteti ostida chiqadi).
KIND_ORDER = ("rektorat", "fakultet", "oquv", "boshqarma", "bolim", "markaz", "turar_joy", "boshqa")

_OQUV_WORDS = ("magistratura", "ordinatura", "malaka oshirish")


def org_kind(code: str | None, name: str) -> str:
    lowered = name.lower()
    kind = KIND_BY_CODE.get((code or "").strip(), "boshqa")
    if kind == "fakultet" and any(word in lowered for word in _OQUV_WORDS):
        return "oquv"
    if kind == "boshqa" and "turar joy" in lowered:
        return "turar_joy"
    return kind


# ── Lavozim toifasi ─────────────────────────────────────────────────────────

POSITION_GROUPS = {
    "oqituvchi": "Professor-o‘qituvchilar",
    "mamuriy": "Ma’muriy xodimlar",
    "texnik": "Texnik xodimlar",
}

_TEACHER = ("assistent", "o'qituvchi", "dotsent", "professor", "kafedra mudiri", "tyutor", "stajer")
_TECHNICAL = (
    "farrosh", "qorovul", "supuruvchi", "chilangar", "santexnik", "duradgor", "elektr", "komendant",
    "xo'jalik bekasi", "texnik", "haydovchi", "oshpaz", "bog'bon", "kir yuvuvchi", "garderob", "liftchi",
    "payvandchi", "bo'yoqchi", "ishchi", "dvornik", "operator qozon", "qozonxona", "slesar", "tikuvchi",
)
_APOS = str.maketrans({c: "'" for c in "‘’ʻʼ`´"})


def _norm(text: str | None) -> str:
    return " ".join((text or "").translate(_APOS).lower().split())


# O'zi ro'yxatdan o'tgan xodimlar lavozimni qo'lda, xato va kirillda yozgan
# ("Assisent", "Фаррош", "Коровл", "stajyor o'qituvchi"). HEMIS nomiga keltiriladi.
_CYR = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j", "з": "z", "и": "i",
    "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "", "ы": "i", "ь": "",
    "э": "e", "ю": "yu", "я": "ya", "қ": "q", "ғ": "g'", "ў": "o'", "ҳ": "h",
})
_CANONICAL: tuple[tuple[re.Pattern, str], ...] = tuple(
    (re.compile(pattern), name)
    for pattern, name in (
        (r"kabi ?net mudir", "Kabinet mudiri"),
        (r"kafedra mudir", "Kafedra mudiri"),
        (r"katta o'?q?i?t?u?v?chi|katta oqtuvchi", "Katta o‘qituvchi"),
        (r"staj", "Stajer-o‘qituvchi"),
        (r"^a+s+i*s*[ie]*s*[ie]*n*t|as+is+e?t|as+it+ent|assistant|kafedra as+is", "Assistent"),
        (r"dotsent|dosent", "Dotsent"),
        (r"professor", "Professor"),
        (r"tyutor|tyuter", "Tyutor"),
        (r"^o'?q[io]?t?u?v?chi$", "O‘qituvchi"),
        (r"lab[ao]rant", "Laborant"),
        (r"farrosh|farosh", "Farrosh"),
        (r"qorovul|korovl|korovul", "Qorovul"),
        (r"supuruvchi", "Ko‘cha supuruvchi"),
        (r"duradgor|durodgor", "Duradgor"),
        (r"elektr|elektra", "Elektromontyor"),
        (r"xisobchi|hisobchi", "Hisobchi"),
        (r"kutubxonachi", "Kutubxonachi"),
        (r"ish yurituvchi", "Ish yurituvchi"),
        (r"menejer|menedjer", "Menejer"),
    )
)


def canonical_position(text: str | None) -> str | None:
    """Qo'lda yozilgan lavozim -> HEMIS nomi (topilmasa — matnning o'zi)."""
    raw = " ".join((text or "").split())
    if not raw:
        return None
    norm = _norm(raw.lower().translate(_CYR))
    for pattern, name in _CANONICAL:
        if pattern.search(norm):
            return name
    return raw[:120]


def position_group(position: str | None) -> str | None:
    """Lavozim -> 'oqituvchi' | 'texnik' | 'mamuriy' (None — lavozim noma'lum)."""
    text = _norm((canonical_position(position) or "").lower().translate(_CYR))
    if not text:
        return None
    if any(word in text for word in _TECHNICAL) and "o'qituvchi" not in text:
        return "texnik"
    if any(word in text for word in _TEACHER):
        return "oqituvchi"
    return "mamuriy"


# ── Nom bo'yicha bog'lash (HEMIS'da yo'q xodimlar) ──────────────────────────

_SUFFIXES = (" kafedrasi", " kafedra", " fakulteti", " bo'limi", " markazi")


def unit_key(name: str | None) -> str:
    text = _norm(name)
    text = re.sub(r"[\"().,]", " ", text)
    text = " ".join(text.split())
    for suffix in _SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    return text.replace("x", "h").strip()


def match_unit(text: str | None, units: dict[str, uuid.UUID]) -> uuid.UUID | None:
    """`units` — unit_key -> id. Aniq kalit, bo'lmasa bitta bo'linma
    kalitini to'liq o'z ichiga olgan matn (eng uzun mos keladigani)."""
    key = unit_key(text)
    if not key:
        return None
    if key in units:
        return units[key]
    candidates = [(len(k), uid) for k, uid in units.items() if len(k) >= 6 and (k in key or key in k)]
    if not candidates:
        return None
    candidates.sort(reverse=True)
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        return None
    return candidates[0][1]


async def link_unassigned_staff(db: AsyncSession) -> int:
    """Bo'linmasi yo'q faol xodimlarni group_or_position matni bo'yicha
    bog'laydi. Qaytaradi: nechta bog'landi. Commit chaqiruvchida."""
    units = (await db.execute(select(OrgUnit.id, OrgUnit.name).where(OrgUnit.active.is_(True)))).all()
    keys: dict[str, uuid.UUID] = {}
    for uid, name in units:
        keys.setdefault(unit_key(name), uid)
    rows = (
        await db.execute(
            select(StudentStaff).where(
                StudentStaff.type == "xodim", StudentStaff.active.is_(True), StudentStaff.org_unit_id.is_(None)
            )
        )
    ).scalars().all()
    linked = 0
    for person in rows:
        unit_id = match_unit(person.group_or_position, keys)
        if unit_id is not None:
            person.org_unit_id = unit_id
            linked += 1
        elif not person.position:
            # Bo'lim emas — lavozim yozilgan ("Farrosh", "Assisent"): filtrlar uchun lavozim.
            person.position = canonical_position(person.group_or_position)
    return linked


# ── Daraxt ──────────────────────────────────────────────────────────────────


@dataclass
class TreeUnit:
    id: uuid.UUID
    name: str
    kind: str
    parent_id: uuid.UUID | None
    children: list[TreeUnit] = field(default_factory=list)


def build_tree(units: list[OrgUnit]) -> list[TreeUnit]:
    """Ildizlar tartib bilan: rektorat, fakultetlar (ichida kafedralar), ..."""
    nodes = {u.id: TreeUnit(u.id, u.name.strip(), u.kind, u.parent_id) for u in units}
    roots: list[TreeUnit] = []
    for node in nodes.values():
        parent = nodes.get(node.parent_id) if node.parent_id else None
        if parent is not None and parent.id != node.id:
            parent.children.append(node)
        else:
            roots.append(node)
    order = {kind: i for i, kind in enumerate(KIND_ORDER)}

    def sort(items: list[TreeUnit]) -> None:
        items.sort(key=lambda n: (order.get(n.kind, 99), n.name.lower()))
        for item in items:
            sort(item.children)

    sort(roots)
    return roots


def descendants(roots: list[TreeUnit], unit_id: uuid.UUID) -> set[uuid.UUID]:
    """Bo'linma va uning barcha ichki bo'linmalari."""
    found: set[uuid.UUID] = set()

    def walk(items: list[TreeUnit], inside: bool) -> None:
        for item in items:
            here = inside or item.id == unit_id
            if here:
                found.add(item.id)
            walk(item.children, here)

    walk(roots, False)
    return found
