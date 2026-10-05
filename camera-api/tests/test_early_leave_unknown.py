""""Erta ketdi" — bitta qoida, va "aniqlanmadi" degan halol javob.

Productionda (2026-09-20) hisobot 64 qatordan 54 tasini (84%) "erta ketdi"
deb ko'rsatardi. Sabab: uch xil hisob bor edi va hisobotdagi eng yumshog'i
faqat "check_out ish tugashidan oldin" deb qarardi. check_out esa endi
ISTALGAN kameradagi oxirgi ko'rinish, kamera qoplamasi siyrak — ya'ni
"10:12 da ketdi" emas, "10:12 dan keyin hech bir kamera ko'rmadi".

Bu yerda tekshiriladi: (1) qoida bitta joyda va ikkala chaqiruvchi bir xil
javob beradi, (2) dalil yetmasa javob "aniqlanmadi" va hisobotda shu son
ko'rinadi — jim turib "erta ketmadi" deb yozilmaydi.
"""

from datetime import datetime, time, timedelta

import pytest
from httpx import AsyncClient

from app.models import PresenceVisit
from app.routers.attendance import _is_early_leave
from app.services.attendance_policy import (
    EARLY_NA,
    EARLY_NO,
    EARLY_UNKNOWN,
    EARLY_YES,
    Policy,
    early_leave_verdict,
)
from app.timezone import INSTITUTE_TZ
from tests.conftest import auth_headers
from tests.situation_world import _record, _situation_settings, world  # noqa: F401 — pytest fikstura

PAST_DAY = datetime(2026, 8, 3).date()  # dushanba
RULE = Policy()
NOW = datetime(2026, 8, 10, 18, 0, tzinfo=INSTITUTE_TZ)


def _verdict(check_in, check_out, last_seen=None, sightings=None, status="keldi"):
    return early_leave_verdict(
        status=status, day=PAST_DAY,
        check_in=time.fromisoformat(check_in) if check_in else None,
        check_out=time.fromisoformat(check_out) if check_out else None,
        last_seen=time.fromisoformat(last_seen) if last_seen else None,
        sightings=sightings, policy=RULE, now=NOW,
    )


class TestSharedRule:
    def test_sparse_sightings_are_unknown_not_early(self):
        """Productiondagi odatiy qator: odam 09:00 da ko'rindi, 10:12 da yana
        bir marta — va boshqa hech qayerda. Bu "erta ketdi" emas."""
        assert _verdict("09:00", "10:12", last_seen="10:12", sightings=1) == EARLY_UNKNOWN

    def test_no_sighting_history_at_all_is_unknown(self):
        assert _verdict("08:00", "14:30", last_seen="14:30") == EARLY_UNKNOWN

    def test_a_short_stay_is_unknown(self):
        """Ikki ko'rinish, lekin orasi 5 daqiqa — kamera uni yo'qotgan."""
        assert _verdict("09:00", "09:05", last_seen="09:05", sightings=2) == EARLY_UNKNOWN

    def test_tracked_day_ending_before_work_end_is_early(self):
        assert _verdict("08:00", "14:30", last_seen="14:30", sightings=8) == EARLY_YES

    def test_seen_after_the_exit_is_not_early(self):
        assert _verdict("08:00", "12:00", last_seen="15:30", sightings=8) == EARLY_NO

    def test_staying_until_work_end_is_not_early(self):
        assert _verdict("08:00", "17:05", last_seen="17:05", sightings=8) == EARLY_NO

    def test_absent_and_weekend_days_are_not_judged(self):
        assert _verdict("08:00", "14:30", sightings=8, status="kelmadi") == EARLY_NA
        assert early_leave_verdict(
            status="keldi", day=datetime(2026, 8, 9).date(),  # yakshanba
            check_in=time(8, 0), check_out=time(14, 30), last_seen=time(14, 30),
            sightings=8, policy=RULE, now=NOW,
        ) == EARLY_NA

    def test_person_card_and_the_rule_agree(self):
        """Odam kartasi (app/routers/attendance.py) alohida qoida yuritmaydi."""
        record = _record(type("P", (), {"id": None})(), PAST_DAY, "keldi", "09:00", "10:12")
        assert _is_early_leave(record, time(10, 12), sightings=1, now=NOW) is False
        assert _is_early_leave(record, time(10, 12), sightings=9, now=NOW) is True


