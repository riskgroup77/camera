"""HEMIS'ga bog'lanmagan talabalarni HEMIS yozuvlari bilan moslashtirish.

Muammo (production, 2026-10-06): 894 faol talabaning hemis_id'si yo'q —
ulardan 573 tasi QR sahifada o'zini ro'yxatdan o'tkazgan va guruhini qo'lda
yozgan ("20.26 gurux", "1kurs 3426 guruh"). Nazoratda ular 372 ta bir
kishilik "guruh" bo'lib ko'rinadi. HEMIS sinxroni (integrations/hemis.py)
ularni topmaydi: HEMIS talabasi avval hemis_id bo'yicha qidiriladi, yozuv
esa ilgari yaratilgan — o'zini ro'yxatdan o'tkazgan qator boshqa, yuzi
o'shanda, guruhi va dars jadvali HEMIS qatorida.

Bu modul har bir bog'lanmagan talaba uchun HEMIS qatoridan juftini
qidiradi va TAKLIF beradi; birlashtirish — person_dedupe.merge_people
(davomat, dars davomati, yuz, tashriflar ko'chadi; HEMIS qatori qoladi).

Ism qoidasi — name_matching.same_person_name (admin "Yangi biriktirish"
bilan bir xil). Qo'shimcha dalillar:
  * JSHSHIR ikkalasida bo'lib, 2 dan ko'p raqamda farq qilsa — boshqa odam;
  * yuz ikkalasida bo'lsa — o'xshashlik past bo'lsa boshqa odam, yuqori
    bo'lsa bir nechta nomzoddan bittasini tanlashga dalil;
  * guruh kodi (qo'lda yozilgan "3426" va HEMIS "DI-3426") — bir nechta
    nomzoddan bittasini tanlashga dalil.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

from app.services.integrations.hemis import group_code
from app.services.name_matching import name_key, name_tokens, same_person_name
from app.services.person_dedupe import FACE_DIFFERENT, pinfl_close

MERGE = "birlashtiriladi"
REVIEW = "tekshirish"
NOT_FOUND = "topilmadi"

VERDICT_LABELS = {
    MERGE: "Birlashtiriladi",
    REVIEW: "Tekshirish kerak",
    NOT_FOUND: "HEMIS'da topilmadi",
}

# ArcFace (buffalo_l) kosinus o'xshashligi. Bir odamning ro'yxatdan o'tish
# rasmi va HEMIS surati odatda 0.45 dan yuqori; boshqa-boshqa odamlar
# FACE_DIFFERENT (person_dedupe) dan past. Oraliq — dalil emas.
FACE_SAME = 0.45


@dataclass
class Proposal:
    person: dict
    verdict: str
    reason: str
    hemis: dict | None = None
    face_similarity: float | None = None
    alternatives: list[dict] = field(default_factory=list)


def _vector(raw) -> np.ndarray | None:
    if not raw:
        return None
    try:
        vector = np.asarray(json.loads(raw) if isinstance(raw, str) else raw, dtype=np.float32)
    except (ValueError, TypeError):
        return None
    norm = float(np.linalg.norm(vector))
    return vector / norm if vector.ndim == 1 and vector.size >= 64 and norm > 0 else None


def face_similarity(a: dict, b: dict) -> float | None:
    va, vb = _vector(a.get("biometric_embedding")), _vector(b.get("biometric_embedding"))
    if va is None or vb is None or va.shape != vb.shape:
        return None
    return round(float(va @ vb), 3)


def _pinfl_conflict(a: dict, b: dict) -> bool:
    pa, pb = a.get("pinfl"), b.get("pinfl")
    return bool(pa and pb and pa != pb and not pinfl_close(pa, pb))


def _same_group(person: dict, hemis: dict) -> bool:
    wanted = group_code(person.get("group_or_position"))
    return bool(wanted) and wanted == group_code(hemis.get("group_or_position"))


class _HemisIndex:
    """HEMIS qatorlari ism so'zlari bo'yicha: same_person_name ismni AYNAN
    talab qiladi (familiya bilan o'rni almashgan bo'lishi mumkin), shuning
    uchun nomzodlar — shu ikki so'zdan biri mos kelganlar."""

    def __init__(self, rows: list[dict]):
        self.by_token: dict[str, list[dict]] = defaultdict(list)
        self.by_key: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            self.by_key[name_key(row.get("full_name"))].append(row)
            for token in set(name_tokens(row.get("full_name"))[:2]):
                self.by_token[token].append(row)

    def candidates(self, person: dict) -> list[dict]:
        name = person.get("full_name")
        seen: dict = {}
        for row in self.by_key.get(name_key(name), []):
            seen[row["id"]] = row
        for token in set(name_tokens(name)[:2]):
            for row in self.by_token.get(token, []):
                if row["id"] not in seen and same_person_name(name, row.get("full_name")):
                    seen[row["id"]] = row
        return [row for row in seen.values() if row.get("type") == person.get("type")]


