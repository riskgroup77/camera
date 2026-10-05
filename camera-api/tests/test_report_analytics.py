"""Hisobotlar sahifasining jonli tahlili (app/services/analytics.py).

Barcha shaxsiy ma'lumotlar SOXTA."""

import io
from datetime import date, datetime, time, timedelta, timezone

import openpyxl
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import AttendanceRecord, Building, Camera, Event, Faculty, LessonSession, StudentStaff
from app.services import analytics
from app.services.analytics import AnalyticsRangeError, build_analytics, previous_range, range_label, validate_range
from tests.conftest import auth_headers

DAY = date(2026, 9, 14)  # dushanba
TASHKENT_OFFSET = timedelta(hours=5)


pytestmark = pytest.mark.six_am_day


def local_moment(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=timezone.utc) - TASHKENT_OFFSET


@pytest.fixture(autouse=True)
def _no_cache():
    analytics.reset_cache_for_tests()
    yield
    analytics.reset_cache_for_tests()


@pytest.fixture
async def world(db_session, seeded):
    faculty = (await db_session.execute(select(Faculty).where(Faculty.name == "Davolash ishi"))).scalar_one()
    building = (await db_session.execute(select(Building))).scalars().first()
    camera = Camera(
        name="Kirish-Sinov", ip="10.7.7.7", building_id=building.id, zone="Kirish", resolution="1080p",
        status="faol", last_seen_at=datetime.now(timezone.utc),
    )
    staff = [
        StudentStaff(full_name=f"Soxtaov Xodim {i}", type="xodim", faculty_id=faculty.id,
                     group_or_position="Anatomiya kafedrasi", biometrics_status="tasdiqlangan")
        for i in range(4)
    ]
    student = StudentStaff(full_name="Soxtaova Talaba", type="talaba", faculty_id=faculty.id,
                           group_or_position="1-kurs, DI-1", biometrics_status="yoq")
    db_session.add_all([camera, student, *staff])
    await db_session.commit()
    return {"camera": camera, "staff": staff, "student": student, "building": building}


def event(camera, when, *, severity="past", status="yangi", module_code=17):
    return Event(
        occurred_at=when, camera_id=camera.id, camera_name=camera.name, building="1-bino",
        module_code=module_code, module_name=f"Modul {module_code}", group="D",
        confidence=60, severity=severity, status=status,
    )


class TestRanges:
    def test_validation(self):
        with pytest.raises(AnalyticsRangeError):
            validate_range(date(2026, 9, 2), date(2026, 9, 1))
        with pytest.raises(AnalyticsRangeError):
            validate_range(date(2026, 1, 1), date(2026, 1, 1) + timedelta(days=92))
        validate_range(date(2026, 1, 1), date(2026, 1, 1) + timedelta(days=91))

    def test_previous_period_has_equal_length(self):
        assert previous_range(date(2026, 9, 8), date(2026, 9, 14)) == (date(2026, 9, 1), date(2026, 9, 7))
        assert previous_range(DAY, DAY) == (date(2026, 9, 13), date(2026, 9, 13))

    def test_labels(self):
        assert range_label(DAY, DAY) == "14-sentabr, 2026"
        assert range_label(date(2026, 9, 1), date(2026, 9, 15)) == "1–15-sentabr, 2026"
        assert range_label(date(2026, 8, 28), date(2026, 9, 3)) == "28-avgust – 3-sentabr, 2026"


