"""Bir kunlik davomatni HEMIS'dan bazaga yozish — qoida: app/services/hemis_attendance.py.

scripts/hemis_davomat.py (qo'lda) va app/jobs/hemis_attendance_sync.py (har
30 daqiqada) shu funksiyani chaqiradi.

Qoidalar:
  * kamera, turniket va qo'lda kiritilgan yozuvlarga TEGILMAYDI — HEMIS
    faqat yozuvi yo'q odamni to'ldiradi (source='hemis');
  * kun davomida qayta ishga tushirish xavfsiz va YAQINLASHADI: ertalabki
    darslarda yo'q bo'lgani uchun "kelmadi" yozilgan talaba keyingi darsda
    belgilansa — HEMIS yozuvi "keldi" ga o'tadi (vaqti — birinchi qatnashgan
    darsi boshlanishi);
  * `finalize` (o'tgan kun yoki tugash soatidan keyin): HEMIS dars
    jadvalida darsi bo'lib (lesson_sessions.teacher_id), shu kuni birorta
    darsi HEMIS'da o'tkazilmagan o'qituvchi — "kelmadi".
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from app.database import SessionLocal
from app.models import AttendanceRecord, AuditLog, LessonSession, StudentStaff
from app.services.hemis_attendance import day_attendance
from app.services.integrations import hemis

SOURCE = "hemis"
AUDIT_USER = "HEMIS davomati"


@dataclass
class SyncResult:
    day: date
    lessons: int = 0
    groups_checked: int = 0
    groups_without_students: int = 0
    absences: int = 0
    hemis_present: int = 0
    hemis_absent: int = 0
    teachers: int = 0
    found: int = 0
    already: int = 0
    inserted: Counter = field(default_factory=Counter)
    upgraded: int = 0
    retimed: int = 0
    teachers_absent: int = 0
    applied: bool = False

    def lines(self) -> list[str]:
        mark = "" if self.applied else "   (SINOV — yozilmadi; --qollash bilan yoziladi)"
        return [
            f"HEMIS {self.day}: davomat olingan darslar {self.lessons}, guruhlar {self.groups_checked} "
            f"(talabasi topilmagan {self.groups_without_students}), kelmaganlik qaydlari {self.absences}",
            f"  HEMIS bo'yicha talabalar: keldi {self.hemis_present}, kelmadi {self.hemis_absent}; "
            f"dars o'tgan o'qituvchilar {self.teachers}",
            f"  bazada topildi: {self.found}; shu kuni yozuvi bor — yangisi qo'shilmaydi: {self.already}",
            f"  YOZILADI: talaba keldi {self.inserted[('talaba', 'keldi')]}, "
            f"talaba kelmadi {self.inserted[('talaba', 'kelmadi')]}, xodim keldi {self.inserted[('xodim', 'keldi')]}, "
            f"darsi o'tmagan o'qituvchi (kelmadi) {self.teachers_absent}{mark}",
            f"  kelmadi -> keldi (keyingi darsda belgilangan): {self.upgraded}; kelish vaqti qo'yildi: {self.retimed}",
        ]


async def fetch_day(day: date) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    # HEMIS lesson_date — kunning UTC yarim tuni (1791158400 = 2026-10-05).
    start = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())
    params = {"lesson_date_from": start, "lesson_date_to": start + 86399}
    async with hemis.HemisClient() as client:
        controls = await client.fetch_all("attendance-control-list", params=params)
        absences = await client.fetch_all("attendance-list", params=params)
        students = await client.fetch_all(hemis.ENTITY_ENDPOINTS["students"])
        employees = await hemis.fetch_employees(client)
    # Boshqa kunlar aralashmasin (filtr e'tiborsiz qolsa ham).
    controls = [r for r in controls if r.get("lesson_date") in (None, start)]
    absences = [r for r in absences if r.get("lesson_date") in (None, start)]
    return controls, absences, students, employees


def plan_person(
    kind: str, status: str | None, at: time | None, old
) -> tuple[str, tuple | None]:
    """Bitta odam uchun qaror (toza funksiya — sinovlanadi):
    ("insert", (status, at)) | ("upgrade", at) | ("retime", at) | ("skip", None).
    `old` — shu kungi mavjud yozuv (source, status, check_in) yoki None."""
    if status is None:
        return "skip", None
    if old is None:
        return "insert", (status, at)
    if old.source != SOURCE:
        return "skip", None  # kamera / turniket / qo'lda — tegilmaydi
    if status == "keldi" and old.status == "kelmadi":
        return "upgrade", at
    if status == "keldi" and old.status in ("keldi", "kech_keldi") and old.check_in is None and at is not None:
        return "retime", at
    return "skip", None


async def sync_day(day: date, *, apply: bool, finalize: bool = False) -> SyncResult:
    controls, absences, students, employees = await fetch_day(day)
    by_group: dict = {}
    number_of: dict = {}
    for item in students:
        person = hemis.map_student(item)
        group = (item.get("group") or {}).get("id") if isinstance(item.get("group"), dict) else None
        if person is None or not person.active or item.get("id") is None:
            continue
        number_of[item["id"]] = person.hemis_id
        if group is not None:
            by_group.setdefault(group, []).append(item["id"])
    staff_number = {}
    for item in employees:
        mapped = hemis.map_employee(item) if item.get("id") is not None else None
        if mapped is not None:
            staff_number[item["id"]] = mapped.hemis_id

    attendance = day_attendance(controls, absences, by_group)
    wanted: dict[str, str] = {number_of[s]: st for s, st in attendance.students.items() if s in number_of}
    times: dict = {number_of[s]: at for s, at in attendance.student_times.items() if s in number_of}
    teachers = {staff_number[t] for t in attendance.teachers if t in staff_number}
    times.update({staff_number[t]: at for t, at in attendance.teacher_times.items() if t in staff_number})

    result = SyncResult(
        day=day,
        lessons=len(controls),
        groups_checked=attendance.groups_checked,
        groups_without_students=attendance.groups_without_students,
        absences=len(absences),
        hemis_present=sum(1 for s in wanted.values() if s == "keldi"),
        hemis_absent=sum(1 for s in wanted.values() if s == "kelmadi"),
        teachers=len(teachers),
        applied=apply,
    )

    async with SessionLocal() as db:
        rows = (await db.execute(
            select(StudentStaff.id, StudentStaff.hemis_id, StudentStaff.type)
            .where(StudentStaff.active.is_(True), StudentStaff.hemis_id.in_([*wanted, *teachers]))
        )).all()
        records = {r.student_staff_id: r for r in (await db.execute(
            select(AttendanceRecord.student_staff_id, AttendanceRecord.source, AttendanceRecord.check_in,
                   AttendanceRecord.status)
            .where(AttendanceRecord.date == day)
        )).all()}
        result.found = len(rows)
        result.already = sum(1 for pid, *_ in rows if pid in records)

        inserts: list[tuple] = []
        upgrades: list[tuple] = []
        retimes: list[tuple] = []
        present_ids = set()
        for pid, hemis_id, kind in rows:
            status = wanted.get(hemis_id) if kind == "talaba" else ("keldi" if hemis_id in teachers else None)
            if status == "keldi":
                present_ids.add(pid)
            at = times.get(hemis_id) if status == "keldi" else None
            action, value = plan_person(kind, status, at, records.get(pid))
            if action == "insert":
                inserts.append((pid, kind, *value))
            elif action == "upgrade":
                upgrades.append((pid, value))
            elif action == "retime":
                retimes.append((pid, value))

        if finalize:
            # Darsi jadvalda bo'lgan, lekin birorta darsi HEMIS'da o'tkazilmagan
            # o'qituvchi — yozuvi yo'q bo'lsa "kelmadi".
            scheduled = set((await db.execute(
                select(LessonSession.teacher_id).join(StudentStaff, StudentStaff.id == LessonSession.teacher_id)
                .where(LessonSession.date == day, LessonSession.teacher_id.is_not(None),
                       StudentStaff.active.is_(True))
                .distinct()
            )).scalars().all())
            for pid in scheduled - present_ids:
                if pid not in records:
                    inserts.append((pid, "xodim", "kelmadi", None))
                    result.teachers_absent += 1

        result.inserted = Counter((kind, status) for _, kind, status, _ in inserts if not (kind == "xodim" and status == "kelmadi"))
        result.upgraded = len(upgrades)
        result.retimed = len(retimes)
        if not apply or not (inserts or upgrades or retimes):
            return result
        for start in range(0, len(inserts), 1000):
            chunk = inserts[start:start + 1000]
            await db.execute(
                insert(AttendanceRecord)
                .values([{"student_staff_id": pid, "date": day, "status": status, "source": SOURCE, "check_in": at}
                         for pid, _, status, at in chunk])
                .on_conflict_do_nothing(index_elements=["student_staff_id", "date"])
            )
        for pid, at in upgrades:
            await db.execute(
                update(AttendanceRecord)
                .where(AttendanceRecord.student_staff_id == pid, AttendanceRecord.date == day,
                       AttendanceRecord.source == SOURCE, AttendanceRecord.status == "kelmadi")
                .values(status="keldi", check_in=at)
            )
        for pid, at in retimes:
            await db.execute(
                update(AttendanceRecord)
                .where(AttendanceRecord.student_staff_id == pid, AttendanceRecord.date == day,
                       AttendanceRecord.source == SOURCE, AttendanceRecord.check_in.is_(None))
                .values(check_in=at)
            )
        db.add(AuditLog(
            user_id=None, user_name=AUDIT_USER, module="Davomat", status="muvaffaqiyatli", ip="internal",
            action=(f"{day} davomati HEMIS'dan: {dict(result.inserted)}; o'qituvchi kelmadi: {result.teachers_absent}; "
                    f"kelmadi->keldi: {result.upgraded}; kelish vaqti: {result.retimed}"),
        ))
        await db.commit()
    return result
