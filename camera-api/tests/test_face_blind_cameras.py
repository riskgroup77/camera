"""Yuzi tanib bo'lmaydigan kameralarni yuz sweepidan chiqarish.

Productionda o'lchandi (2026-09-16): 107 kameraning taxminan yarmida yuz
balandligi 8-20 piksel — chegara esa 40. Bunday kadrda hech kim
tanilmaydi, lekin har aylanishda kadr olinadi va model chaqiriladi; shu
bilan birga HAQIQATAN yuz ko'rinadigan kirish kameralari navbatda
kutadi. Bu testlar qarorning to'g'ri va QAYTARILADIGAN bo'lishini
himoya qiladi: bir marta tanigan kamera hech qachon o'chirilmaydi va
o'chirilgani ham vaqti-vaqti bilan qayta tekshiriladi.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.config import settings
from app.jobs import unified_face_sweep
from app.models import Building, Camera
from app.services import recognition_stats

CAMERA_ID = "00000000-0000-0000-0000-0000000000aa"


def _face(height_px: int) -> SimpleNamespace:
    return SimpleNamespace(bbox=[0, 0, height_px, height_px], embedding=None)


def _graded(count: int):
    return [SimpleNamespace(similarity=0.2, person_id=None, grade="none") for _ in range(count)]


def _see_faces(camera_id: str, *, height_px: int, count: int) -> None:
    """`count` ta yuzni bittadan kadrda ko'rgan qilib qayd etadi."""
    for _ in range(count):
        faces = [_face(height_px)]
        recognition_stats.record_frame(camera_id, faces, _graded(1))


@pytest.fixture(autouse=True)
def _clean_stats():
    recognition_stats.reset_for_tests()
    unified_face_sweep.reset_sweep_round_for_tests()
    yield
    recognition_stats.reset_for_tests()
    unified_face_sweep.reset_sweep_round_for_tests()


class TestIsFaceBlind:
    def test_a_camera_with_too_few_faces_is_not_judged_yet(self):
        _see_faces(CAMERA_ID, height_px=10, count=settings.face_blind_min_faces - 1)
        assert recognition_stats.is_face_blind(CAMERA_ID) is False

    def test_many_tiny_faces_and_no_matches_means_blind(self):
        _see_faces(CAMERA_ID, height_px=10, count=settings.face_blind_min_faces)
        assert recognition_stats.is_face_blind(CAMERA_ID) is True

    def test_normal_sized_faces_are_never_blind(self):
        _see_faces(CAMERA_ID, height_px=80, count=settings.face_blind_min_faces * 2)
        assert recognition_stats.is_face_blind(CAMERA_ID) is False

    def test_one_recognised_person_keeps_the_camera_in(self):
        """Tanigan kamera o'chirilmaydi — hatto qolgan hamma yuzi kichik
        bo'lsa ham: u yerda odam tanish AMALDA ishlagan."""
        _see_faces(CAMERA_ID, height_px=10, count=settings.face_blind_min_faces)
        recognition_stats.record_credit(CAMERA_ID, "strict")
        assert recognition_stats.is_face_blind(CAMERA_ID) is False

    def test_a_pending_relaxed_sighting_also_keeps_it_in(self):
        _see_faces(CAMERA_ID, height_px=10, count=settings.face_blind_min_faces)
        recognition_stats.record_credit(CAMERA_ID, "relaxed_pending")
        assert recognition_stats.is_face_blind(CAMERA_ID) is False

    def test_the_setting_can_turn_the_whole_rule_off(self, monkeypatch):
        _see_faces(CAMERA_ID, height_px=10, count=settings.face_blind_min_faces)
        monkeypatch.setattr(settings, "face_blind_skip_enabled", False)
        assert recognition_stats.is_face_blind(CAMERA_ID) is False


