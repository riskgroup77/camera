"""Dars jadvali importi: xona raqami -> kamera, o'qituvchi ismi -> xodim,
fakultet guruhdan, oldindan ko'rish, Excel — app/services/lesson_import.py."""

import io

import pytest
from httpx import AsyncClient
from openpyxl import Workbook
from sqlalchemy import select

from app.models import Building, Camera, Faculty, LessonSession, StudentStaff
from app.timezone import INSTITUTE_TZ
from tests.conftest import auth_headers


@pytest.fixture
async def world(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    faculty = (await db_session.execute(select(Faculty).where(Faculty.name == "Davolash ishi"))).scalar_one()
    room = Camera(name="211-xona", ip="10.8.0.1", building_id=building.id, zone="Z", resolution="1080p",
                  status="faol", room_type="auditoriya", room_code="211")
    teacher = StudentStaff(full_name="Saloxiddinov Akmal Qaxorovich", type="xodim", group_or_position="Kafedra")
    student = StudentStaff(full_name="Aziz Karimov", type="talaba", group_or_position="2-kurs, DI-1625",
                           faculty_id=faculty.id)
    db_session.add_all([room, teacher, student])
    await db_session.commit()
    return {"room": room, "teacher": teacher}


def _csv(text: str) -> dict:
    return {"file": ("jadval.csv", text.encode("utf-8"), "text/csv")}


async def _post(client: AsyncClient, files: dict, apply: bool) -> dict:
    headers = await auth_headers(client, "admin", "admin123")
    resp = await client.post(f"/api/lesson-sessions/import?apply={str(apply).lower()}", headers=headers, files=files)
    assert resp.status_code == 200
    return resp.json()


UZBEK_CSV = (
    "sana;guruh;fan;xona;o'qituvchi;boshlanish\n"
    "21.09.2026;DI-1625;Anatomiya;Aud. 211;Salohiddinov Akmal Koxorovich;08:30-09:50\n"
    "21.09.2026;DI-1625;Fiziologiya;305;Noma'lum Odam;10:00\n"
)


class TestImport:
    async def test_preview_links_rooms_and_teachers_and_writes_nothing(self, client, db_session, world):
        result = await _post(client, _csv(UZBEK_CSV), apply=False)

        assert result["preview"] is True and result["errors"] == []
        assert (result["imported"], result["withCamera"], result["withTeacher"]) == (2, 1, 1)
        first = result["rows"][0]
        assert (first["camera"], first["teacher"], first["teacherMatched"], first["start"]) == (
            "211-xona", "Saloxiddinov Akmal Qaxorovich", True, "08:30",
        )
        assert result["unmatchedRooms"] == ["305"]
        assert result["unmatchedTeachers"] == ["Noma'lum Odam"]
        assert (await db_session.execute(select(LessonSession))).scalars().all() == []

    async def test_apply_creates_linked_lessons_and_a_rerun_skips_them(self, client, db_session, world):
        await _post(client, _csv(UZBEK_CSV), apply=True)
        lessons = (await db_session.execute(select(LessonSession).order_by(LessonSession.subject))).scalars().all()
        anatomy = lessons[0]
        assert anatomy.camera_id == world["room"].id
        assert anatomy.teacher_id == world["teacher"].id
        # Fakultet ustuni yo'q — guruh talabalaridan olindi.
        assert anatomy.faculty == "Davolash ishi"
        local = anatomy.scheduled_start_time.astimezone(INSTITUTE_TZ)
        assert (local.date().isoformat(), local.hour, local.minute) == ("2026-09-21", 8, 30)
        assert lessons[1].camera_id is None and lessons[1].teacher == "Noma'lum Odam"

        again = await _post(client, _csv(UZBEK_CSV), apply=True)
        assert (again["imported"], again["skipped"]) == (0, 2)

    async def test_same_subject_twice_a_day_at_different_times_is_two_lessons(self, client, db_session, world):
        text = (
            "date,group,faculty,subject,start\n"
            "2026-09-22,DI-1625,Davolash ishi,Anatomiya,08:30\n"
            "2026-09-22,DI-1625,Davolash ishi,Anatomiya,10:00\n"
        )
        result = await _post(client, _csv(text), apply=True)
        assert result["imported"] == 2

    async def test_unknown_group_without_faculty_is_an_error(self, client, db_session, world):
        result = await _post(client, _csv("sana,guruh,fan\n2026-09-21,XX-0000,Fan\n"), apply=False)
        assert result["imported"] == 0 and "aniqlanmadi" in result["errors"][0]["message"]

    async def test_excel_file(self, client, db_session, world):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Sana", "Guruh", "Fan", "Xona", "O'qituvchi"])
        sheet.append(["2026-09-23", "DI-1625", "Gistologiya", 211, "Saloxiddinov Akmal Qaxorovich"])
        buffer = io.BytesIO()
        workbook.save(buffer)
        files = {"file": ("jadval.xlsx", buffer.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}

        result = await _post(client, files, apply=False)
        assert result["errors"] == []
        assert (result["withCamera"], result["withTeacher"]) == (1, 1)


# ─────────────────────────────── Haftalik jadval (namuna + yoyish)

WEEKLY_CSV = (
    "guruh;hafta kuni;boshlanish;xona;fan;o'qituvchi\n"
    "DI-1625;Seshanba;08:30;211;Anatomiya;Salohiddinov Akmal Koxorovich\n"
    "DI-1625;Juma;10:00;305;Fiziologiya;\n"
)


async def _post_weekly(client: AsyncClient, text: str, *, dan: str, gacha: str, apply: bool) -> dict:
    headers = await auth_headers(client, "admin", "admin123")
    resp = await client.post(
        f"/api/lesson-sessions/import-haftalik?dan={dan}&gacha={gacha}&apply={str(apply).lower()}",
        headers=headers,
        files={"file": ("haftalik.csv", text.encode("utf-8"), "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_weekly_schedule_is_expanded_over_the_period(client: AsyncClient, world, db_session):
    """Bitta haftalik qator — oraliqdagi har bir shu kunga bitta dars."""
    body = await _post_weekly(client, WEEKLY_CSV, dan="2026-09-01", gacha="2026-09-30", apply=True)

    # Sentabr 2026: 5 ta seshanba, 4 ta juma.
    assert body["imported"] == 9
    assert body["weeks"] == 5
    # Xonasi bor dars kameraga bog'lanadi, 305 esa yo'q — ochiq aytiladi.
    assert body["withCamera"] == 5
    assert body["unmatchedRooms"] == ["305"]

    sessions = (await db_session.execute(select(LessonSession))).scalars().all()
    dates = sorted({s.date.isoformat() for s in sessions})
    assert dates[0] == "2026-09-01"
    assert dates[-1] == "2026-09-29"


async def test_weekly_preview_writes_nothing(client: AsyncClient, world, db_session):
    body = await _post_weekly(client, WEEKLY_CSV, dan="2026-09-01", gacha="2026-09-07", apply=False)
    assert body["preview"] is True and body["imported"] == 2
    assert (await db_session.execute(select(LessonSession))).scalars().first() is None


async def test_weekly_repeat_upload_does_not_duplicate(client: AsyncClient, world):
    await _post_weekly(client, WEEKLY_CSV, dan="2026-09-01", gacha="2026-09-07", apply=True)
    again = await _post_weekly(client, WEEKLY_CSV, dan="2026-09-01", gacha="2026-09-07", apply=True)
    assert again["imported"] == 0 and again["skipped"] == 2


async def test_weekly_bad_range_is_refused(client: AsyncClient, world):
    headers = await auth_headers(client, "admin", "admin123")
    resp = await client.post(
        "/api/lesson-sessions/import-haftalik?dan=2026-10-01&gacha=2026-09-01",
        headers=headers,
        files={"file": ("h.csv", WEEKLY_CSV.encode("utf-8"), "text/csv")},
    )
    assert resp.status_code == 422


async def test_weekly_without_weekday_column_says_so(client: AsyncClient, world):
    headers = await auth_headers(client, "admin", "admin123")
    resp = await client.post(
        "/api/lesson-sessions/import-haftalik?dan=2026-09-01&gacha=2026-09-07",
        headers=headers,
        files={"file": ("h.csv", b"guruh;boshlanish\nDI-1625;08:30\n", "text/csv")},
    )
    assert resp.status_code == 422
    assert "Hafta kuni" in resp.json()["detail"]


async def test_template_download_lists_real_groups_and_rooms(client: AsyncClient, world):
    headers = await auth_headers(client, "admin", "admin123")
    resp = await client.get("/api/lesson-sessions/namuna.xlsx", headers=headers)
    assert resp.status_code == 200
    assert "namuna.xlsx" in resp.headers["content-disposition"]

    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(resp.content))
    rooms = [wb["Xonalar"].cell(row, 1).value for row in range(2, wb["Xonalar"].max_row + 1)]
    assert "211" in rooms
