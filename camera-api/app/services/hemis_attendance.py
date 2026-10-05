"""Bir kunlik davomatni HEMIS'dan tiklash (dastur o'zi yuritmagan kun uchun).

HEMIS'da o'qituvchilar har dars juftligida davomat oladi:
  * attendance-control-list — davomat olingan darslar (guruh, o'qituvchi,
    juftlik);
  * attendance-list — darsga kelmagan talabalar (juftlik, absent_on —
    sababli, absent_off — sababsiz soatlar).

Qoida (taxmin emas — HEMIS'dagi qaydlar):
  * davomati olingan guruh talabasi kamida bitta darsda "yo'q" deb
    yozilmagan bo'lsa — keldi; hamma darslarida "yo'q" bo'lsa — kelmadi;
  * davomati olinmagan guruh — yozuv qo'yilmaydi (ma'lumot yo'q);
  * shu kuni dars o'tgan (davomat olgan) o'qituvchi — keldi.
Kelish vaqti — birinchi QATNASHGAN darsining boshlanishi (lessonPair
start_time): odam shu paytda darsda bo'lgani HEMIS'da qayd etilgan.
O'qituvchiga — birinchi o'tgan darsi. Holat "keldi" (darsiga kechikmagan;
"kech keldi" taxmin qilinmaydi). Kamera yozgan yozuvga tegilmaydi.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import time
from typing import Any


def _id(value: Any) -> Any:
    return value.get("id") if isinstance(value, dict) else None


def _pair(row: dict) -> str:
    pair = row.get("lessonPair") or {}
    return str(pair.get("code") or pair.get("name") or "")


def _start(row: dict) -> time | None:
    """lessonPair.start_time ("08:30") -> time; noto'g'ri qiymat — None."""
    raw = str((row.get("lessonPair") or {}).get("start_time") or "").strip()
    try:
        hours, minutes = raw.split(":")[:2]
        return time(int(hours), int(minutes))
    except (ValueError, TypeError):
        return None


@dataclass
class DayAttendance:
    # HEMIS talaba id (student-list "id") -> "keldi" | "kelmadi"
    students: dict[Any, str] = field(default_factory=dict)
    # Dars o'tgan o'qituvchilar (employee-list "id")
    teachers: set = field(default_factory=set)
    # Kelish vaqti: talaba — birinchi qatnashgan darsi, o'qituvchi — birinchi
    # o'tgan darsi boshlanishi (vaqti noma'lum bo'lsa — yo'q).
    student_times: dict[Any, time] = field(default_factory=dict)
    teacher_times: dict[Any, time] = field(default_factory=dict)
    groups_checked: int = 0
    groups_without_students: int = 0


def day_attendance(controls: list[dict], absences: list[dict], students_by_group: dict[Any, list[Any]]) -> DayAttendance:
    """Toza funksiya — sinovlanadi. `students_by_group` — HEMIS guruh id ->
    shu guruhdagi faol talabalar id'lari (student-list)."""
    held: dict[Any, set[str]] = defaultdict(set)
    starts: dict[str, time] = {}
    out = DayAttendance()
    for row in controls:
        group = _id(row.get("group"))
        if group is None:
            continue
        pair, start = _pair(row), _start(row)
        held[group].add(pair)
        if start is not None and (pair not in starts or start < starts[pair]):
            starts[pair] = start
        teacher = _id(row.get("employee"))
        if teacher is not None:
            out.teachers.add(teacher)
            if start is not None and (teacher not in out.teacher_times or start < out.teacher_times[teacher]):
                out.teacher_times[teacher] = start
    missed: dict[Any, set[str]] = defaultdict(set)
    for row in absences:
        if (row.get("absent_on") or 0) + (row.get("absent_off") or 0) <= 0:
            continue
        student = _id(row.get("student"))
        if student is not None:
            missed[student].add(_pair(row))
    for group, pairs in held.items():
        members = students_by_group.get(group, [])
        if not members:
            out.groups_without_students += 1
            continue
        out.groups_checked += 1
        for student in members:
            attended = pairs - missed.get(student, set())
            out.students[student] = "keldi" if attended else "kelmadi"
            times = [starts[p] for p in attended if p in starts]
            if times:
                out.student_times[student] = min(times)
    return out