@pytest.mark.usefixtures("seeded")
class TestSweepSkipsBlindCameras:
    @pytest.fixture
    async def cameras(self, db_session):
        building = (await db_session.execute(select(Building))).scalars().first()
        rows = [
            Camera(
                name=name,
                ip=ip,
                building_id=building.id,
                zone="Zona",
                resolution="1080p",
                status="faol",
                stream_url=f"http://mediamtx/{ip}/index.m3u8",
                last_seen_at=datetime.now(timezone.utc),
                **roles,
            )
            # Uyqu faqat auditoriyada, begona shaxs kirishda ishlaydi
            # (app/services/camera_roles.py) — rolsiz kamera sweepga tushmaydi.
            for name, ip, roles in (
                ("Kirish", "10.8.0.1", {"is_entrance": True}),
                ("Katta auditoriya", "10.8.0.2", {"room_type": "auditoriya"}),
            )
        ]
        db_session.add_all(rows)
        await db_session.commit()
        for row in rows:
            await db_session.refresh(row, attribute_names=["building"])
        return rows

    async def _swept_names(self, monkeypatch, session_factory) -> list[str]:
        swept: list[str] = []

        async def fake_process(camera, flags, candidates, factory):
            swept.append(camera.name)
            return {"unauthorized": 0, "sleep": 0}

        monkeypatch.setattr(unified_face_sweep, "_process_camera", fake_process)
        await unified_face_sweep.run_unified_face_sweep_once(session_factory=session_factory)
        return swept

    async def test_blind_camera_is_skipped_but_rechecked_later(self, cameras, monkeypatch, db_session):
        from tests.conftest import TestSessionLocal

        entrance, hall = cameras
        _see_faces(str(hall.id), height_px=10, count=settings.face_blind_min_faces)
        monkeypatch.setattr(settings, "face_blind_recheck_every", 3)

        first = await self._swept_names(monkeypatch, TestSessionLocal)
        assert entrance.name in first
        assert hall.name not in first  # birinchi aylanishda tashlab ketildi

        # Uchinchi aylanishda qayta tekshiriladi (kamera burilgan yoki
        # yaqinlashtirilgan bo'lishi mumkin).
        await self._swept_names(monkeypatch, TestSessionLocal)
        third = await self._swept_names(monkeypatch, TestSessionLocal)
        assert hall.name in third

    async def _sleep_flags(self, monkeypatch, session_factory) -> dict[str, bool]:
        seen: dict[str, bool] = {}

        async def fake_process(camera, flags, candidates, factory):
            seen[camera.name] = flags["sleep"]
            return {"unauthorized": 0, "sleep": 0}

        monkeypatch.setattr(unified_face_sweep, "_process_camera", fake_process)
        await unified_face_sweep.run_unified_face_sweep_once(session_factory=session_factory)
        return seen

    async def test_sleep_runs_only_while_a_lesson_is_on(self, cameras, monkeypatch, db_session):
        """Uyqu (#20) bo'sh auditoriyada tekshirilmaydi — faqat jadvaldagi
        dars davom etayotgan kamerada."""
        from datetime import timedelta

        from app.models import AIModuleConfig, LessonSession
        from app.timezone import local_now
        from tests.conftest import TestSessionLocal

        sleep_module = (await db_session.execute(select(AIModuleConfig).where(AIModuleConfig.code == 20))).scalar_one()
        sleep_module.active = True
        await db_session.commit()
        monkeypatch.setattr(settings, "sleep_only_during_lessons", True)
        _, hall = cameras

        assert (await self._sleep_flags(monkeypatch, TestSessionLocal)).get(hall.name) is False

        db_session.add(
            LessonSession(
                date=local_now().date(), group_name="1-guruh", faculty="Davolash ishi", teacher="O'qituvchi",
                subject="Anatomiya", attention_score=50, teacher_activity_score=50, teacher_on_time=True,
                camera_id=hall.id, scheduled_start_time=local_now() - timedelta(minutes=10),
            )
        )
        await db_session.commit()
        assert (await self._sleep_flags(monkeypatch, TestSessionLocal))[hall.name] is True
