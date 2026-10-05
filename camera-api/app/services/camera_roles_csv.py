"""Kamera rollarini CSV orqali ommaviy belgilash.

107 ta kameraga xona turi va raqamini bittalab kiritish real ish emas.
Admin ro'yxatni yuklab oladi (export_roles_csv), Excel'da `xona_turi` va
`xona_raqami` ustunlarini to'ldiradi va qaytarib yuklaydi
(import_roles_csv). Yuklash avval faqat ko'rsatadi — nima o'zgarishini,
qaysi qator nega o'qilmaganini — va faqat tasdiqlangandan keyin yozadi.

Qoidalar:
  * kamera `id` bo'yicha topiladi, id bo'lmasa — `ip` bo'yicha;
  * faqat `xona_turi`, `xona_raqami` va `yuz_yonalishi` (kirish kamerasi
    kirayotganlar yoki chiqayotganlarning yuzini ko'radi) o'zgaradi, qolgan ustunlar ma'lumot
    uchun (bino, zona va h.k. alohida sahifada tahrirlanadi);
  * bo'sh katak — o'zgartirmaslik; "-" — belgini olib tashlash;
  * xona turi kod ("auditoriya") yoki to'liq nom ("Auditoriya (dars
    xonasi)") bo'lishi mumkin, katta-kichik harf farqi yo'q.
"""

from __future__ import annotations

import csv
import io
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Camera
from app.services.camera_roles import ROOM_TYPE_LABELS, ROOM_TYPES, effective_room_type, normalize_room_code

EXPORT_COLUMNS = [
    "id",
    "nomi",
    "ip",
    "bino",
    "qavat",
    "zona",
    "kirish_chiqish",
    "perimetr",
    "amaldagi_tur",
    "xona_turi",
    "xona_raqami",
    "yuz_yonalishi",
]
CLEAR_MARK = "-"
MAX_ROWS = 2000

_ROOM_TYPE_LOOKUP: dict[str, str] = {code: code for code in ROOM_TYPES}
_ROOM_TYPE_LOOKUP.update({label.lower(): code for code, label in ROOM_TYPE_LABELS.items()})


def _yes(value: bool) -> str:
    return "ha" if value else ""


def export_roles_csv(cameras: list[Camera]) -> bytes:
    """UTF-8 BOM bilan — Excel o'zbekcha harflarni (o', g') buzmasin."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(EXPORT_COLUMNS)
    for camera in cameras:
        effective = effective_room_type(camera)
        writer.writerow(
            [
                str(camera.id),
                camera.name,
                camera.ip,
                camera.building.name if camera.building else "",
                "" if camera.floor is None else camera.floor,
                camera.zone,
                _yes(camera.is_entrance or camera.is_exit),
                _yes(camera.is_perimeter),
                ROOM_TYPE_LABELS.get(effective, "") if effective else "",
                camera.room_type or "",
                camera.room_code or "",
                camera.face_direction or "",
            ]
        )
    return ("﻿" + buffer.getvalue()).encode("utf-8")


@dataclass
class RoleChange:
    camera_id: str
    camera_name: str
    field: str  # "room_type" | "room_code" | "face_direction"
    old: str | None
    new: str | None


@dataclass
class RoleImportError:
    row: int
    message: str


@dataclass
class RolesImportResult:
    rows: int = 0
    changes: list[RoleChange] = field(default_factory=list)
    errors: list[RoleImportError] = field(default_factory=list)
    applied: bool = False


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _reader(text: str) -> csv.DictReader:
    """Excel ba'zi tillarda nuqta-vergul bilan saqlaydi — ajratuvchi sarlavhadan aniqlanadi."""
    first_line = text.split("\n", 1)[0]
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if reader.fieldnames:
        reader.fieldnames = [(name or "").strip().lower() for name in reader.fieldnames]
    return reader


def _parse_room_type(value: str) -> tuple[bool, str | None]:
    """(tushunildimi, qiymat). Bo'sh — o'zgartirmaslik (None qaytmaydi, chaqiruvchi tekshiradi)."""
    key = value.strip().lower()
    if key == CLEAR_MARK:
        return True, None
    code = _ROOM_TYPE_LOOKUP.get(key)
    return (code is not None), code


