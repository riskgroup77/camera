"""TT kriteriya 9 ("Erta ketish") — productionda topilgan ikki xato.

1. Soat 15:50 da bugungi kun "erta ketdi" deb belgilangan edi: oxirgi
   chiqish 15:02, cutoff 16:00 — kun hali tugamagan, odam binoda.
2. Barcha kirish eshiklari chiqish ham bo'lgani uchun tushlikka chiqib
   qaytgan odamning check_out i 12:00 bo'lib qolardi, keyin uni xonada
   ko'rgan kameralar hisobga olinmasdi.
"""

from datetime import date, datetime, time, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import AttendanceRecord, Building, Camera, Faculty, PresenceVisit, StudentStaff
from app.routers.attendance import _is_early_leave
from app.timezone import INSTITUTE_TZ
from tests.conftest import auth_headers

PAST_DAY = date(2026, 8, 3)


def _record(day: date, check_in: str | None, check_out: str | None, status: str = "keldi") -> AttendanceRecord:
    return AttendanceRecord(
        date=day,
        status=status,
        check_in=time.fromisoformat(check_in) if check_in else None,
        check_out=time.fromisoformat(check_out) if check_out else None,
    )


class TestIsEarlyLeave:
    """`sightings` — o'sha kuni odam necha marta ko'rilgani. Usiz (yoki bitta
    ko'rinish bilan) javob "aniqlanmadi", ya'ni erta ketish emas."""

    def test_past_day_with_final_exit_before_cutoff(self):
        assert _is_early_leave(_record(PAST_DAY, "08:00", "14:30"), time(14, 30), sightings=6) is True

    def test_today_is_not_judged_before_the_cutoff(self):
        today = date(2026, 9, 17)
        now = datetime(2026, 9, 17, 15, 50, tzinfo=INSTITUTE_TZ)
        assert _is_early_leave(_record(today, "10:23", "15:02"), None, now=now) is False

    def test_today_is_judged_once_the_cutoff_has_passed(self):
        today = date(2026, 9, 17)
        now = datetime(2026, 9, 17, 18, 5, tzinfo=INSTITUTE_TZ)
        assert _is_early_leave(_record(today, "10:23", "15:02"), time(15, 2), sightings=4, now=now) is True

    def test_seen_elsewhere_after_the_exit_is_not_early_leave(self):
        """Tushlikka chiqish: eshik 12:00 ni yozdi, xona kamerasi 15:30 da ko'rdi."""
        assert _is_early_leave(_record(PAST_DAY, "08:00", "12:00"), time(15, 30), sightings=6) is False

    def test_a_hallway_glimpse_right_after_the_exit_still_counts_as_leaving(self):
        assert _is_early_leave(_record(PAST_DAY, "08:00", "12:00"), time(12, 1), sightings=6) is True

    def test_unknown_arrival_is_never_early_leave(self):
        """Kelish vaqti noma'lum (birinchi ko'rinish xonada, cutoff dan keyin)."""
        assert _is_early_leave(_record(PAST_DAY, None, "14:30"), time(14, 30), sightings=6) is False

    def test_a_single_sighting_is_not_evidence_of_leaving(self):
        """Kamera odamni bir marta ko'rdi, keyin yo'qotdi — bu "erta ketdi" emas."""
        assert _is_early_leave(_record(PAST_DAY, "08:00", "14:30"), time(14, 30), sightings=1) is False
        assert _is_early_leave(_record(PAST_DAY, "08:00", "14:30"), time(14, 30)) is False


@pytest.fixture
async def person(db_session, seeded) -> StudentStaff:
    faculty = (await db_session.execute(select(Faculty))).scalars().first()
    row = StudentStaff(full_name="Tushlikka Chiqqan", type="xodim", faculty_id=faculty.id, group_or_position="Laborant")
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


@pytest.fixture
async def camera(db_session, seeded) -> Camera:
    building = (await db_session.execute(select(Building))).scalars().first()
    row = Camera(name="Xona kamerasi", ip="10.0.7.1", building_id=building.id, zone="Xona", resolution="1080p")
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


def _local(day: date, hhmm: str) -> datetime:
    return datetime.combine(day, time.fromisoformat(hhmm), tzinfo=INSTITUTE_TZ)


@pytest.mark.usefixtures("seeded")
class TestCalendarUsesTheLastSighting:
    async def test_later_sighting_on_any_camera_clears_early_leave(self, client: AsyncClient, db_session, person, camera):
        row = _record(PAST_DAY, "08:00", "12:00")
        row.student_staff_id = person.id
        db_session.add(row)
        db_session.add(
            PresenceVisit(
                student_staff_id=person.id,
                camera_id=camera.id,
                first_seen_at=_local(PAST_DAY, "15:00"),
                last_seen_at=_local(PAST_DAY, "15:30"),
                sightings=3,
            )
        )
        await db_session.commit()

        headers = await auth_headers(client, "admin", "admin123")
        days = (
            await client.get(f"/api/attendance/{person.id}", headers=headers, params={"month": "2026-08"})
        ).json()
        assert [d["earlyLeave"] for d in days] == [False]

        summary = (await client.get(f"/api/attendance/{person.id}/summary", headers=headers)).json()
        assert all(month["earlyLeave"] == 0 for month in summary["months"])

    async def test_final_exit_before_cutoff_is_still_reported(self, client: AsyncClient, db_session, person, camera):
        row = _record(PAST_DAY, "08:00", "13:00")
        row.student_staff_id = person.id
        db_session.add(row)
        db_session.add(
            PresenceVisit(
                student_staff_id=person.id,
                camera_id=camera.id,
                first_seen_at=_local(PAST_DAY, "12:30"),
                last_seen_at=_local(PAST_DAY, "13:00") + timedelta(seconds=30),
                sightings=2,
            )
        )
        await db_session.commit()

        headers = await auth_headers(client, "admin", "admin123")
        days = (
            await client.get(f"/api/attendance/{person.id}", headers=headers, params={"month": "2026-08"})
        ).json()
        assert [d["earlyLeave"] for d in days] == [True]