class TestAttendance:
    async def test_staff_rates_lateness_arrival_and_previous_period(self, db_session, world):
        s = world["staff"]
        db_session.add_all([
            AttendanceRecord(student_staff_id=s[0].id, date=DAY, status="keldi", check_in=time(8, 10)),
            AttendanceRecord(student_staff_id=s[1].id, date=DAY, status="keldi", check_in=time(8, 40)),
            AttendanceRecord(student_staff_id=s[2].id, date=DAY, status="kech_keldi", check_in=time(9, 20)),
            AttendanceRecord(student_staff_id=s[3].id, date=DAY, status="kelmadi"),
            # oldingi davr (13-sentabr): hamma kelgan
            AttendanceRecord(student_staff_id=s[0].id, date=DAY - timedelta(days=1), status="keldi", check_in=time(8, 0)),
        ])
        await db_session.commit()

        a = await build_analytics(db_session, DAY, DAY)
        staff = a.attendance.staff
        assert (staff.records, staff.present, staff.late, staff.absent) == (4, 3, 1, 1)
        assert staff.rate == 75.0
        assert staff.late_share == 33.3
        assert staff.avg_arrival == "08:43"  # (490 + 520 + 560) / 3 daqiqa
        assert staff.by_day[0].keldi == 2 and staff.by_day[0].kech_keldi == 1 and staff.by_day[0].kelmadi == 1
        assert staff.by_faculty[0].name == "Davolash ishi" and staff.by_faculty[0].rate == 75.0
        hist = {b.label: b.count for b in staff.arrival_histogram}
        assert hist["08:00"] == 1 and hist["08:30"] == 1 and hist["09:15"] == 1

        # Namuna kichik — foiz bor, lekin ishonchsiz deb belgilanadi.
        assert staff.reliability.reliable is False
        kpi = next(k for k in a.kpis if k.key == "staff_attendance")
        assert kpi.display == "75.0%"
        assert kpi.previous == 100.0 and kpi.delta == -25.0 and kpi.delta_display == "−25.0 f.p."
        assert kpi.reliable is False and kpi.note

    async def test_missing_records_are_not_zero(self, db_session, world):
        a = await build_analytics(db_session, DAY, DAY)
        students = a.attendance.students
        assert students.records == 0 and students.rate is None
        assert students.population == 1 and students.enrolled == 0
        kpi = next(k for k in a.kpis if k.key == "staff_attendance")
        assert kpi.value is None and kpi.display == "—" and kpi.delta is None


class TestSecurity:
    async def test_local_days_heatmap_and_night(self, db_session, world):
        camera = world["camera"]
        db_session.add_all([
            event(camera, local_moment(DAY, 22, 0), severity="yuqori"),           # kechasi, dushanba 22:00
            event(camera, local_moment(DAY, 14, 0), status="tasdiqlangan"),       # dushanba 14:00
            event(camera, local_moment(DAY - timedelta(days=1), 23, 30)),         # oldingi kun — kirmaydi
            event(camera, local_moment(DAY, 5, 30)),                              # 05:30 — hali oldingi ish kuni
        ])
        await db_session.commit()

        s = (await build_analytics(db_session, DAY, DAY)).security
        assert s.total == 2
        assert (s.by_day[0].yuqori, s.by_day[0].past) == (1, 1)
        assert s.serious == 1
        assert s.heatmap[0][22] == 1 and s.heatmap[0][14] == 1 and s.heatmap_max == 1
        assert s.night == 1
        assert s.top_cameras[0].name == "Kirish-Sinov" and s.top_cameras[0].share == 100.0

    async def test_module_precision_needs_enough_reviews(self, db_session, world):
        camera = world["camera"]
        db_session.add_all(
            [event(camera, local_moment(DAY, 10), status="tasdiqlangan", module_code=15) for _ in range(9)]
            + [event(camera, local_moment(DAY, 11), status="rad_etilgan", module_code=15)]
            + [event(camera, local_moment(DAY, 12), status="tasdiqlangan", module_code=14)]
        )
        await db_session.commit()

        s = (await build_analytics(db_session, DAY, DAY)).security
        modules = {m.code: m for m in s.top_modules}
        assert modules[15].precision == 90.0 and modules[15].count == 10
        assert modules[14].precision is None  # bitta ko'rib chiqilgan signal — foiz emas
        assert s.precision == 90.9


