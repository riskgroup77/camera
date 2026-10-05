# -*- coding: utf-8 -*-
"""Institut talabalarini tizimga ommaviy kiritish.

MAQSAD. Kontingent ro'yxatidagi har bir talaba tizimda o'z qatoriga ega
bo'lishi va JSHSHIR raqami orqali ochiq sahifada
(https://cam.fermi.uz/royxatdan-otish) yuzini tasdiqlay olishi kerak.
Bu #1 "Begona shaxs" moduli uchun ham shart: bazada talabalar bo'lmasa,
kamerada ko'ringan har bir talaba "begona" deb hisoblanadi.

SHAXSIY MA'LUMOT GIT'GA TUSHMAYDI. Xodimlar skriptidan farqli o'laroq,
bu yerda ro'yxat skript ichiga yozilmagan: 6 mingga yaqin talabaning
JSHSHIR va pasport raqami ochiq repozitoriyga tushmasligi kerak.
Ma'lumot alohida JSON faylda turadi (.gitignore'da) va serverga
qo'lda o'tkaziladi. Import tugagach faylni o'chiring.

IKKI BOSQICH:

  1. export — kompyuterda, Excel fayllar turgan joyda. Kontingent
     fayllari ichiga har bir talabaning rasmi joylangan va ular jami
     ~800 MB; JSON esa ~1 MB:

         python scripts/import_talabalar.py export "C:/.../talablar kotingenti" talabalar.json

  2. import — serverda, konteyner ichida:

         docker compose cp talabalar.json api:/tmp/talabalar.json
         docker compose exec -T api python scripts/import_talabalar.py import /tmp/talabalar.json --dry-run
         docker compose exec -T api python scripts/import_talabalar.py import /tmp/talabalar.json

SHIFRLANGAN TO'PLAM (serverga fayl o'tkazmasdan). JSON'ni serverga
qo'lda o'tkazish qiyin bo'lsa, u shifrlangan .py faylga joylanadi va
git orqali boradi:

         python scripts/import_talabalar.py pack talabalar.json scripts/talabalar_malumot.py

  Repozitoriyda faqat AES-256-GCM bilan shifrlangan matn turadi; kalit
  (parol so'z) repoga yozilmaydi va ishga tushirishda so'raladi. Serverda:

         docker compose exec api python scripts/talabalar_malumot.py --dry-run
         docker compose exec api python scripts/talabalar_malumot.py
         docker compose exec api python scripts/talabalar_malumot.py --kurs 2

KURS. Fayllar o'tgan (2025-2026) o'quv yili bo'yicha tuzilgan: "1-kurs"
faylidagilar hozir 2-kursda, "5 kurslar" faylidagilar esa 6-kursda.
Kurs fayl nomidagi raqamga COURSE_SHIFT qo'shib aniqlanadi. Guruh
kodidagi yil bunga ishonchli tayanch emas: MD guruhlari (MD-1123,
MD-478) boshqacha raqamlanadi.

FAKULTET. Faqat 4-kurs faylida fakultet ustuni bor. Boshqa fayllar
uchun fakultet guruh prefiksidan olinadi va bu jadval o'sha 4-kurs
faylidagi haqiqiy bog'lanishlardan tuzilgan (GROUP_PREFIX_FACULTY).
Prefiksi noma'lum guruhlar (klinik ordinatura va magistratura
mutaxassisliklari, FT, OHI, BM) hamda guruhi ko'rsatilmagan 3-kurs
talabalari FAKULTETSIZ kiritiladi — taxmin qilib noto'g'ri fakultetga
yozishdan ko'ra, bo'sh qoldirib hisobotda ko'rsatish to'g'ri. Jadvalga
prefiks qo'shib skriptni qayta ishga tushirsangiz, ular joyiga tushadi.

XAVFSIZLIK. Skript IDEMPOTENT:

  * JSHSHIR bo'yicha mavjud TALABA topilsa — ism, fakultet, guruh
    yangilanadi. Biometrik holat, yuz vektori va rasm HECH QACHON
    o'zgartirilmaydi.
  * Shu JSHSHIR bilan XODIM bo'lsa — unga tegilmaydi (masalan, bir
    vaqtda xodim bo'lgan ordinator), hisobotda ko'rsatiladi.
  * Pasport boshqa yozuvda allaqachon bo'lsa — saqlanmaydi: ro'yxatdan
    o'tish sahifasi pasport bo'yicha qidirganda ikkita natija topib,
    xato berardi.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import getpass
import json
import lzma
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import SessionLocal
from app.models import Faculty, StudentGroup, StudentStaff
from scripts.import_xodimlar import _ensure_faculties, _fac_key

PERSON_TYPE = "talaba"

# Fayl o'tgan o'quv yili uchun tuzilgan — hozir hamma bir kurs yuqorida.
COURSE_SHIFT = 1

FACULTY_DAVOLASH = "Davolash ishi fakulteti"
FACULTY_PROFILAKTIKA = "Tibbiy profilaktika va jamoat salomatligi fakulteti"
FACULTY_PEDIATRIYA = "Pediatriya fakulteti"
FACULTY_XALQARO = "Xalqaro fakultet"

# 4-kurs faylidagi "Fakultet" ustunidan olingan (DI, TPI, XT, F, P, PI, S).
# ЛД — "лечебное дело", ya'ni rus guruhidagi davolash ishi. MD — ingliz
# tilidagi xalqaro guruhlar (talabalarning deyarli hammasi chet elliklar).
GROUP_PREFIX_FACULTY = {
    "DI": FACULTY_DAVOLASH,
    "ЛД": FACULTY_DAVOLASH,
    "TPI": FACULTY_PROFILAKTIKA,
    "XT": FACULTY_PROFILAKTIKA,
    "F": FACULTY_PEDIATRIYA,
    "P": FACULTY_PEDIATRIYA,
    "PI": FACULTY_PEDIATRIYA,
    "S": FACULTY_PEDIATRIYA,
    "MD": FACULTY_XALQARO,
}

_APOSTROPHES = "‘’`ʻʼ´"
_PLACEHOLDERS = {"XXX"}
# Otasining ismidan keyingi qo'shimchalar — kichik harf bilan yoziladi.
_PARTICLES = {"qizi", "o'g'li", "kizi", "ogli", "o'gli", "ugli", "uli", "ulı", "ulí", "qızı", "qízí"}

# Sarlavha (apostrof va bo'shliqlarsiz, kichik harfda) -> maydon
_HEADERS = {
    "toliq ismi": "name",
    "pasport raqami": "passport",
    "jshshir-kod": "pinfl",
    "fakultet": "faculty",
    "guruh": "group",
}


# ── tozalash ──────────────────────────────────────────────────────────────


def format_name(raw: str | None) -> str:
    """"TO‘XTAYEVA MALIKA SHERZOD QIZI" -> "To'xtayeva Malika Sherzod qizi".

    Manbada ismlar bosh harflarda; chet elliklarda yetishmayotgan familiya
    yoki otasining ismi o'rniga "XXX" yozilgan — u ismning qismi emas."""
    text = raw or ""
    for ch in _APOSTROPHES:
        text = text.replace(ch, "'")
    words: list[str] = []
    for token in text.split():
        if token.upper() in _PLACEHOLDERS:
            continue
        low = token.lower()
        if low in _PARTICLES:
            words.append(low)
            continue
        words.append("-".join(part[:1].upper() + part[1:] for part in low.split("-")))
    return " ".join(words)


