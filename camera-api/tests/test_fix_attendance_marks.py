"""scripts/fix_attendance_marks.py — eski qoida va AI uzilishi qoldirgan
noto'g'ri "kech keldi" / "kelmadi" belgilarini tuzatish."""

import importlib.util
import sys
from datetime import date, datetime, time
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import AttendanceRecord, AuditLog, Building, Camera, PresenceVisit, StudentStaff, User
from app.timezone import INSTITUTE_TZ

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fix_attendance_marks.py"
DAY = date(2026, 9, 16)
OUTAGE_DAY = date(2026, 9, 18)


@pytest.fixture(scope="module")
def fix():
    spec = importlib.util.spec_from_file_location("fix_attendance_marks", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["fix_attendance_marks"] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("fix_attendance_marks", None)


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=INSTITUTE_TZ)


class TestJudgement:
    def test_rules(self, fix):
        cutoff = time(9, 0)
        assert fix.judge_late(time(10, 30), False, cutoff, None)[:2] == ("keldi", None)
        assert fix.judge_late(time(9, 20), True, cutoff, None) is None  # haqiqatan kech
        assert fix.judge_late(time(10, 30), True, cutoff, time(10, 16))[:2] == ("keldi", None)
        assert fix.judge_late(time(10, 5), True, cutoff, time(10, 16)) is None  # AI ishlagan paytda kech
        assert fix.judge_late(time(8, 40), True, cutoff, None)[:2] == ("keldi", time(8, 40))
        assert fix.judge_late(None, None, cutoff, None) is None
        # Kunduzgi birinchi kirish ko'rinishi — odatda ketish payti.
        assert fix.judge_late(time(16, 30), True, cutoff, None, time(12, 0))[:2] == ("keldi", None)
        assert fix.judge_late(time(9, 20), True, cutoff, None, time(12, 0)) is None
        # Siyrak kuzatilgan kun: ertalabki kechikish ham ishonchsiz.
        assert fix.judge_late(time(9, 20), True, cutoff, None, time(12, 0), True)[:2] == ("keldi", None)
        assert fix.judge_late(time(8, 40), True, cutoff, None, time(12, 0), True)[:2] == ("keldi", time(8, 40))


