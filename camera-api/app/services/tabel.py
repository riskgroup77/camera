"""Oylik davomat tabeli: qatorlar — odamlar, ustunlar — oyning kunlari.

Bu rektorat chop etib, imzolab qo'yadigan qog'oz: har bir katakda bitta
belgi, o'ngda yakunlar. Shuning uchun ikki qoida:

  * jadvaldan HECH KIM tushib qolmaydi — yuzi tizimga kiritilmagan odam
    ham qatorda turadi, faqat uning kataklari "ma'lumot yo'q" bo'ladi;
  * "bilmaymiz" va "kelmadi" hech qachon aralashmaydi — `·` alohida
    ustunda sanaladi, `–` ga qo'shilmaydi.

Aholi, filtrlar, tanlov nomi va izohlar app/services/hisobot.py dan
olinadi: hisobot sahifasi bilan bir xil odamlar, bir xil gaplar.
Ish kunlari va kechikish daqiqasi — app/services/attendance_policy.py
(butun tizimdagi bitta qoida).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date as date_type, time as time_type, timedelta

from fastapi import HTTPException, status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AIModuleConfig, AttendanceRecord
from app.services import hisobot
from app.services import situation as svc
from app.services.attendance_policy import Policy

# Belgilar — qog'ozda ham, ekranda ham bir xil (izoh `legend` da).
MARK_PRESENT = "+"
MARK_LATE = "K"
MARK_ABSENT = "–"   # en-dash: "-" bilan adashmasin
MARK_OFF = "D"
MARK_UNKNOWN = "·"  # o'rta nuqta

LEGEND = [
    {"mark": MARK_PRESENT, "label": "Keldi"},
    {"mark": MARK_LATE, "label": "Kech keldi"},
    {"mark": MARK_ABSENT, "label": "Kelmadi"},
    {"mark": MARK_OFF, "label": "Dam olish / ish kuni emas"},
    {"mark": MARK_UNKNOWN, "label": "Ma'lumot yo'q"},
]

WEEKDAYS = ("Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya")  # isoweekday 1..7
MONTHS = ("yanvar", "fevral", "mart", "aprel", "may", "iyun",
          "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr")

TITLE = "Davomat tabeli"
# Qog'ozdagi jadval uchun chegara: 300 qatordan keyin tabel o'qilmaydi,
# shuning uchun ro'yxat kesiladi va buni `note` da ochiq aytamiz.
PEOPLE_LIMIT = hisobot.PEOPLE_LIMIT


def month_bounds(oy: str) -> tuple[date_type, date_type]:
    """"YYYY-MM" -> oyning birinchi va oxirgi kuni."""
    try:
        year, month = oy.split("-")
        start = date_type(int(year), int(month), 1)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "'oy' 'YYYY-MM' formatida bo'lishi kerak") from exc
    end = date_type(start.year + (start.month == 12), start.month % 12 + 1, 1) - timedelta(days=1)
    return start, end


def month_label(start: date_type) -> str:
    return f"{start.year}-yil {MONTHS[start.month - 1]}"


def _hhmm(value: time_type | None) -> str | None:
    return value.strftime("%H:%M") if value is not None else None


@dataclass(frozen=True)
class _Rec:
    status: str
    check_in: time_type | None


def _cell(day: date_type, *, mark: str, title: str) -> dict:
    return {"day": day.day, "mark": mark, "title": title}


def build_cells(member: hisobot.Member, days: list[date_type], records: dict[date_type, _Rec],
                policy: Policy, kind: str, today: date_type, no_data_title: str) -> tuple[list[dict], dict]:
    """Bitta odamning bir oylik qatori va yakunlari.

    Tartib muhim: ish kuni emasligi HAMMA uchun bir xil (`D`), keyin
    "bilib bo'lmaydigan" sabablar (yuz kiritilmagan, kun hali kelmagan),
    eng oxirida haqiqiy yozuv.
    """
    cells: list[dict] = []
    present = late = absent = unknown = off = 0
    for day in days:
        rec = records.get(day)
        if not policy.is_work_day(day) or (rec is not None and rec.status == "dam_olish"):
            cells.append(_cell(day, mark=MARK_OFF, title="dam olish kuni"))
            off += 1
            continue
        if not member.enrolled and rec is None:
            # Yuzsiz odamning ham turniket yoki qo'lda kiritilgan yozuvi bo'lishi
            # mumkin — u bor bo'lsa hisobot sahifasi kabi hisobga olinadi.
            cells.append(_cell(day, mark=MARK_UNKNOWN, title="yuzi tizimga kiritilmagan"))
            unknown += 1
            continue
        if day > today:
            cells.append(_cell(day, mark=MARK_UNKNOWN, title="kun hali kelmagan"))
            unknown += 1
            continue
        if rec is None:
            cells.append(_cell(day, mark=MARK_UNKNOWN, title=no_data_title))
            unknown += 1
            continue
        if rec.status == "kech_keldi":
            minutes = policy.late_minutes(rec.check_in, kind, day)
            arrived = _hhmm(rec.check_in)
            title = f"{arrived} keldi, {minutes} daqiqa kech" if arrived else f"{minutes} daqiqa kech keldi"
            cells.append(_cell(day, mark=MARK_LATE, title=title))
            late += 1
        elif rec.status == "keldi":
            arrived = _hhmm(rec.check_in)
            cells.append(_cell(day, mark=MARK_PRESENT, title=f"{arrived} keldi" if arrived else "keldi"))
            present += 1
        else:  # kelmadi
            cells.append(_cell(day, mark=MARK_ABSENT, title="kun davomida kamerada ko'rinmadi"))
            absent += 1
    totals = {"present": present, "late": late, "absent": absent, "unknown": unknown,
              # Ish kunlari — shu odam bo'yicha `D` bo'lmagan kunlar:
              # present + late + absent + unknown ayni shunga teng.
              "workDays": len(days) - off}
    return cells, totals


async def _records(db: AsyncSession, ids: list[uuid.UUID], start: date_type,
                   end: date_type) -> dict[uuid.UUID, dict[date_type, _Rec]]:
    """Butun oy uchun BITTA so'rov: (odam -> kun -> yozuv)."""
    out: dict[uuid.UUID, dict[date_type, _Rec]] = {}
    if not ids:
        return out
    rows = await db.execute(
        select(AttendanceRecord.student_staff_id, AttendanceRecord.date, AttendanceRecord.status,
               AttendanceRecord.check_in)
        .where(AttendanceRecord.student_staff_id.in_(ids))
        .where(AttendanceRecord.date.between(start, end))
    )
    for pid, day, status, check_in in rows.all():
        out.setdefault(pid, {})[day] = _Rec(status, check_in)
    return out