def clean_pinfl(raw) -> str:
    """Excel ba'zan raqamni son sifatida saqlaydi (60000000000011) — satrga
    aylantirib, raqamdan boshqa hamma narsani olib tashlaymiz."""
    if raw is None:
        return ""
    if isinstance(raw, float) and raw.is_integer():
        raw = int(raw)
    return "".join(ch for ch in str(raw) if ch.isdigit())


def parse_passport(raw) -> tuple[str | None, str | None]:
    """"AA1000006" -> ("AA", "1000006"). Ro'yxatdan o'tish sahifasi 2-4 harfli
    seriya va 5-10 raqamli nomer qabul qiladi — boshqa shakldagi (masalan,
    bir harfli xorijiy) pasport saqlanmaydi, bunday talaba JSHSHIR bilan
    kiradi."""
    text = re.sub(r"[\s\-]", "", str(raw or "")).upper()
    match = re.fullmatch(r"([A-Z]{2,4})(\d{5,10})", text)
    return (match.group(1), match.group(2)) if match else (None, None)


def clean_group(raw) -> str:
    """"ЛД - 25101" -> "ЛД-25101", "P-2621 A " -> "P-2621 A"."""
    text = re.sub(r"\s*-\s*", "-", str(raw or "").strip())
    return re.sub(r"\s+", " ", text)