class TestLessonsAndSystem:
    async def test_unanalyzed_lessons_do_not_drag_attention_down(self, db_session, world):
        common = dict(date=DAY, group_name="DI-1", faculty="Davolash ishi", teacher="Soxtaov O.", subject="Anatomiya")
        db_session.add_all([
            LessonSession(**common, attention_score=80, attention_samples=4, sleep_incidents=2,
                          teacher_activity_score=70, activity_samples=4,
                          teacher_on_time=True, punctuality_checked_at=datetime.now(timezone.utc)),
            # Import qilingan, hali o'tmagan dars: soxta 50% endi hisobga kirmaydi.
            LessonSession(**common, attention_score=50, sleep_incidents=0, teacher_activity_score=50),
            # Kadr olinmay yopilgan: tekshirilgan hisoblanmaydi.
            LessonSession(**common, attention_score=0, sleep_incidents=0, teacher_activity_score=0,
                          punctuality_checked_at=datetime.now(timezone.utc)),
        ])
        await db_session.commit()

        a = await build_analytics(db_session, DAY, DAY)
        assert a.lessons.sessions == 3 and a.lessons.analyzed_sessions == 1
        assert a.lessons.avg_attention == 80.0
        assert a.lessons.avg_teacher_activity == 70.0
        assert a.lessons.sleep_incidents == 2
        assert a.lessons.checked_sessions == 1
        assert a.lessons.teacher_on_time_rate == 100.0

        system = a.system
        assert system.cameras_active >= 1 and system.cameras_live >= 1
        coverage = {c.type: c for c in system.coverage}
        assert coverage["xodim"].percent == 100.0
        assert coverage["talaba"].percent == 0.0
        assert any(i.title == "Talabalar davomati to'liq emas" for i in a.insights)


class TestEndpoints:
    async def test_analytics_endpoint_shape_and_validation(self, client: AsyncClient, world):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get("/api/reports/analytics", params={"from": "2026-09-14", "to": "2026-09-14"}, headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["period"]["label"] == "14-sentabr, 2026"
        assert body["previousPeriod"]["start"] == "2026-09-13"
        assert len(body["kpis"]) == 6
        assert "byDay" in body["attendance"]["staff"] and "kechKeldi" in body["attendance"]["staff"]["byDay"][0]
        assert len(body["security"]["heatmap"]) == 7

        bad = await client.get("/api/reports/analytics", params={"from": "2026-09-15", "to": "2026-09-14"}, headers=headers)
        assert bad.status_code == 422

    async def test_save_list_and_open_archived_report(self, client: AsyncClient, world):
        headers = await auth_headers(client, "admin", "admin123")
        saved = await client.post("/api/reports", json={"from": "2026-09-08", "to": "2026-09-14"}, headers=headers)
        assert saved.status_code == 201, saved.text
        body = saved.json()
        assert body["hasAnalytics"] is True
        assert body["period"] == "Haftalik"
        assert body["rangeStart"] == "2026-09-08" and body["rangeEnd"] == "2026-09-14"
        assert body["createdBy"]
        assert body["analytics"]["period"]["days"] == 7

        listed = (await client.get("/api/reports", headers=headers)).json()
        item = listed["items"][0]
        assert len(item["kpis"]) == 6
        assert "analytics" not in item

        opened = (await client.get(f"/api/reports/{body['id']}", headers=headers)).json()
        assert opened["analytics"]["period"]["start"] == "2026-09-08"

        assert (await client.get("/api/reports/not-a-uuid", headers=headers)).status_code == 404

    async def test_excel_export(self, client: AsyncClient, world):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get("/api/reports/analytics.xlsx", params={"from": "2026-09-14", "to": "2026-09-14"}, headers=headers)
        assert resp.status_code == 200
        workbook = openpyxl.load_workbook(io.BytesIO(resp.content))
        assert workbook.sheetnames == ["Xulosa", "Davomat", "Xavfsizlik", "Darslar", "Tizim"]
