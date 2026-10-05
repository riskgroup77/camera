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
HEMIS kelish vaqtini bermaydi: vaqt bo'sh qoladi va "kech keldi" taxmin
qilinmaydi. Kamera yozgan yozuvga tegilmaydi (haqiqiy vaqti bor).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


def _id(value: Any) -> Any:
    return value.get("id") if isinstance(value, dict) else None


def _pair(row: dict) -> str:
    pair = row.get("lessonPair") or {}
    return str(pair.get("code") or pair.get("name") or "")


@dataclass
class DayAttendance:
    # HEMIS talaba id (student-list "id") -> "keldi" | "kelmadi"
    students: dict[Any, str] = field(default_factory=dict)
    # Dars o'tgan o'qituvchilar (employee-list "id")
    teachers: set = field(default_factory=set)
    groups_checked: int = 0
    groups_without_students: int = 0


def day_attendance(controls: list[dict], absences: list[dict], students_by_group: dict[Any, list[Any]]) -> DayAttendance:
    """Toza funksiya — sinovlanadi. `students_by_group` — HEMIS guruh id ->
    shu guruhdagi faol talabalar id'lari (student-list)."""
    held: dict[Any, set[str]] = defaultdict(set)
    out = DayAttendance()
    for row in controls:
        group = _id(row.get("group"))
        if group is None:
            continue
        held[group].add(_pair(row))
        teacher = _id(row.get("employee"))
        if teacher is not None:
            out.teachers.add(teacher)
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
            out.students[student] = "kelmadi" if pairs <= missed.get(student, set()) else "keldi"
    return out