def faculty_for(group: str, explicit: str | None = None) -> str | None:
    if explicit and explicit.strip():
        return explicit.strip()
    match = re.match(r"^([A-ZА-ЯЁ]+)(?=[-\s\d]|$)", group or "")
    return GROUP_PREFIX_FACULTY.get(match.group(1)) if match else None


def course_from_filename(filename: str) -> int:
    """"1-kurs.xlsx" -> 1, "3- kurs.xlsx" -> 3, "4 kurslar.xlsx" -> 4."""
    match = re.search(r"\d+", Path(filename).name)
    if not match:
        raise ValueError(f"Fayl nomidan kurs aniqlanmadi: {filename}")
    return int(match.group())


# ── 1-bosqich: Excel -> JSON ──────────────────────────────────────────────


def _header_key(value) -> str:
    text = str(value or "").strip().lower()
    for ch in _APOSTROPHES + "'":
        text = text.replace(ch, "")
    return text


def export_excel(excel_dir: str | Path, out_path: str | Path) -> dict:
    import openpyxl

    rows: list[dict] = []
    per_file: dict[str, int] = {}
    for path in sorted(Path(excel_dir).glob("*.xlsx")):
        if path.name.startswith("~$"):
            continue  # Excel ochiq turganda qoldiradigan vaqtinchalik fayl
        file_course = course_from_filename(path.name)
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        count = 0
        for sheet in workbook.worksheets:
            it = sheet.iter_rows(values_only=True)
            header = next(it, None)
            if not header:
                continue
            columns = {_HEADERS[_header_key(h)]: i for i, h in enumerate(header) if _header_key(h) in _HEADERS}
            if "name" not in columns or "pinfl" not in columns:
                continue
            for row_number, values in enumerate(it, start=2):
                def cell(field):
                    i = columns.get(field)
                    return values[i] if i is not None and i < len(values) else None

                if not str(cell("name") or "").strip():
                    continue  # masalan, 3-kurs "xalqaro" varag'i: faqat guruh nomlari, ism yo'q
                rows.append(
                    {
                        "pinfl": clean_pinfl(cell("pinfl")),
                        "name": str(cell("name")).strip(),
                        "passport": str(cell("passport") or "").strip(),
                        "group": str(cell("group") or "").strip(),
                        "faculty": str(cell("faculty") or "").strip(),
                        "file_course": file_course,
                        "source": f"{path.name} / {sheet.title} / {row_number}-qator",
                    }
                )
                count += 1
        workbook.close()
        per_file[path.name] = count

    payload = {"generated_at": datetime.now().isoformat(timespec="seconds"), "files": per_file, "rows": rows}
    Path(out_path).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    for name, count in per_file.items():
        print(f"  {name:<20} {count:>5} ta talaba")
    print(f"  {'JAMI':<20} {len(rows):>5} ta -> {out_path}")
    return payload


# ── 2-bosqich: JSON -> baza ───────────────────────────────────────────────


@dataclass
class StudentRecord:
    pinfl: str
    full_name: str
    passport_series: str | None
    passport_number: str | None
    group: str
    course: int
    faculty: str | None
    source: str

    @property
    def group_or_position(self) -> str:
        return f"{self.course}-kurs, {self.group}" if self.group else f"{self.course}-kurs"


def build_records(rows: list[dict]) -> tuple[list[StudentRecord], list[str]]:
    records: list[StudentRecord] = []
    problems: list[str] = []
    seen: dict[str, str] = {}
    for row in rows:
        source = row.get("source", "?")
        pinfl = clean_pinfl(row.get("pinfl"))
        name = format_name(row.get("name"))
        if len(pinfl) != 14:
            problems.append(f"{source}: JSHSHIR 14 xonali emas ({pinfl or 'bo`sh'}) — o'tkazib yuborildi")
            continue
        if not name:
            problems.append(f"{source}: ism bo'sh — o'tkazib yuborildi")
            continue
        if pinfl in seen:
            problems.append(f"{source}: JSHSHIR takrorlangan ({seen[pinfl]} bilan) — ikkinchisi o'tkazib yuborildi")
            continue
        seen[pinfl] = source
        group = clean_group(row.get("group"))
        series, number = parse_passport(row.get("passport"))
        records.append(
            StudentRecord(
                pinfl=pinfl,
                full_name=name,
                passport_series=series,
                passport_number=number,
                group=group,
                course=int(row["file_course"]) + COURSE_SHIFT,
                faculty=faculty_for(group, row.get("faculty")),
                source=source,
            )
        )
    return records, problems


