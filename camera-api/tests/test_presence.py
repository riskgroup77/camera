"""O'qituvchilar kuzatuvi: kim, qachon, qaysi bino va xonada bo'lgan va bu
darsiga bog'liqmi; hamda davomat kameralari holati.

Eng qimmat xato — noto'g'ri ayblov: o'qituvchi darsida bo'lgan, lekin
tizim "darsga kirmadi" deydi (yoki aksincha). Shuning uchun bog'liqlik
qoidalarining har biri alohida tekshiriladi.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.config import settings
from app.jobs.attendance_ai import process_camera_frame
from app.jobs.lesson_attendance import _group_roster
from app.models import AttendanceRecord, Building, Camera, LessonSession, PresenceVisit, StudentStaff
from app.services.face_matching import CandidateMatrix
from app.services.presence import record_visit
from app.timezone import INSTITUTE_TZ
from tests.conftest import auth_headers


def _today(hour: int, minute: int = 0) -> datetime:
    return datetime.now(INSTITUTE_TZ).replace(hour=hour, minute=minute, second=0, microsecond=0)


@pytest.fixture(autouse=True)
def _lesson_length(monkeypatch):
    monkeypatch.setattr(settings, "lesson_duration_minutes", 80)
    monkeypatch.setattr(settings, "attendance_late_to_lesson_grace_minutes", 5)


@pytest.fixture
async def place(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    entrance = Camera(name="Kirish-1", ip="10.1.0.1", building_id=building.id, zone="Asosiy kirish",
                      resolution="1080p", status="faol", is_entrance=True, is_exit=True, last_seen_at=_today(9))
    room = Camera(name="205-xona", ip="10.1.0.2", building_id=building.id, zone="205-xona",
                  resolution="1080p", status="faol", last_seen_at=_today(9))
    room2 = Camera(name="310-xona", ip="10.1.0.3", building_id=building.id, zone="310-xona",
                   resolution="1080p", status="faol", excluded_module_codes=[6, 7])
    teacher = StudentStaff(full_name="Yusupova Dilnoza Anvarovna", type="xodim", group_or_position="Anatomiya",
                           biometrics_status="tasdiqlangan", biometric_embedding="[0.1]")
    other = StudentStaff(full_name="Karimov Aziz Olimovich", type="xodim", group_or_position="Fiziologiya",
                         biometrics_status="tasdiqlangan", biometric_embedding="[0.1]")
    db_session.add_all([entrance, room, room2, teacher, other])
    await db_session.commit()
    for obj in (entrance, room, room2):
        await db_session.refresh(obj, attribute_names=["building"])
    return SimpleNamespace(building=building, entrance=entrance, room=room, room2=room2, teacher=teacher, other=other)


def _lesson(camera, start, *, teacher=None, subject="Anatomiya", group="DI-1625", teacher_name="Yusupova D."):
    return LessonSession(date=start.date(), group_name=group, faculty="Davolash ishi", teacher=teacher_name,
                         teacher_id=teacher.id if teacher else None, subject=subject, attention_score=0,
                         teacher_activity_score=0, camera_id=camera.id, scheduled_start_time=start)


def _visit(person, camera, first, last, sightings=5):
    return PresenceVisit(student_staff_id=person.id, camera_id=camera.id, first_seen_at=first,
                         last_seen_at=last, sightings=sightings)


class TestRecordingVisits:
    async def test_close_sightings_become_one_visit_a_long_gap_starts_another(self, db_session, place):
        await record_visit(db_session, place.teacher.id, place.room.id, _today(9, 0), 0.7)
        await record_visit(db_session, place.teacher.id, place.room.id, _today(9, 6), 0.8)
        await record_visit(db_session, place.teacher.id, place.room.id, _today(9, 40), 0.6)
        await db_session.commit()

        visits = (await db_session.execute(select(PresenceVisit).order_by(PresenceVisit.first_seen_at))).scalars().all()
        assert len(visits) == 2
        assert visits[0].sightings == 2
        assert visits[0].last_seen_at == _today(9, 6)
        assert visits[0].best_similarity == pytest.approx(0.8)

    async def test_face_recognition_writes_the_visit(self, db_session, place):
        """Yuz tanilgan zahoti tashrif yoziladi — kunlik davomat bilan birga."""
        vector = np.zeros(512)
        vector[0] = 1.0
        candidates = CandidateMatrix(ids=[str(place.teacher.id)], matrix=np.array([vector]),
                                     person_types={str(place.teacher.id): "xodim"})
        face = SimpleNamespace(embedding=vector, bbox=np.array([0, 0, 100, 120]))

        await process_camera_frame(b"frame", db_session, place.room, occurred_at=_today(9, 5),
                                   candidates=candidates, faces=[face])

        visit = (await db_session.execute(select(PresenceVisit))).scalar_one()
        assert visit.camera_id == place.room.id
        # Xona kamerasi odam binoga qachon kirganini bilmaydi: 09:05 da
        # xonada ko'rinish "kech keldi" degani emas (eshik kamerasi
        # ko'rmay qolgan bo'lishi mumkin). Faqat "keldi", kelish vaqti yo'q.
        record = (await db_session.execute(select(AttendanceRecord))).scalar_one()
        assert record.status == "keldi"
        assert record.check_in is None


class TestPersonDay:
    async def _day(self, client, person):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get(f"/api/presence/people/{person.id}/day", headers=headers,
                                params={"date": _today(9).date().isoformat()})
        assert resp.status_code == 200, resp.text
        return resp.json()

    async def test_every_visit_says_how_it_relates_to_a_lesson(self, client: AsyncClient, db_session, place):
        db_session.add_all([
            _lesson(place.room, _today(9), teacher=place.teacher),  # o'z darsi 09:00-10:20, 205-xona
            _lesson(place.room, _today(11), teacher=place.other, subject="Fiziologiya", teacher_name="Karimov A."),
            _lesson(place.room2, _today(13), teacher=place.teacher, subject="Anatomiya amaliyot"),  # 310-xona
            _visit(place.teacher, place.entrance, _today(8, 40), _today(8, 41)),
            _visit(place.teacher, place.room, _today(9, 3), _today(10, 15)),
            _visit(place.teacher, place.room, _today(11, 10), _today(11, 20)),
            _visit(place.teacher, place.entrance, _today(13, 5), _today(13, 6)),
        ])
        await db_session.commit()

        body = await self._day(client, place.teacher)
        relations = [(v["camera"], v["firstSeen"][:5], v["lesson"]["relation"]) for v in body["visits"]]
        assert relations == [
            ("Kirish-1", "08:40", "darsdan_tashqari"),
            ("205-xona", "09:03", "oz_darsi"),
            ("205-xona", "11:10", "boshqa_dars"),
            ("Kirish-1", "13:05", "darsi_boshqa_joyda"),
        ]
        assert body["buildings"] == [place.building.name]
        assert body["visits"][1]["durationMinutes"] == 72

        lessons = {l["startsAt"]: l for l in body["lessons"]}
        assert lessons["09:00"]["attended"] is True
        assert lessons["09:00"]["arrivedAt"] == "09:03"
        assert lessons["09:00"]["late"] is False  # 5 daqiqalik oraliq ichida
        assert lessons["13:00"]["attended"] is False

    async def test_a_day_without_a_schedule_still_shows_where_they_were(self, client, db_session, place):
        db_session.add(_visit(place.teacher, place.room, _today(10), _today(10, 30)))
        await db_session.commit()
        body = await self._day(client, place.teacher)
        assert body["visits"][0]["lesson"]["relation"] == "jadval_yoq"
        assert body["lessons"] == []

    async def test_late_arrival_to_own_lesson(self, client, db_session, place):
        db_session.add_all([_lesson(place.room, _today(9), teacher=place.teacher),
                            _visit(place.teacher, place.room, _today(9, 12), _today(10))])
        await db_session.commit()
        (lesson,) = (await self._day(client, place.teacher))["lessons"]
        assert lesson["attended"] is True and lesson["late"] is True

    async def test_unknown_person_is_404(self, client, place):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get("/api/presence/people/not-a-uuid/day", headers=headers)
        assert resp.status_code == 404


class TestTeachersList:
    async def test_summary_per_teacher(self, client: AsyncClient, db_session, place):
        db_session.add_all([
            _lesson(place.room, _today(9), teacher=place.teacher),
            _lesson(place.room2, _today(13), teacher=place.teacher),
            _visit(place.teacher, place.entrance, _today(8, 40), _today(8, 41)),
            _visit(place.teacher, place.room, _today(9, 2), _today(10)),
        ])
        await db_session.commit()

        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get("/api/presence/teachers", headers=headers,
                                params={"date": _today(9).date().isoformat()})
        (row,) = resp.json()
        assert row["fullName"] == "Yusupova Dilnoza Anvarovna"
        assert row["firstSeen"] == "08:40"
        assert row["lastSeen"] == "10:00"
        assert row["visits"] == 2
        assert (row["lessonsScheduled"], row["lessonsAttended"]) == (2, 1)

    async def test_search_by_name(self, client, db_session, place):
        db_session.add_all([_visit(place.teacher, place.room, _today(9), _today(9, 10)),
                            _visit(place.other, place.room, _today(9), _today(9, 10))])
        await db_session.commit()
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get("/api/presence/teachers", headers=headers,
                                params={"date": _today(9).date().isoformat(), "search": "karimov"})
        assert [r["fullName"] for r in resp.json()] == ["Karimov Aziz Olimovich"]


class TestAttendanceCameras:
    async def test_which_cameras_serve_attendance_and_what_they_saw(self, client: AsyncClient, db_session, place,
                                                                     monkeypatch):
        # Eski tartib: kunlik davomat faqat kirish kameralarida.
        monkeypatch.setattr(settings, "attendance_any_camera", False)
        db_session.add(_visit(place.teacher, place.room, datetime.now(INSTITUTE_TZ) - timedelta(minutes=5),
                              datetime.now(INSTITUTE_TZ)))
        await db_session.commit()

        headers = await auth_headers(client, "admin", "admin123")
        body = (await client.get("/api/presence/cameras", headers=headers)).json()
        cams = {c["name"]: c for c in body["cameras"]}

        assert cams["Kirish-1"]["role"] == "Kirish/chiqish"
        assert cams["Kirish-1"]["checkIntervalSeconds"] == settings.entrance_exit_attendance_interval_seconds
        # Kunlik davomat faqat kirish kameralarida (2026-09-18 qarori) — xona
        # kamerasi tashriflarni yozadi, lekin kunlik davomat bermaydi.
        assert cams["205-xona"]["attendanceEnabled"] is False
        assert "faqat kirish" in cams["205-xona"]["disabledReason"]
        assert cams["205-xona"]["recognizedToday"] == 1
        assert cams["310-xona"]["attendanceEnabled"] is False
        assert body["peopleRecognizedToday"] == 1
        assert body["entrance"] == 1

    async def test_any_camera_marks_arrival(self, client: AsyncClient, place, monkeypatch):
        # Hozirgi tartib (attendance_any_camera): odamni birinchi ko'rgan
        # istalgan faol kamera kelishni yozadi — xona kamerasi ham.
        monkeypatch.setattr(settings, "attendance_any_camera", True)
        headers = await auth_headers(client, "admin", "admin123")
        cams = {c["name"]: c for c in (await client.get("/api/presence/cameras", headers=headers)).json()["cameras"]}
        assert cams["205-xona"]["attendanceEnabled"] is True
        assert cams["205-xona"]["disabledReason"] is None

    async def test_requires_login(self, client: AsyncClient):
        resp = await client.get("/api/presence/cameras")
        assert resp.status_code in (401, 403)


async def test_lesson_roster_includes_imported_students_with_course_prefix(db_session, seeded):
    """Import "2-kurs, DI-1625" deb yozadi, jadval esa "DI-1625" — ilgari
    import qilingan birorta talaba darsga bog'lanmasdi."""
    db_session.add_all([
        StudentStaff(full_name="Import Talaba", type="talaba", group_or_position="2-kurs, DI-1625",
                     biometrics_status="tasdiqlangan"),
        StudentStaff(full_name="Qo'lda Talaba", type="talaba", group_or_position="DI-1625",
                     biometrics_status="tasdiqlangan"),
        StudentStaff(full_name="Boshqa Guruh", type="talaba", group_or_position="2-kurs, DI-16250",
                     biometrics_status="tasdiqlangan"),
    ])
    await db_session.commit()
    names = sorted(p.full_name for p in await _group_roster(db_session, "DI-1625"))
    assert names == ["Import Talaba", "Qo'lda Talaba"]