@pytest.fixture
async def admin(client: AsyncClient, world):
    return await auth_headers(client, "operator", "operator123")


def _tile(body: dict, label: str):
    return next(t for t in body["tiles"] if t["label"] == label)


@pytest.mark.usefixtures("world")
class TestReportShowsTheUnknownCount:
    async def test_a_sparsely_seen_day_is_counted_as_unknown(self, client, admin, world, db_session):
        """Bir kun, ikki xodim: biri kuzatilgan (erta ketdi), ikkinchisi
        kamerada bir marta ko'ringan (aniqlanmadi). Hisobot ikkovini ham
        "erta ketdi" deb ko'rsatmasligi va noma'lumni yashirmasligi kerak."""
        today = world.today
        monday = today - timedelta(days=today.weekday() + 7)
        people = world.people

        db_session.add(_record(people.rahimov, monday, "keldi", "07:50", "15:00"))
        db_session.add(
            PresenceVisit(
                student_staff_id=people.rahimov.id,
                first_seen_at=datetime.combine(monday, time(7, 50), tzinfo=INSTITUTE_TZ),
                last_seen_at=datetime.combine(monday, time(15, 0), tzinfo=INSTITUTE_TZ),
                sightings=9,
            )
        )
        db_session.add(_record(people.karimov, monday, "keldi", "09:00", "10:12"))
        db_session.add(
            PresenceVisit(
                student_staff_id=people.karimov.id,
                first_seen_at=datetime.combine(monday, time(10, 12), tzinfo=INSTITUTE_TZ),
                last_seen_at=datetime.combine(monday, time(10, 12), tzinfo=INSTITUTE_TZ),
                sightings=1,
            )
        )
        await db_session.commit()

        res = await client.get(
            "/api/hisobot/report",
            params={"kind": "xodim", "criterion": "erta_ketish",
                    "from": monday.isoformat(), "to": monday.isoformat()},
            headers=admin,
        )
        assert res.status_code == 200, res.text
        body = res.json()["report"]

        assert _tile(body, "Erta ketish holatlari")["value"] == 1
        assert _tile(body, "Aniqlab bo'lmadi")["value"] == 1, (
            "bir marta ko'ringan odam 'erta ketdi' ham, 'vaqtida ketdi' ham emas"
        )
        assert _tile(body, "Hukm chiqarilgan kunlar")["value"] == 1
        names = [p["full_name"] for p in body["people"]]
        assert names == ["Rahimov Bobur"], "aniqlanmagan kun ayblov ro'yxatiga tushmaydi"
        assert "aniqlanmadi" in " ".join(body["summary"]) or "baholab bo'lmadi" in " ".join(body["summary"])
        assert body.get("note") and "baholab bo'lmadi" in body["note"]


class TestManualRecordIsEvidence:
    """Vaqtni odam yozgan bo'lsa, kamera ko'rinishlari bo'yicha
    "dalil yetarli emas" deyish operatorning yozganini bekor qilish bo'lardi."""

    def test_manual_check_out_is_trusted_without_sightings(self):
        from datetime import date, datetime, time

        from app.services.attendance_policy import EARLY_YES, Policy, early_leave_verdict

        verdict = early_leave_verdict(
            status="keldi", day=date(2026, 8, 3), check_in=time(8, 0), check_out=time(14, 30),
            last_seen=None, sightings=None, source="qolda", policy=Policy(),
            now=datetime(2026, 8, 4, 9, 0),
        )
        assert verdict == EARLY_YES

    def test_camera_record_without_sightings_stays_unknown(self):
        from datetime import date, datetime, time

        from app.services.attendance_policy import EARLY_UNKNOWN, Policy, early_leave_verdict

        verdict = early_leave_verdict(
            status="keldi", day=date(2026, 8, 3), check_in=time(8, 0), check_out=time(14, 30),
            last_seen=None, sightings=None, source="kamera", policy=Policy(),
            now=datetime(2026, 8, 4, 9, 0),
        )
        assert verdict == EARLY_UNKNOWN
