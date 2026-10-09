"""Talaba/xodim dublikatlarini topish va birlashtirish.

Productionda (2026-09-24) 7253 faol yozuvdan 81 tasi dublikat edi: xodimlar
ikki marta import qilingan (kadrlar ro'yxati — bo'lim va JSHSHIR bilan,
keyin lavozimlar ro'yxati — yuz bilan), talabalar esa HEMIS importidan
tashqari QR orqali o'zini yana ro'yxatdan o'tkazgan. Natija: bitta odamning
yuzi bir yozuvda, davomati boshqasida — kamera uni taniydi, lekin hisobotda
"kelmadi".

BIR ODAM deb hisoblanadi: tur, familiya, ism va otasining ismi mos
(katta-kichik harf, apostrof shakli, "o'g'li/qizi", "-ovich/-ovna" va
harflar tartibi farqi hisobga olinmaydi; otasining ismi bittasida bo'lmasa
ham mos). JSHSHIR ikkalasida bo'lib, 2 dan ko'p raqamda farq qilsa — bu
boshqa odam (adash), birlashtirilmaydi.

BIRLASHTIRISH o'chirishdan oldin hamma narsani saqlanadigan yozuvga ko'chiradi:
bo'sh maydonlar (JSHSHIR, HEMIS, karta, ota-ona aloqasi, rozilik), yuz
(saqlanadiganda bo'lmasa), to'liqroq ism, davomat (bir kunda ikkalasida
bo'lsa — ertaroq kelgani), dars davomati, tashriflar, galereya, dars
jadvali, turniket o'tishlari va tekshiruv yozuvlari.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field

import numpy as np

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.name_matching import same_person_name

_APOS = str.maketrans({c: "'" for c in "‘’ʻʼ`´"})
_SUFFIX = {"o'g'li", "og'li", "o'gli", "ogli", "ugli", "o'g'il", "qizi", "kizi", "qiz"}
_PATRONYMIC_END = re.compile(r"(ovich|evich|ovna|evna|yevich|yevna)$")

COPY_FIELDS = (
    "pinfl", "passport_series", "passport_number", "hemis_id", "card_number", "faculty_id",
    "parent_phone", "parent_telegram_chat_id", "telegram_link_code",
    "consent_given_at", "consent_version", "consent_source",
)
# ArcFace kosinus o'xshashligi: bundan past — boshqa-boshqa odamlar (bir
# odamning ikki surati odatda 0.45 dan yuqori).
FACE_DIFFERENT = 0.25

# Pasport (seriya + raqam) — birgalikda noyob indeks (ix_students_staff_passport).
UNIQUE_FIELDS = frozenset({"pinfl", "hemis_id", "card_number", "telegram_link_code", "passport_series", "passport_number"})
BIOMETRIC_FIELDS = (
    "biometric_embedding", "biometric_photo_key", "biometric_photo_left_key", "biometric_photo_right_key",
    "biometrics_status", "biometrics_confirmed_at",
)

# (jadval, ustun) — shaxsga ishora qiluvchi, oddiy ko'chiriladigan havolalar.
SIMPLE_REFS = (
    ("presence_visits", "student_staff_id"),
    ("face_gallery_embeddings", "student_staff_id"),
    ("lesson_sessions", "teacher_id"),
    ("unknown_sightings", "person_id"),
    ("access_events", "student_staff_id"),
)


def name_tokens(name: str | None) -> list[str]:
    s = (name or "").translate(_APOS).lower().replace("x", "h")
    s = re.sub(r"[^a-z' ]", " ", s)
    words = [w.strip("'") for w in s.split()]
    words = [w for w in words if w and w not in _SUFFIX]
    return [_PATRONYMIC_END.sub("", w) for w in words]


def pinfl_close(a: str, b: str) -> bool:
    """Bir-ikki raqamdagi xato (qo'lda terilgan JSHSHIR) — o'sha odam."""
    return len(a) == len(b) and sum(x != y for x, y in zip(a, b)) <= 2


def keeper_score(row: dict) -> float:
    """Qaysi yozuv qoladi: rasmiy import (JSHSHIR bor, o'zi ro'yxatdan
    o'tmagan) > tasdiqlangan yuz > ko'proq davomat."""
    return (
        (4 if row.get("pinfl") and not row.get("self_registered") else 0)
        + (2 if row.get("biometrics_status") == "tasdiqlangan" else 0)
        + (1 if not row.get("self_registered") else 0)
        + min(int(row.get("att") or 0), 50) / 100
    )


@dataclass
class DuplicateGroup:
    keeper: dict
    duplicates: list[dict] = field(default_factory=list)
    # "ism" — faqat ism bo'yicha; "ism_yuz" — yuz ham mos (ism shakli boshqa
    # bo'lsa ham: familiya/ism tartibi, otasining ismi); "yuz" — yuzi bir xil,
    # ismi boshqa: birlashtirilmaydi, operator ko'rib chiqadi (ko'pincha
    # rasmlardan biri noto'g'ri odamga biriktirilgan).
    reason: str = "ism"
    face_similarity: float | None = None

    @property
    def mergeable(self) -> bool:
        return self.reason != "yuz"


def _unit_vector(raw) -> np.ndarray | None:
    if not raw:
        return None
    try:
        vector = np.asarray(json.loads(raw) if isinstance(raw, str) else raw, dtype=np.float32)
    except (ValueError, TypeError):
        return None
    norm = float(np.linalg.norm(vector))
    return vector / norm if vector.ndim == 1 and norm > 0 else None


def face_pairs(rows: list[dict], threshold: float) -> list[tuple[int, int, float]]:
    """(i, j, o'xshashlik) — tasdiqlangan yuzlari `threshold` dan o'xshash
    bir turdagi yozuvlar juftligi (rows indekslari)."""
    index, vectors = [], []
    for i, row in enumerate(rows):
        if row.get("biometrics_status") != "tasdiqlangan":
            continue
        vector = _unit_vector(row.get("biometric_embedding"))
        if vector is not None and vector.size >= 64 and (not vectors or vector.shape == vectors[0].shape):
            index.append(i)
            vectors.append(vector)
    if len(vectors) < 2:
        return []
    matrix = np.stack(vectors)
    pairs: list[tuple[int, int, float]] = []
    # Bo'laklab — 10 000 kishida to'liq matritsa 400 MB bo'lardi.
    for start in range(0, len(vectors), 1024):
        block = matrix[start:start + 1024] @ matrix.T
        for a, b in zip(*np.nonzero(block >= threshold)):
            i, j = start + int(a), int(b)
            if i < j and rows[index[i]].get("type") == rows[index[j]].get("type"):
                pairs.append((index[i], index[j], float(block[a, b])))
    return pairs


def names_compatible(a: str | None, b: str | None) -> bool:
    """Yuz mos bo'lganda ism uchun yumshoqroq shart: familiya va ism bir xil
    (tartibi farq qilsa ham) yoki familiya bir xil va ism boshi (4 harf) mos."""
    ta, tb = name_tokens(a), name_tokens(b)
    if len(ta) < 2 or len(tb) < 2:
        return False
    if sorted(ta[:2]) == sorted(tb[:2]):
        return True
    return ta[0] == tb[0] and ta[1][:4] == tb[1][:4]


def _pinfl_conflict(people: list[dict]) -> bool:
    pinfls = [row["pinfl"] for row in people if row.get("pinfl")]
    return len(set(pinfls)) > 1 and not all(pinfl_close(pinfls[0], p) for p in pinfls[1:])


def group_duplicates(rows: list[dict], *, use_faces: bool = True) -> list[DuplicateGroup]:
    """Toza funksiya — sinovlanadi. `rows` — faol shaxslar (dict)."""
    groups = _name_groups(rows)
    if use_faces and settings.dedupe_face_similarity > 0:
        groups = _add_face_groups(rows, groups)
    groups.sort(key=lambda g: (g.reason == "yuz", g.keeper.get("type") or "", g.keeper.get("full_name") or ""))
    return groups


def _add_face_groups(rows: list[dict], groups: list[DuplicateGroup]) -> list[DuplicateGroup]:
    """Ism bo'yicha topilmagan, lekin yuzi bir xil yozuvlar (production,
    2026-09-25: 4055 yuzdan 22 juft >= 0.55, 17 tasida familiya-ism mos —
    HEMIS importi ism shaklini boshqacha yozgan)."""
    threshold = min(settings.dedupe_face_similarity, settings.dedupe_face_only_similarity)
    pairs = face_pairs(rows, threshold)
    if not pairs:
        return groups
    # Birlashtirish — union-find, ism guruhlari bilan birga.
    parent = list(range(len(rows)))
    position = {id(row): i for i, row in enumerate(rows)}

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    name_sets: set[frozenset[int]] = set()
    for group in groups:
        members = [position[id(p)] for p in (group.keeper, *group.duplicates)]
        name_sets.add(frozenset(members))
        for other in members[1:]:
            parent[find(other)] = find(members[0])
    best: dict[int, float] = {}
    review: list[DuplicateGroup] = []
    for i, j, similarity in pairs:
        a, b = rows[i], rows[j]
        if find(i) == find(j):
            root = find(i)
            best[root] = max(best.get(root, 0.0), similarity)
            continue
        if similarity >= settings.dedupe_face_similarity and names_compatible(a.get("full_name"), b.get("full_name")):
            if _pinfl_conflict([a, b]):
                continue
            ri, rj = find(i), find(j)
            parent[rj] = ri
            best[ri] = max(best.get(ri, 0.0), best.get(rj, 0.0), similarity)
        elif similarity >= settings.dedupe_face_only_similarity:
            people = sorted((a, b), key=keeper_score, reverse=True)
            review.append(DuplicateGroup(keeper=people[0], duplicates=people[1:], reason="yuz", face_similarity=round(similarity, 3)))
    clusters: dict[int, list[int]] = {}
    for i in range(len(rows)):
        clusters.setdefault(find(i), []).append(i)
    result: list[DuplicateGroup] = []
    for root, members in clusters.items():
        if len(members) < 2:
            continue
        by_face = frozenset(members) not in name_sets
        people = sorted((rows[i] for i in members), key=keeper_score, reverse=True)
        result.append(
            DuplicateGroup(
                keeper=people[0],
                duplicates=people[1:],
                reason="ism_yuz" if by_face else "ism",
                face_similarity=round(best[root], 3) if root in best else None,
            )
        )
    return result + review


def _name_groups(rows: list[dict]) -> list[DuplicateGroup]:
    buckets: dict[tuple, list[tuple[dict, list[str]]]] = {}
    for row in rows:
        tokens = name_tokens(row.get("full_name"))
        if len(tokens) >= 2:
            buckets.setdefault((row.get("type"), tokens[0], tokens[1]), []).append((row, tokens))
    groups: list[DuplicateGroup] = []
    for items in buckets.values():
        if len(items) < 2:
            continue
        patronymics = {tokens[2][:4] for _, tokens in items if len(tokens) >= 3}
        if len(patronymics) > 1:
            continue  # otasining ismi boshqa — adash
        pinfls = [row["pinfl"] for row, _ in items if row.get("pinfl")]
        if len(set(pinfls)) > 1 and not all(pinfl_close(pinfls[0], p) for p in pinfls[1:]):
            continue  # JSHSHIR butunlay boshqa — adash
        people = sorted((row for row, _ in items), key=keeper_score, reverse=True)
        groups.append(DuplicateGroup(keeper=people[0], duplicates=people[1:]))
    return groups


_ROWS_SQL = """
    select s.*,
           (select count(*) from attendance_records a where a.student_staff_id = s.id) as att
    from students_staff s where s.active
"""


async def find_duplicates(db: AsyncSession) -> list[DuplicateGroup]:
    rows = [dict(r._mapping) for r in (await db.execute(text(_ROWS_SQL))).all()]
    return group_duplicates(rows)


async def _person(db: AsyncSession, person_id: uuid.UUID) -> dict | None:
    row = (
        await db.execute(text(_ROWS_SQL.replace("where s.active", "where s.id = :id")), {"id": person_id})
    ).first()
    return dict(row._mapping) if row else None


class MergeError(Exception):
    pass


def faces_differ(a: dict, b: dict) -> bool:
    """Ikkalasida yuz bor va ular boshqa-boshqa odamniki (FACE_DIFFERENT dan past)."""
    va, vb = _unit_vector(a.get("biometric_embedding")), _unit_vector(b.get("biometric_embedding"))
    return va is not None and vb is not None and va.shape == vb.shape and float(va @ vb) < FACE_DIFFERENT


def _all_angles(row: dict) -> bool:
    return bool(row.get("biometric_photo_key") and row.get("biometric_photo_left_key") and row.get("biometric_photo_right_key"))


async def merge_people(
    db: AsyncSession, keeper_id: uuid.UUID, duplicate_id: uuid.UUID, *, manual: bool = False
) -> dict:
    """Bitta dublikatni saqlanadigan yozuvga qo'shib o'chiradi. Commit
    chaqiruvchida (bir guruh — bir tranzaksiya). Nima ko'chirilganini qaytaradi.

    `manual=True` — administrator ikki yozuvni O'ZI tanlagan (merge_manual):
    ism qoidasi tekshirilmaydi (familiya o'zgargan, harf xatosi), lekin
    JSHSHIR va yuz himoyasi qoladi."""
    if keeper_id == duplicate_id:
        raise MergeError("Bir xil yozuv")
    keeper = await _person(db, keeper_id)
    dup = await _person(db, duplicate_id)
    if keeper is None or dup is None:
        raise MergeError("Yozuv topilmadi")
    if keeper["type"] != dup["type"] and not manual:
        raise MergeError("Talaba va xodimni birlashtirib bo'lmaydi")
    # Himoya: so'rov qo'lda tuzilgan bo'lsa ham, adashlarni birlashtirmaydi.
    # Ism qoidasi — name_matching (kirill/lotin, q/k, so'z tartibi; HEMIS
    # moslashtirishi — app/services/hemis_reconcile.py — ham shunga tayanadi).
    same_name = (
        same_person_name(keeper["full_name"], dup["full_name"])
        and not _pinfl_conflict([keeper, dup])
        and not faces_differ(keeper, dup)
    )
    if manual:
        _check_manual_pair(keeper, dup)
    elif not same_name and not any(group.mergeable for group in group_duplicates([keeper, dup])):
        raise MergeError(f"{keeper['full_name']} va {dup['full_name']} — boshqa-boshqa odamlar")

    moved: dict[str, int] = {}
    updates = {f: dup[f] for f in COPY_FIELDS if keeper.get(f) is None and dup.get(f) is not None}
    # HEMIS ismi rasmiy — sinxron baribir qaytarib yozadi.
    if not keeper.get("hemis_id") and len(name_tokens(dup["full_name"])) > len(name_tokens(keeper["full_name"])):
        updates["full_name"] = dup["full_name"]
    # Yuz: saqlanadiganda yo'q bo'lsa — dublikatniki; ikkalasida bo'lsa,
    # uch burchakdan olingani (ro'yxatdan o'tish) bitta suratdan olinganidan
    # (HEMIS rasmi) ishonchliroq tanitadi.
    if dup.get("biometric_embedding") and (not keeper.get("biometric_embedding") or (_all_angles(dup) and not _all_angles(keeper))):
        for f in BIOMETRIC_FIELDS:
            updates[f] = dup.get(f)
        moved["yuz"] = 1
    unique_moves = [f for f in updates if f in UNIQUE_FIELDS]
    if {"passport_series", "passport_number"} & set(unique_moves):
        unique_moves = sorted(set(unique_moves) | {"passport_series", "passport_number"})
    if unique_moves:
        await db.execute(
            text("update students_staff set " + ", ".join(f"{f} = null" for f in unique_moves) + " where id = :d"),
            {"d": duplicate_id},
        )
    if updates:
        await db.execute(
            text("update students_staff set " + ", ".join(f"{f} = :{f}" for f in updates) + " where id = :k"),
            {**updates, "k": keeper_id},
        )

    # Davomat: kuniga bitta yozuv — ikkalasida bo'lsa, ertaroq kelgani qoladi.
    clashes = (
        await db.execute(
            text(
                """select d.id as did, k.id as kid, d.check_in as dci, k.check_in as kci
                   from attendance_records d
                   join attendance_records k on k.date = d.date and k.student_staff_id = :k
                   where d.student_staff_id = :d"""
            ),
            {"d": duplicate_id, "k": keeper_id},
        )
    ).all()
    for clash in clashes:
        drop = clash.kid if clash.dci is not None and (clash.kci is None or clash.dci < clash.kci) else clash.did
        await db.execute(text("delete from attendance_records where id = :i"), {"i": drop})
    res = await db.execute(
        text("update attendance_records set student_staff_id = :k where student_staff_id = :d"),
        {"d": duplicate_id, "k": keeper_id},
    )
    moved["davomat"] = res.rowcount or 0

    # Unikal juftliklar: dars davomati (dars+shaxs), tekshiruv (shaxs+kun+kamera).
    await db.execute(
        text(
            """delete from lesson_attendance d using lesson_attendance k
               where d.student_staff_id = :d and k.student_staff_id = :k
                 and k.lesson_session_id = d.lesson_session_id"""
        ),
        {"d": duplicate_id, "k": keeper_id},
    )
    res = await db.execute(
        text("update lesson_attendance set student_staff_id = :k where student_staff_id = :d"),
        {"d": duplicate_id, "k": keeper_id},
    )
    moved["dars davomati"] = res.rowcount or 0
    await db.execute(
        text(
            """delete from face_review_items d using face_review_items k
               where d.person_id = :d and k.person_id = :k and k.day = d.day
                 and k.camera_id is not distinct from d.camera_id"""
        ),
        {"d": duplicate_id, "k": keeper_id},
    )
    await db.execute(
        text("update face_review_items set person_id = :k where person_id = :d"), {"d": duplicate_id, "k": keeper_id}
    )
    for table, column in SIMPLE_REFS:
        res = await db.execute(
            text(f"update {table} set {column} = :k where {column} = :d"), {"d": duplicate_id, "k": keeper_id}
        )
        moved[table] = res.rowcount or 0

    await db.execute(text("delete from students_staff where id = :d"), {"d": duplicate_id})
    return {key: value for key, value in moved.items() if value}


# ── Qo'lda birlashtirish (administrator ikki yozuvni o'zi tanlaydi) ─────────
# Avtomatik qidiruv topa olmaydigan juftlar uchun (2026-10-09): familiya
# o'zgargan (Mamajonova -> Kenjayeva), harf xatosi (Dodobayev/Dododbayev),
# kirill/lotin (Мухсинова/Muxsinova). Bir yozuvda yuz va JSHSHIR, ikkinchisida
# dars jadvali va davomat — natija bitta to'liq yozuv, odam yuzini qayta
# topshirmaydi.

# Rasmiy profil (ism, guruh, fakultet, bo'linma) — shu maydonlar profil
# manbasidan olinadi; HEMIS ID va boshqalar COPY_FIELDS orqali ko'chadi.
PROFILE_FIELDS = (
    "type", "full_name", "group_or_position", "faculty_id", "reported_group", "org_unit_id", "position", "hemis_photo_url",
)


def _check_manual_pair(a: dict, b: dict) -> None:
    if a["id"] == b["id"]:
        raise MergeError("Bir xil yozuv")
    if a["type"] != b["type"] and not _wrong_type_clone(a, b):
        raise MergeError("Talaba va xodimni birlashtirib bo'lmaydi")
    if a.get("pinfl") and b.get("pinfl") and not pinfl_close(a["pinfl"], b["pinfl"]):
        raise MergeError("Ikki yozuvda ikki xil JSHSHIR — bular boshqa-boshqa odamlar")
    if faces_differ(a, b):
        raise MergeError("Ikki yozuvdagi yuzlar boshqa-boshqa odamniki — birlashtirilmaydi")


def _wrong_type_clone(a: dict, b: dict) -> bool:
    """Havolada turini adashtirgan klon (talaba "xodim" deb o'tgan): biri
    HEMIS'dan, ikkinchisi o'zi ro'yxatdan o'tgan — tur HEMIS'dan olinadi."""
    official, clone = (a, b) if a.get("hemis_id") else (b, a)
    return bool(official.get("hemis_id")) and not clone.get("hemis_id") and bool(clone.get("self_registered"))


def _face_rank(row: dict) -> tuple:
    """Qaysi yozuv qoladi: tasdiqlangan yuz > kutilmoqda > yuz bor; keyin
    uch tomonlama; keyin rasmiylik (keeper_score)."""
    status = row.get("biometrics_status")
    return (
        2 if status == "tasdiqlangan" else (1 if status == "kutilmoqda" and row.get("biometric_embedding") else 0),
        1 if row.get("biometric_embedding") else 0,
        1 if _all_angles(row) else 0,
        keeper_score(row),
    )


def plan_manual_merge(a: dict, b: dict) -> dict:
    """Sof funksiya — nima qoladi va natija qanday bo'ladi (bazaga yozmaydi)."""
    _check_manual_pair(a, b)
    keeper, other = (a, b) if _face_rank(a) >= _face_rank(b) else (b, a)
    # Profil: HEMIS'dan kelgan (rasmiy) yozuvniki; bo'lmasa — faolniki.
    if other.get("hemis_id") and not keeper.get("hemis_id"):
        profile = other
    elif other.get("active") and not keeper.get("active"):
        profile = other
    else:
        profile = keeper
    face = keeper if keeper.get("biometric_embedding") or not other.get("biometric_embedding") else other
    status = face.get("biometrics_status") or "yoq"
    if status == "kutilmoqda" and face.get("biometric_embedding") and _all_angles(face):
        status = "tasdiqlangan"  # administrator qarori — uch tomonlama yuz tasdiqlanadi
    return {
        "keeper": keeper,
        "other": other,
        "profile": profile,
        "result": {
            "full_name": profile["full_name"],
            "group_or_position": profile.get("group_or_position") or "",
            "faculty_id": profile.get("faculty_id"),
            "active": bool(keeper.get("active") or other.get("active")),
            "biometrics_status": status,
            "all_angles": _all_angles(face),
            "has_pinfl": bool(keeper.get("pinfl") or other.get("pinfl")),
            "hemis_linked": bool(keeper.get("hemis_id") or other.get("hemis_id")),
            "attendance": int(keeper.get("att") or 0) + int(other.get("att") or 0),
        },
    }


async def merge_manual(db: AsyncSession, first_id: uuid.UUID, second_id: uuid.UUID, *, apply: bool) -> dict:
    """Ikki yozuvni bittaga. apply=False — faqat reja (oldindan ko'rish).
    Commit chaqiruvchida."""
    a, b = await _person(db, first_id), await _person(db, second_id)
    if a is None or b is None:
        raise MergeError("Yozuv topilmadi")
    plan = plan_manual_merge(a, b)
    if not apply:
        return plan
    keeper, other, profile = plan["keeper"], plan["other"], plan["profile"]
    moved = await merge_people(db, keeper["id"], other["id"], manual=True)
    updates: dict = {}
    if profile is other:
        updates.update({f: other.get(f) for f in PROFILE_FIELDS})
        updates["self_registered"] = bool(other.get("self_registered"))
    if plan["result"]["active"] and not keeper.get("active"):
        updates.update(active=True, deactivated_at=None, manually_deactivated=False)
    if plan["result"]["biometrics_status"] == "tasdiqlangan" and (
        await db.execute(text("select biometrics_status from students_staff where id = :k"), {"k": keeper["id"]})
    ).scalar() == "kutilmoqda":
        updates.update(biometrics_status="tasdiqlangan", biometrics_review_reason=None)
        await db.execute(
            text("update students_staff set biometrics_confirmed_at = now() where id = :k"), {"k": keeper["id"]}
        )
    if updates:
        await db.execute(
            text("update students_staff set " + ", ".join(f"{f} = :{f}" for f in updates) + " where id = :k"),
            {**updates, "k": keeper["id"]},
        )
    return {**plan, "moved": moved}


def merge_candidate_score(person: dict, other: dict) -> int:
    """Taklif tartibi uchun: ism-sharifning qancha qismi mos (0-3).
    Familiya o'zgargan bo'lsa ham ism + otasining ismi mos keladi."""
    from app.services import name_matching  # kirill/lotin bir xil tokenlarga

    ta, tb = name_matching.name_tokens(person.get("full_name")), name_matching.name_tokens(other.get("full_name"))
    if len(ta) < 2 or len(tb) < 2:
        return 0
    score = 0
    if ta[0][:5] == tb[0][:5]:
        score += 1
    if ta[1][:5] == tb[1][:5]:
        score += 1
    if len(ta) > 2 and len(tb) > 2 and ta[2][:4] == tb[2][:4]:
        score += 1
    return score


# ── Yuzli klon <-> HEMIS yozuvi juftlari (avtomatik) ────────────────────────
# 09.10 holati: yuzi tasdiqlangan, JSHSHIRli, HEMIS ID'siz klon (ko'pincha
# faol emas) va yuzsiz, lekin guruhi/davomati bor HEMIS yozuvi. Ism turlicha
# yozilgan: "Shalola"/"Shalolaxon", "Bobirjon"/"Boburjon", so'z tartibi
# ("Shukrona Isojonova"), kirill/lotin, familiya o'zgargan (Mamajonova ->
# Kenjayeva). Guruh raqami ("TBI 426" = "TPI-426", "3226" = "DI-3226") va
# YAGONALIK — adashni birlashtirmaslik uchun.

_GROUP_NUMBER = re.compile(r"(?<!\d)(\d{3,4})(?!\d)")
_GIVEN_SUFFIXES = ("hon", "jon", "bonu", "oy")


def _lev(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _stem_given(word: str) -> str:
    for suffix in _GIVEN_SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def _given_match(a: str, b: str) -> bool:
    sa, sb = _stem_given(a), _stem_given(b)
    if sa == sb or (len(sa) >= 4 and len(sb) >= 4 and (sa.startswith(sb) or sb.startswith(sa))):
        return True
    return min(len(sa), len(sb)) >= 4 and _lev(sa, sb) <= 1


def _surname_match(a: str, b: str) -> bool:
    sa, sb = a.rstrip("a"), b.rstrip("a")  # Ahmadaliyev / Ahmadaliyeva
    if sa == sb:
        return True
    return min(len(sa), len(sb)) >= 5 and (_lev(sa, sb) <= 1 or sa[:7] == sb[:7] and len(sa[:7]) == 7)


def _patronymic_match(a: str | None, b: str | None) -> bool | None:
    """None — bittasida yo'q (noma'lum)."""
    if not a or not b:
        return None
    return a[:4] == b[:4]


def group_numbers(row: dict) -> set[str]:
    text_ = " ".join(str(row.get(f) or "") for f in ("group_or_position", "reported_group"))
    return set(_GROUP_NUMBER.findall(text_))


def clone_name_match(clone: str, target: str, *, same_group: bool) -> bool:
    """Klon ismi (havolada qo'lda yozilgan) HEMIS ismiga mosmi."""
    from app.services import name_matching

    tt = name_matching.name_tokens(target)
    tc = name_matching.name_tokens(clone)
    if len(tt) < 2 or len(tc) < 2:
        return False
    t_sur, t_giv, t_pat = tt[0], tt[1], (tt[2] if len(tt) > 2 else None)
    # Klon so'z tartibi ikki xil bo'lishi mumkin: "Familiya Ism ..." yoki "Ism Familiya ...".
    for sur, giv, pat in ((tc[0], tc[1], tc[2] if len(tc) > 2 else None), (tc[1], tc[0], tc[2] if len(tc) > 2 else None)):
        if not _given_match(giv, t_giv):
            continue
        pm = _patronymic_match(pat, t_pat)
        if _surname_match(sur, t_sur) and pm is not False:
            return True
        # Familiya o'zgargan: ism + otasining ismi + guruh mos.
        if pm is True and same_group:
            return True
    return False


def _is_face(row: dict) -> bool:
    return bool(row.get("biometric_embedding")) and row.get("biometrics_status") in ("tasdiqlangan", "kutilmoqda")


def find_clone_pairs(rows: list[dict]) -> tuple[list[tuple[dict, list[dict]]], list[tuple[dict, list[dict]]]]:
    """(aniq guruhlar [(hemis, [klonlar])], noaniqlar [(klon, nomzodlar)]).

    Klon — HEMIS ID'siz, yuzi (tasdiqlangan/kutilmoqda) YOKI JSHSHIRi bor
    yozuv (faol bo'lmasa ham). Nishon — HEMIS ID'li, yuzsiz, faol. Tur bir xil
    (yoki o'zi ro'yxatdan o'tgan klon turini adashtirgan — guruh raqami mos).
    Guruh raqami ikkalasida bo'lsa — teng. JSHSHIR ikkalasida bo'lib, boshqa
    bo'lsa — rad. Klonga AYNAN bitta nishon mos kelsagina aniq; bir nishonga
    bir nechta klon (odam bir necha marta o'tgan) — hammasi bitta guruh."""
    clones = [r for r in rows if not r.get("hemis_id") and (_is_face(r) or r.get("pinfl"))]
    targets = [r for r in rows if r.get("hemis_id") and not r.get("biometric_embedding") and r.get("active")]
    hits_of: dict = {}
    for c in clones:
        cg = group_numbers(c)
        hits = []
        for t in targets:
            tg = group_numbers(t)
            if t["type"] != c["type"] and not (c.get("self_registered") and cg and cg & tg):
                continue
            if cg and tg and not (cg & tg):
                continue
            if c.get("pinfl") and t.get("pinfl") and not pinfl_close(c["pinfl"], t["pinfl"]):
                continue
            if clone_name_match(c["full_name"], t["full_name"], same_group=bool(cg & tg)):
                hits.append(t)
        if hits:
            hits_of[c["id"]] = (c, hits)
    groups: dict = {}
    unsure: list[tuple[dict, list[dict]]] = []
    for c, hits in hits_of.values():
        if len(hits) == 1:
            groups.setdefault(hits[0]["id"], (hits[0], []))[1].append(c)
        else:
            unsure.append((c, hits))
    # Faqat JSHSHIRli (yuzsiz) klonlar guruhi ham foydali: JSHSHIR HEMIS
    # yozuviga o'tadi — havola odamni topadi, tahrirlashda xato chiqmaydi.
    return list(groups.values()), unsure