async def run(
    rows: list[dict],
    dry_run: bool = False,
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> int:
    records, problems = build_records(rows)
    stats: Counter = Counter()
    staff_conflicts: list[StudentRecord] = []

    async with session_factory() as db:
        faculties = await _ensure_faculties(db, {r.faculty for r in records if r.faculty}, dry_run)

        existing = (await db.execute(select(StudentStaff).where(StudentStaff.pinfl.is_not(None)))).scalars().all()
        by_pinfl = {r.pinfl: r for r in existing}
        passport_rows = await db.execute(
            select(StudentStaff.passport_series, StudentStaff.passport_number, StudentStaff.pinfl).where(
                StudentStaff.passport_number.is_not(None)
            )
        )
        passport_owner = {(s, n): p for s, n, p in passport_rows.all()}

        for record in records:
            faculty = faculties.get(_fac_key(record.faculty)) if record.faculty else None
            current = by_pinfl.get(record.pinfl)

            if current is not None and current.type != PERSON_TYPE:
                staff_conflicts.append(record)
                continue

            passport = (record.passport_series, record.passport_number)
            if record.passport_number:
                owner = passport_owner.get(passport)
                if owner is not None and owner != record.pinfl:
                    stats["pasport_band"] += 1
                    passport = (None, None)
                else:
                    passport_owner[passport] = record.pinfl

            if current is None:
                stats["yangi"] += 1
                if not dry_run:
                    db.add(
                        StudentStaff(
                            full_name=record.full_name,
                            type=PERSON_TYPE,
                            pinfl=record.pinfl,
                            passport_series=passport[0],
                            passport_number=passport[1],
                            faculty_id=faculty.id if faculty else None,
                            group_or_position=record.group_or_position,
                            biometrics_status="yoq",
                        )
                    )
                continue

            # Mavjud talaba. Biometrikaga TEGILMAYDI.
            changed = False
            if current.full_name != record.full_name:
                current.full_name = record.full_name
                changed = True
            if faculty is not None and current.faculty_id != faculty.id:
                current.faculty_id = faculty.id
                changed = True
            if current.group_or_position != record.group_or_position:
                current.group_or_position = record.group_or_position
                changed = True
            if passport[1] and not current.passport_number:
                current.passport_series, current.passport_number = passport
                changed = True
            stats["yangilandi" if changed else "ozgarmadi"] += 1

        groups_written = 0
        if not dry_run:
            await db.flush()
            groups_written = await _sync_groups(db, records, faculties)
            await _sync_faculty_counts(db, {f.id for f in faculties.values()})
            await db.commit()

        pinfls = [r.pinfl for r in records]
        in_db = 0
        for start in range(0, len(pinfls), 1000):
            in_db += await db.scalar(
                select(func.count())
                .select_from(StudentStaff)
                .where(StudentStaff.type == PERSON_TYPE)
                .where(StudentStaff.pinfl.in_(pinfls[start : start + 1000]))
            )

    _report(records, problems, stats, staff_conflicts, groups_written, in_db, dry_run)

    if dry_run:
        return 0
    expected = len(records) - len(staff_conflicts)
    if in_db != expected:
        print(f"\nDIQQAT: bazada {in_db} ta, kutilgan {expected} ta. Yuqoridagi xabarlarni ko'rib chiqing.")
        return 1
    print("\nHammasi joyida: ro'yxatdagi har bir talaba bazada.")
    print("Import tugadi — talabalar.json faylini serverdan va konteynerdan o'chiring.")
    return 0


async def _sync_groups(db: AsyncSession, records: list[StudentRecord], faculties: dict[str, Faculty]) -> int:
    """Fakulteti aniq guruhlarni student_groups jadvaliga yozadi (bu jadvalda
    fakultet majburiy). Guruh nomi bo'yicha: bor bo'lsa yangilanadi."""
    members: dict[str, list[StudentRecord]] = defaultdict(list)
    for record in records:
        if record.group and record.faculty:
            members[record.group].append(record)

    existing = {g.name: g for g in (await db.execute(select(StudentGroup))).scalars().all()}
    for name, group_records in members.items():
        faculty = faculties.get(_fac_key(Counter(r.faculty for r in group_records).most_common(1)[0][0]))
        if faculty is None:
            continue
        course = Counter(r.course for r in group_records).most_common(1)[0][0]
        group = existing.get(name)
        if group is None:
            db.add(StudentGroup(name=name, faculty_id=faculty.id, course=course, student_count=len(group_records)))
        else:
            group.faculty_id = faculty.id
            group.course = course
            group.student_count = len(group_records)
    return len(members)


async def _sync_faculty_counts(db: AsyncSession, faculty_ids: set) -> None:
    """Fakultet jadvalidagi talabalar va kurslar soni — dastlabki namunaviy
    raqamlar o'rniga haqiqiy ro'yxatdan."""
    await db.flush()
    for faculty_id in faculty_ids:
        faculty = await db.get(Faculty, faculty_id)
        if faculty is None:
            continue
        students = await db.scalar(
            select(func.count())
            .select_from(StudentStaff)
            .where(StudentStaff.type == PERSON_TYPE)
            .where(StudentStaff.faculty_id == faculty_id)
        )
        if not students:
            continue
        max_course = await db.scalar(select(func.max(StudentGroup.course)).where(StudentGroup.faculty_id == faculty_id))
        faculty.student_count = students
        if max_course:
            faculty.course_count = max_course


def _report(records, problems, stats, staff_conflicts, groups_written, in_db, dry_run) -> None:
    line = "=" * 64
    print()
    print(line)
    print(f"  Fayldagi talabalar      : {len(records)}")
    print(f"  Yangi qo'shildi         : {stats['yangi']}")
    print(f"  Yangilandi              : {stats['yangilandi']}")
    print(f"  O'zgarishsiz            : {stats['ozgarmadi']}")
    print(f"  Xodim bilan bir JSHSHIR : {len(staff_conflicts)} (tegilmadi)")
    print(f"  Pasporti saqlanmadi     : {stats['pasport_band']} (boshqa yozuvda bor)")
    if not dry_run:
        print(f"  Guruhlar yozildi        : {groups_written}")
        print(f"  Bazada (tekshiruv)      : {in_db}")
    print(line)

    print("\n  Kurslar bo'yicha (yangi o'quv yili):")
    for course, count in sorted(Counter(r.course for r in records).items()):
        print(f"    {course}-kurs: {count}")

    print("\n  Fakultetlar bo'yicha:")
    for name, count in Counter(r.faculty or "— Fakultetsiz" for r in records).most_common():
        print(f"    {name:<55} {count:>5}")

    no_faculty = [r for r in records if not r.faculty]
    if no_faculty:
        no_group = sum(1 for r in no_faculty if not r.group)
        print(f"\n  Fakultetsiz {len(no_faculty)} ta talaba:")
        print(f"    guruhi ko'rsatilmagan (3-kurs fayli)       : {no_group}")
        prefixes = Counter(re.split(r"[-\s]", r.group)[0] for r in no_faculty if r.group)
        print(f"    guruh prefiksi jadvalda yo'q               : {sum(prefixes.values())}")
        print("    eng ko'p uchraganlari: " + ", ".join(f"{p} ({n})" for p, n in prefixes.most_common(12)))

    if staff_conflicts:
        print("\n  Xodim sifatida mavjud (talaba qilib o'zgartirilmadi):")
        for record in staff_conflicts[:20]:
            print(f"    {record.full_name} — {record.group_or_position}")
        if len(staff_conflicts) > 20:
            print(f"    ... va yana {len(staff_conflicts) - 20} ta")

    if problems:
        print(f"\n  Muammoli qatorlar ({len(problems)}):")
        for problem in problems[:30]:
            print(f"    {problem}")

    if dry_run:
        print("\n[dry-run] Bazaga hech narsa yozilmadi.")


# ── shifrlangan to'plam ───────────────────────────────────────────────────
#
# Repozitoriy ochiq, shuning uchun talabalar ro'yxati unga faqat shifrlangan
# holda tushadi. AES-256-GCM: shifrlaydi va butunligini tekshiradi — kalit
# noto'g'ri yoki matn buzilgan bo'lsa ochilmaydi, "yarim to'g'ri" ma'lumot
# bazaga yozilib ketmaydi. Kalit parol so'zdan scrypt bilan hosil qilinadi:
# u ataylab sekin, ya'ni parolni tanlab topish qimmat.

BUNDLE_FORMAT = 1
KEY_ENV = "TALABALAR_KALIT"
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**15, 8, 1
_SALT_LEN, _NONCE_LEN = 16, 12


class WrongPassphraseError(Exception):
    pass


def _normalize_passphrase(passphrase: str) -> str:
    """Kalit serverda qo'lda teriladi: bo'shliq, chiziqcha va harf kattaligi
    xatoga sabab bo'lmasin."""
    return re.sub(r"[\s\-]", "", passphrase or "").upper()


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    normalized = _normalize_passphrase(passphrase)
    if not normalized:
        raise WrongPassphraseError("Kalit kiritilmadi")
    return Scrypt(salt=salt, length=32, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P).derive(normalized.encode("utf-8"))


def seal(payload: dict, passphrase: str) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt, nonce = os.urandom(_SALT_LEN), os.urandom(_NONCE_LEN)
    header = bytes([BUNDLE_FORMAT])
    plain = lzma.compress(json.dumps(payload, ensure_ascii=False).encode("utf-8"), preset=9)
    cipher = AESGCM(_derive_key(passphrase, salt)).encrypt(nonce, plain, header)
    return base64.b64encode(header + salt + nonce + cipher).decode("ascii")


def unseal(blob: str, passphrase: str) -> dict:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    raw = base64.b64decode("".join(blob.split()))
    header = raw[:1]
    if not header or header[0] != BUNDLE_FORMAT:
        raise ValueError("Noma'lum to'plam formati")
    salt = raw[1 : 1 + _SALT_LEN]
    nonce = raw[1 + _SALT_LEN : 1 + _SALT_LEN + _NONCE_LEN]
    cipher = raw[1 + _SALT_LEN + _NONCE_LEN :]
    try:
        plain = AESGCM(_derive_key(passphrase, salt)).decrypt(nonce, cipher, header)
    except InvalidTag:
        raise WrongPassphraseError("Kalit noto'g'ri") from None
    return json.loads(lzma.decompress(plain).decode("utf-8"))


def pack(json_path: str | Path, out_py: str | Path, passphrase: str) -> dict[int, int]:
    """talabalar.json -> shifrlangan, git'ga qo'yish mumkin bo'lgan .py fayl.
    Faylda ochiq holda faqat kurslar bo'yicha sonlar turadi."""
    payload = json.loads(Path(json_path).read_text(encoding="utf-8"))
    rows = payload["rows"]
    per_course = dict(sorted(Counter(int(r["file_course"]) + COURSE_SHIFT for r in rows).items()))
    blob = seal({"generated_at": payload.get("generated_at"), "rows": rows}, passphrase)
    body = "\n".join(f'    "{blob[i:i + 100]}"' for i in range(0, len(blob), 100))
    courses_text = "\n".join(f"    {course}-kurs: {count} ta" for course, count in per_course.items())

    source = (
        "# -*- coding: utf-8 -*-\n"
        f'"""Talabalar kontingenti — {len(rows)} ta talaba, SHIFRLANGAN.\n'
        "\n"
        "Kurslar (yangi o'quv yili):\n"
        f"{courses_text}\n"
        "\n"
        "Ma'lumot AES-256-GCM bilan shifrlangan: repozitoriy ochiq, JSHSHIR va\n"
        "pasport raqamlari unda ochiq holda turmasligi kerak. Kalit bu faylda ham,\n"
        "repozitoriyda ham YO'Q — ishga tushirilganda so'raladi.\n"
        "\n"
        "ISHGA TUSHIRISH (server, /opt/camera/camera-api):\n"
        "\n"
        "    docker compose cp scripts/import_talabalar.py api:/app/scripts/import_talabalar.py\n"
        "    docker compose cp scripts/talabalar_malumot.py api:/app/scripts/talabalar_malumot.py\n"
        "    docker compose exec api python scripts/talabalar_malumot.py --dry-run   # sinov, bazaga yozmaydi\n"
        "    docker compose exec api python scripts/talabalar_malumot.py             # haqiqiy import\n"
        "    docker compose exec api python scripts/talabalar_malumot.py --kurs 2    # faqat bitta kurs\n"
        "\n"
        "Qayta ishga tushirish xavfsiz: takror yaratmaydi, tasdiqlangan yuzga tegmaydi\n"
        "(qarang scripts/import_talabalar.py).\n"
        f'"""\n'
        "\n"
        "import os\n"
        "import sys\n"
        "\n"
        "sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\n"
        "\n"
        "from scripts.import_talabalar import run_bundle_cli  # noqa: E402\n"
        "\n"
        f'YARATILGAN = "{payload.get("generated_at") or ""}"\n'
        f"KURSLAR = {per_course!r}\n"
        "MALUMOT = (\n"
        f"{body}\n"
        ")\n"
        "\n"
        'if __name__ == "__main__":\n'
        '    sys.stdout.reconfigure(encoding="utf-8", errors="replace")\n'
        "    sys.exit(run_bundle_cli(MALUMOT, KURSLAR))\n"
    )
    Path(out_py).write_text(source, encoding="utf-8")
    return per_course


def run_bundle_cli(blob: str, courses: dict[int, int]) -> int:
    return asyncio.run(run_bundle(blob, courses))


async def run_bundle(
    blob: str,
    courses: dict[int, int],
    argv: list[str] | None = None,
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> int:
    parser = argparse.ArgumentParser(description="Shifrlangan talabalar ro'yxatini bazaga kiritish")
    parser.add_argument("--dry-run", action="store_true", help="faqat tekshirish, bazaga yozmaydi")
    parser.add_argument("--kurs", type=int, action="append", choices=sorted(courses),
                        help="faqat shu kurs(lar)ni kiritish; bir necha marta berish mumkin")
    args = parser.parse_args(argv)

    print("Talabalar ro'yxati: " + ", ".join(f"{c}-kurs {n} ta" for c, n in sorted(courses.items())))
    passphrase = os.environ.get(KEY_ENV) or getpass.getpass("Kalitni kiriting (yozganda ko'rinmaydi): ")
    try:
        payload = unseal(blob, passphrase)
    except WrongPassphraseError as exc:
        print(f"\n{exc}. Bazaga hech narsa yozilmadi. Kalitni tekshirib, qayta urinib ko'ring.")
        return 2

    rows = payload["rows"]
    if args.kurs:
        wanted = set(args.kurs)
        rows = [r for r in rows if int(r["file_course"]) + COURSE_SHIFT in wanted]
        print("Tanlangan: " + ", ".join(f"{c}-kurs" for c in sorted(wanted)) + f" — {len(rows)} ta talaba")
    return await run(rows, dry_run=args.dry_run, session_factory=session_factory)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Talabalarni Excel kontingentidan tizimga kiritish")
    sub = parser.add_subparsers(dest="command", required=True)
    exp = sub.add_parser("export", help="Excel fayllardan JSON tayyorlash (kompyuterda)")
    exp.add_argument("excel_dir")
    exp.add_argument("out")
    imp = sub.add_parser("import", help="JSON'dan bazaga yozish (serverda)")
    imp.add_argument("json_path")
    imp.add_argument("--dry-run", action="store_true")
    pck = sub.add_parser("pack", help="JSON'ni shifrlangan .py faylga joylash (kompyuterda)")
    pck.add_argument("json_path")
    pck.add_argument("out_py")
    args = parser.parse_args(argv)

    if args.command == "export":
        export_excel(args.excel_dir, args.out)
        return 0
    if args.command == "pack":
        passphrase = os.environ.get(KEY_ENV) or getpass.getpass("Shifrlash kaliti: ")
        for course, count in pack(args.json_path, args.out_py, passphrase).items():
            print(f"  {course}-kurs: {count} ta")
        print(f"  -> {args.out_py}")
        return 0
    payload = json.loads(Path(args.json_path).read_text(encoding="utf-8"))
    return asyncio.run(run(payload["rows"], dry_run=args.dry_run))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