@pytest.mark.usefixtures("seeded")
class TestPlanAndApply:
    @pytest.fixture
    async def world(self, db_session):
        building = (await db_session.execute(select(Building))).scalars().first()
        door = Camera(name="Eshik", ip="10.3.0.1", building_id=building.id, zone="Kirish", resolution="1080p",
                      status="faol", is_entrance=True)
        room = Camera(name="205-xona", ip="10.3.0.2", building_id=building.id, zone="205", resolution="1080p",
                      status="faol")
        names = ["Xonada Ko'rilgan", "Rostdan Kechikkan", "Uzilishda Kelgan", "Dalilsiz Odam", "Qo'lda Tuzatilgan"]
        people = [StudentStaff(full_name=n, type="xodim", group_or_position="Kafedra",
                               biometrics_status="tasdiqlangan") for n in names]
        # "kelmadi" qamrovi uchun: DAY kuni 20 ta xodimdan 4 tasi tanilgan (20% < 30%).
        absentees = [StudentStaff(full_name=f"Kelmagan {i}", type="xodim", group_or_position="Kafedra",
                                  biometrics_status="tasdiqlangan") for i in range(15)]
        db_session.add_all([door, room, *people, *absentees])
        await db_session.commit()
        room_seen, late, outage, no_proof, manual = people

        def record(person, day, status, check_in=None):
            return AttendanceRecord(student_staff_id=person.id, date=day, status=status, check_in=check_in)

        def visit(person, camera, moment):
            return PresenceVisit(student_staff_id=person.id, camera_id=camera.id, first_seen_at=moment,
                                 last_seen_at=moment, sightings=1)

        admin = (await db_session.execute(select(User).where(User.login == "admin"))).scalar_one()
        db_session.add_all([
            record(room_seen, DAY, "kech_keldi", time(10, 30)), visit(room_seen, room, _at(DAY, 10, 30)),
            visit(room_seen, door, _at(DAY, 16, 0)),
            record(late, DAY, "kech_keldi", time(9, 20)), visit(late, door, _at(DAY, 9, 20)),
            record(outage, OUTAGE_DAY, "kech_keldi", time(10, 30)), visit(outage, door, _at(OUTAGE_DAY, 10, 30)),
            record(no_proof, DAY, "kech_keldi", time(11, 0)),
            record(manual, DAY, "kech_keldi", time(9, 45)), visit(manual, room, _at(DAY, 9, 45)),
            AuditLog(user_id=admin.id, user_name="Jamshid Alimov", action=f"Davomat qayd etdi: {manual.full_name} ({DAY})",
                     module="Talabalar", status="muvaffaqiyatli", ip="192.168.0.1"),
            *[record(person, DAY, "kelmadi") for person in absentees],
        ])
        await db_session.commit()
        return {"room": room_seen, "late": late, "outage": outage, "no_proof": no_proof, "manual": manual,
                "absentees": absentees}

    async def _status(self, db_session, person, day):
        record = (await db_session.execute(
            select(AttendanceRecord).where(AttendanceRecord.student_staff_id == person.id, AttendanceRecord.date == day)
            .execution_options(populate_existing=True)
        )).scalar_one_or_none()
        return (record.status, record.check_in) if record else None

    async def test_plan_names_every_decision(self, fix, db_session, world):
        plan = await fix.build_plan(db_session, DAY, OUTAGE_DAY, {OUTAGE_DAY: time(10, 16)}, include_absences=True)

        assert {f.person for f in plan.late_fixes} == {"Xonada Ko'rilgan", "Uzilishda Kelgan"}
        assert [name for name, _, _ in plan.kept_late] == ["Rostdan Kechikkan"]
        assert {name for name, _, _ in plan.skipped} == {"Dalilsiz Odam", "Qo'lda Tuzatilgan"}
        assert [(g.day, g.recognized, g.enrolled, len(g.record_ids)) for g in plan.absences] == [(DAY, 4, 20, 15)]

    async def test_dry_run_writes_nothing(self, fix, db_session, world):
        await fix.build_plan(db_session, DAY, OUTAGE_DAY, {OUTAGE_DAY: time(10, 16)}, include_absences=True)
        assert await self._status(db_session, world["room"], DAY) == ("kech_keldi", time(10, 30))

    async def test_apply_fixes_and_logs_once_and_a_rerun_finds_nothing(self, fix, db_session, world):
        blind = {OUTAGE_DAY: time(10, 16)}
        plan = await fix.build_plan(db_session, DAY, OUTAGE_DAY, blind, include_absences=True)
        await fix.apply_plan(db_session, plan, blind)

        assert await self._status(db_session, world["room"], DAY) == ("keldi", None)
        assert await self._status(db_session, world["outage"], OUTAGE_DAY) == ("keldi", None)
        assert await self._status(db_session, world["late"], DAY) == ("kech_keldi", time(9, 20))
        assert await self._status(db_session, world["no_proof"], DAY) == ("kech_keldi", time(11, 0))
        assert await self._status(db_session, world["manual"], DAY) == ("kech_keldi", time(9, 45))
        assert all([await self._status(db_session, p, DAY) is None for p in world["absentees"]])

        logs = (await db_session.execute(select(AuditLog.action).where(AuditLog.user_name == "Tizim skripti"))).scalars().all()
        assert len(logs) == 1 and "2 ta" in logs[0] and "15 ta" in logs[0] and "10:16" in logs[0]

        again = await fix.build_plan(db_session, DAY, OUTAGE_DAY, blind, include_absences=True)
        assert again.late_fixes == [] and again.absences == []

    async def test_an_unreliable_day_clears_even_genuine_looking_late_marks(self, fix, db_session, world):
        plan = await fix.build_plan(db_session, DAY, DAY, {}, include_absences=False, unreliable_days={DAY})
        assert "Rostdan Kechikkan" in {f.person for f in plan.late_fixes}
        assert plan.kept_late == []

    async def test_absences_are_left_alone_without_the_flag(self, fix, db_session, world):
        plan = await fix.build_plan(db_session, DAY, DAY, {}, include_absences=False)
        assert plan.absences == []