async def import_roles_csv(db: AsyncSession, raw: bytes, *, apply: bool, scope=None) -> RolesImportResult:
    """CSV'ni o'qiydi, o'zgarishlarni hisoblaydi va `apply` bo'lsa kameralarga
    yozadi (commit — chaqiruvchida, audit yozuvi bilan birga)."""
    result = RolesImportResult()
    reader = _reader(_decode(raw))
    columns = set(reader.fieldnames or [])
    if not ({"id", "ip"} & columns) or not ({"xona_turi", "xona_raqami", "yuz_yonalishi"} & columns):
        result.errors.append(
            RoleImportError(row=1, message="Sarlavhada 'id' (yoki 'ip') va 'xona_turi'/'xona_raqami' ustunlari bo'lishi kerak")
        )
        return result

    query = select(Camera).options(selectinload(Camera.building))
    if scope is not None:
        # Bino doirasi: doiradan tashqaridagi kamera "topilmadi" bo'ladi.
        query = query.where(scope)
    cameras = (await db.execute(query)).scalars().all()
    by_id = {str(camera.id): camera for camera in cameras}
    by_ip: dict[str, list[Camera]] = {}
    for camera in cameras:
        by_ip.setdefault(camera.ip.strip(), []).append(camera)

    seen: set[str] = set()
    for line_number, row in enumerate(reader, start=2):
        if result.rows >= MAX_ROWS:
            result.errors.append(RoleImportError(row=line_number, message=f"{MAX_ROWS} qatordan ko'p — qolgani o'qilmadi"))
            break
        values = {key: (value or "").strip() for key, value in row.items() if key}
        if not any(values.values()):
            continue
        result.rows += 1

        camera: Camera | None = None
        raw_id = values.get("id", "")
        if raw_id:
            try:
                camera = by_id.get(str(uuid.UUID(raw_id)))
            except ValueError:
                camera = None
        elif values.get("ip"):
            matches = by_ip.get(values["ip"], [])
            if len(matches) > 1:
                result.errors.append(
                    RoleImportError(row=line_number, message=f"IP {values['ip']} bir nechta kamerada — 'id' ustunini to'ldiring")
                )
                continue
            camera = matches[0] if matches else None
        if camera is None:
            result.errors.append(RoleImportError(row=line_number, message="Kamera topilmadi (id yoki ip)"))
            continue
        key = str(camera.id)
        if key in seen:
            result.errors.append(RoleImportError(row=line_number, message=f"'{camera.name}' fayl ichida ikki marta uchradi"))
            continue
        seen.add(key)

        # Qator to'liq tekshiriladi va faqat xatosiz bo'lsa qo'llanadi —
        # yarim qo'llangan qator (tur yozildi, raqam yo'q) chalkashtirardi.
        new_values: dict[str, str | None] = {}
        raw_type = values.get("xona_turi", "")
        if raw_type:
            understood, room_type = _parse_room_type(raw_type)
            if not understood:
                allowed = ", ".join(ROOM_TYPES)
                result.errors.append(
                    RoleImportError(row=line_number, message=f"Noma'lum xona turi '{raw_type}' — mumkin: {allowed} yoki '-'")
                )
                continue
            new_values["room_type"] = room_type
        raw_code = values.get("xona_raqami", "")
        if raw_code:
            room_code = None if raw_code == CLEAR_MARK else normalize_room_code(raw_code)
            if raw_code != CLEAR_MARK and room_code is None:
                result.errors.append(RoleImportError(row=line_number, message=f"Xona raqami o'qilmadi: '{raw_code}'"))
                continue
            new_values["room_code"] = room_code
        raw_direction = values.get("yuz_yonalishi", "").lower()
        if raw_direction:
            if raw_direction not in ("kirish", "chiqish", CLEAR_MARK):
                result.errors.append(
                    RoleImportError(row=line_number, message=f"yuz_yonalishi '{raw_direction}' — mumkin: kirish, chiqish yoki '-'")
                )
                continue
            new_values["face_direction"] = None if raw_direction == CLEAR_MARK else raw_direction

        for field_name, new_value in new_values.items():
            old_value = getattr(camera, field_name)
            if new_value == old_value:
                continue
            result.changes.append(RoleChange(key, camera.name, field_name, old_value, new_value))
            if apply:
                setattr(camera, field_name, new_value)

    result.applied = apply and bool(result.changes)
    return result