def _note(kind: str, total: int, missing: int, capped: int, module_off: str | None, has_records: bool) -> str | None:
    """Tabelda nima yetishmayotgani — hisobot sahifasidagi ayni gaplar bilan."""
    parts: list[str] = []
    if capped:
        parts.append(f"Ro'yxat {PEOPLE_LIMIT} kishida kesildi ({capped} kishi jadvalga kirmadi) — "
                     "fakultet yoki guruhni torroq tanlang.")
    if module_off:
        parts.append(module_off + (" Quyidagi belgilar oldin yig'ilgan yozuvlardan."
                                   if has_records else " Shuning uchun oyning kunlari bo'sh."))
    if missing and total:
        share = round(missing * 100 / total)
        line = hisobot.not_enrolled_note(total, missing)
        if share >= 20:
            line = f"Diqqat: {line} Ya'ni tabelning {share}% i o'lchanmagan."
        parts.append(line)
    if not has_records and not module_off:
        who = "talaba" if kind == "talaba" else "xodim"
        parts.append(f"Bu oyda tanlangan {who}lar bo'yicha birorta davomat yozuvi yo'q.")
    return " ".join(parts) or None


async def build(db: AsyncSession, kind: str, oy: str, f: hisobot.Filters) -> dict:
    start, end = month_bounds(oy)
    ctx = await hisobot.context(db, kind, start, end, f)
    policy = await hisobot.load_policy(db)
    active = set((await db.execute(
        select(AIModuleConfig.code).where(AIModuleConfig.active.is_(True)))).scalars().all())
    module_off = hisobot.module_off_text(kind, active, "davomat")

    today = svc.today()
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    day_rows = [{"day": d.day, "weekday": WEEKDAYS[d.isoweekday() - 1],
                 "isWorkDay": policy.is_work_day(d), "isFuture": d > today} for d in days]

    members = sorted(ctx.members, key=lambda m: svc.norm_name(m.name))
    capped = max(0, len(members) - PEOPLE_LIMIT)
    members = members[:PEOPLE_LIMIT]
    records = await _records(db, [m.id for m in members], start, end)
    unit_label = hisobot.unit_label_fn(ctx)
    no_data_title = ("davomat o'sha kuni yig'ilmagan" if module_off
                     else "bu kuni yozuv yo'q — kamerada ham ko'rinmadi, kelmadi deb ham belgilanmadi")

    people: list[dict] = []
    grand = {"people": 0, "present": 0, "late": 0, "absent": 0, "unknown": 0, "notEnrolled": 0}
    for m in members:
        cells, totals = build_cells(m, days, records.get(m.id, {}), policy, kind, today, no_data_title)
        if kind == "talaba":
            _course, group = hisobot.student_course_group(m.raw)
        else:
            group = unit_label(m)
        people.append({"id": str(m.id), "fullName": m.name, "group": group or "",
                       "enrolled": m.enrolled, "cells": cells, "totals": totals})
        grand["people"] += 1
        for key in ("present", "late", "absent", "unknown"):
            grand[key] += totals[key]
        if not m.enrolled:
            grand["notEnrolled"] += 1

    missing = grand["notEnrolled"]
    return {
        "title": TITLE,
        "scope": hisobot.scope_label(kind, f, ctx.faculty_names, ctx.members, ctx.unit_of),
        "month": f"{start.year:04d}-{start.month:02d}",
        "monthLabel": month_label(start),
        "days": day_rows,
        "people": people,
        "totals": grand,
        "legend": LEGEND,
        # Bo'lim va kesilganlik alohida maydonlarda: ilgari bu faqat `note`
        # matnining ichida edi, shuning uchun interfeys qaysi bo'lim
        # kelganini bilolmay, eski varaqni yangi sarlavha ostida ko'rsatardi.
        "kind": kind,
        "capped": capped > 0,
        "cappedCount": capped,
        "peopleLimit": PEOPLE_LIMIT,
        "note": _note(kind, len(people), missing, capped, module_off, bool(records)),
    }