def _decide(person: dict, found: list[dict]) -> Proposal:
    if not found:
        return Proposal(person, NOT_FOUND, "HEMIS'da shu ismli talaba yo'q")

    rejected: list[str] = []
    viable: list[tuple[dict, float | None]] = []
    for row in found:
        if _pinfl_conflict(person, row):
            rejected.append("JSHSHIR boshqa")
            continue
        similarity = face_similarity(person, row)
        if similarity is not None and similarity < FACE_DIFFERENT:
            rejected.append(f"yuzi boshqa ({similarity:.2f})")
            continue
        viable.append((row, similarity))

    if not viable:
        return Proposal(
            person, REVIEW, "Ismi mos HEMIS talabasi bor, lekin " + ", ".join(sorted(set(rejected))),
            alternatives=found,
        )

    chosen, why = None, ""
    if len(viable) == 1:
        chosen, why = viable[0], "ismi mos yagona HEMIS talabasi"
    else:
        by_face = [item for item in viable if item[1] is not None and item[1] >= FACE_SAME]
        by_group = [item for item in viable if _same_group(person, item[0])]
        if len(by_face) == 1:
            chosen, why = by_face[0], f"{len(viable)} ta adashdan yuzi mos kelgani"
        elif len(by_group) == 1:
            chosen, why = by_group[0], f"{len(viable)} ta adashdan guruh kodi mos kelgani"

    if chosen is None:
        return Proposal(
            person, REVIEW, f"Ismi mos {len(viable)} ta HEMIS talabasi — qaysi biri ekanini aniqlab bo'lmadi",
            alternatives=[row for row, _ in viable],
        )

    row, similarity = chosen
    notes = [why]
    if similarity is not None and similarity >= FACE_SAME:
        notes.append(f"yuzi mos ({similarity:.2f})")
    elif similarity is not None:
        notes.append(f"yuz o'xshashligi noaniq ({similarity:.2f})")
    if _same_group(person, row):
        notes.append("guruh kodi mos")
    if person.get("pinfl") and person.get("pinfl") == row.get("pinfl"):
        notes.append("JSHSHIR mos")
    others = [r for r, _ in viable if r is not row]

    # Faqat dalil yetarli bo'lsa avtomatik: yuz o'rtacha (na mos, na boshqa)
    # yoki HEMIS qatori faol emas — odam ko'rib chiqadi.
    if similarity is not None and similarity < FACE_SAME:
        return Proposal(person, REVIEW, "; ".join(notes), row, similarity, others)
    if not row.get("active", True):
        notes.append("HEMIS yozuvi faol emas (bitirgan/chetlashtirilgan)")
        return Proposal(person, REVIEW, "; ".join(notes), row, similarity, others)
    return Proposal(person, MERGE, "; ".join(notes), row, similarity, others)


def reconcile(unlinked: list[dict], hemis_rows: list[dict]) -> list[Proposal]:
    """Toza funksiya — sinovlanadi.

    `unlinked` — hemis_id'siz faol talabalar, `hemis_rows` — hemis_id'li
    talabalar (faol bo'lmaganlari ham: bitirgan odam qayta ro'yxatdan
    o'tgan bo'lishi mumkin). Bitta HEMIS qatoriga ikki kishi tushsa —
    ikkalasi ham tekshirishga (bittasi boshqa odam yoki ular o'zaro dublikat)."""
    index = _HemisIndex(hemis_rows)
    proposals = [_decide(person, index.candidates(person)) for person in unlinked]

    claims: dict = defaultdict(list)
    for proposal in proposals:
        if proposal.verdict == MERGE and proposal.hemis is not None:
            claims[proposal.hemis["id"]].append(proposal)
    for same in claims.values():
        if len(same) > 1:
            for proposal in same:
                proposal.verdict = REVIEW
                proposal.reason += f"; shu HEMIS yozuviga yana {len(same) - 1} kishi to'g'ri keldi"

    order = {MERGE: 0, REVIEW: 1, NOT_FOUND: 2}
    proposals.sort(key=lambda p: (order[p.verdict], p.person.get("full_name") or ""))
    return proposals
