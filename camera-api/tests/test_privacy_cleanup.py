"""Saqlash muddati: faol emas odamning biometrikasi, hodisa suratlari,
turniket qaydlari va bildirishnoma jurnali (app/jobs/cleanup.py).

Obyekt ombori soxta: qaysi kalitlar o'chirilgani yoziladi.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.jobs import cleanup
from app.jobs.cleanup import run_cleanup_once
from app.models import AccessEvent, Event, FaceGalleryEmbedding, NotificationLog, StudentStaff, UnknownSighting
from app.services.face_matching import load_candidate_matrix_cached

EMBEDDING = json.dumps([0.1] * 512)


@pytest.fixture(autouse=True)
def fake_storage(monkeypatch):
    """quiet — delete_files_quietly (biometrika, hodisa bilan birga ketgan
    surat); single — delete_file (surat muddati, har kalit alohida)."""
    calls = {"quiet": [], "single": [], "fail": set()}

    async def delete_quietly(keys):
        collected = [k for k in keys if k]
        calls["quiet"].extend(collected)
        return len(collected)

    def delete_file(key):
        if key in calls["fail"]:
            raise RuntimeError("ombor javob bermadi")
        calls["single"].append(key)

    monkeypatch.setattr(cleanup, "delete_files_quietly", delete_quietly)
    monkeypatch.setattr(cleanup, "delete_file", delete_file)
    return calls


def _person(**overrides) -> StudentStaff:
    values = {
        "full_name": "Odam",
        "type": "talaba",
        "group_or_position": "DI-101",
        "biometrics_status": "tasdiqlangan",
        "biometric_embedding": EMBEDDING,
        "biometric_photo_key": "biometrics/odam.jpg",
    }
    values.update(overrides)
    return StudentStaff(**values)


def _event(occurred_at: datetime, snapshot_key: str | None) -> Event:
    return Event(
        camera_name="Kamera", building="Bino", module_code=1, module_name="Test", group="A", confidence=70,
        severity="past", status="yangi", occurred_at=occurred_at, snapshot_key=snapshot_key,
    )


@pytest.mark.usefixtures("seeded")
class TestBiometricRetention:
    async def test_purges_only_people_inactive_past_the_window(self, db_session, fake_storage):
        now = datetime.now(timezone.utc)
        days = settings.biometric_retention_days_after_inactive
        expired = _person(
            full_name="Ketgan", active=False, deactivated_at=now - timedelta(days=days + 1),
            biometric_photo_key="biometrics/ketgan.jpg",
        )
        recent = _person(
            full_name="Yaqinda ketgan", active=False, deactivated_at=now - timedelta(days=days - 1),
            biometric_photo_key="biometrics/yaqinda.jpg",
        )
        active = _person(full_name="Faol", biometric_photo_key="biometrics/faol.jpg")
        db_session.add_all([expired, recent, active])
        await db_session.commit()

        counts = await run_cleanup_once(db_session)

        assert counts["biometrics_purged"] == 1
        assert fake_storage["quiet"] == ["biometrics/ketgan.jpg"]
        for person in (expired, recent, active):
            await db_session.refresh(person)
        assert expired.biometric_embedding is None
        assert expired.biometric_photo_key is None
        assert expired.biometrics_status == "yoq"
        # Yozuvning o'zi qoladi — faqat biometrika ketadi.
        assert expired.full_name == "Ketgan"
        assert recent.biometric_embedding is not None
        assert active.biometric_embedding is not None

    async def test_purge_also_removes_gallery_samples_and_linked_crops(self, db_session, fake_storage):
        now = datetime.now(timezone.utc)
        days = settings.biometric_retention_days_after_inactive
        person = _person(active=False, deactivated_at=now - timedelta(days=days + 1))
        db_session.add(person)
        await db_session.commit()
        db_session.add_all([
            FaceGalleryEmbedding(
                student_staff_id=person.id, embedding=EMBEDDING, anchor_hash="h" * 64, similarity=0.6, face_px=80
            ),
            UnknownSighting(
                day=now.date(), first_seen_at=now, last_seen_at=now, embedding=EMBEDDING,
                crop_key="unknown/odam.jpg", status="talaba", person_id=person.id,
            ),
        ])
        await db_session.commit()

        await run_cleanup_once(db_session)

        assert sorted(fake_storage["quiet"]) == ["biometrics/odam.jpg", "unknown/odam.jpg"]
        left = await db_session.execute(select(func.count()).select_from(FaceGalleryEmbedding))
        assert left.scalar_one() == 0
        left = await db_session.execute(select(func.count()).select_from(UnknownSighting))
        assert left.scalar_one() == 0

    async def test_inactive_without_timestamp_starts_the_clock(self, db_session, fake_storage):
        person = _person(active=False, deactivated_at=None)
        db_session.add(person)
        await db_session.commit()

        counts = await run_cleanup_once(db_session)

        assert counts["biometrics_purged"] == 0
        await db_session.refresh(person)
        assert person.deactivated_at is not None
        assert person.biometric_embedding is not None

    async def test_zero_retention_disables_purge(self, db_session, fake_storage, monkeypatch):
        monkeypatch.setattr(settings, "biometric_retention_days_after_inactive", 0)
        person = _person(active=False, deactivated_at=datetime.now(timezone.utc) - timedelta(days=3650))
        db_session.add(person)
        await db_session.commit()

        counts = await run_cleanup_once(db_session)

        assert counts["biometrics_purged"] == 0
        await db_session.refresh(person)
        assert person.biometric_embedding is not None

    async def test_purge_refreshes_the_recognition_cache(self, db_session, fake_storage, monkeypatch):
        """Keshda qolgan o'chirilgan odam bir necha daqiqa tanilib
        yurmasligi kerak."""
        person = _person(active=True)
        db_session.add(person)
        await db_session.commit()
        assert str(person.id) in (await load_candidate_matrix_cached(db_session)).ids

        person.active = False
        person.deactivated_at = datetime.now(timezone.utc) - timedelta(days=3650)
        await db_session.commit()
        await run_cleanup_once(db_session)

        assert str(person.id) not in (await load_candidate_matrix_cached(db_session)).ids

    async def test_large_backlog_is_processed_in_batches(self, db_session, fake_storage, monkeypatch):
        monkeypatch.setattr(cleanup, "BIOMETRIC_BATCH_SIZE", 2)
        old = datetime.now(timezone.utc) - timedelta(days=3650)
        db_session.add_all(
            [_person(full_name=f"Odam {i}", active=False, deactivated_at=old, biometric_photo_key=f"b/{i}.jpg")
             for i in range(5)]
        )
        await db_session.commit()

        counts = await run_cleanup_once(db_session)

        assert counts["biometrics_purged"] == 5
        assert sorted(fake_storage["quiet"]) == [f"b/{i}.jpg" for i in range(5)]


@pytest.mark.usefixtures("seeded")
class TestSnapshotRetention:
    async def test_old_snapshots_are_removed_but_events_stay(self, db_session, fake_storage):
        now = datetime.now(timezone.utc)
        days = settings.snapshot_retention_days
        assert 0 < days < settings.event_retention_days
        old = _event(now - timedelta(days=days + 1), "events/old.jpg")
        fresh = _event(now - timedelta(days=days - 1), "events/fresh.jpg")
        db_session.add_all([old, fresh])
        await db_session.commit()

        counts = await run_cleanup_once(db_session)

        assert counts["snapshots_pruned"] == 1
        assert counts["events"] == 0
        assert fake_storage["single"] == ["events/old.jpg"]
        await db_session.refresh(old)
        await db_session.refresh(fresh)
        assert old.snapshot_key is None
        assert fresh.snapshot_key == "events/fresh.jpg"

    async def test_failed_object_delete_keeps_the_key_for_retry(self, db_session, fake_storage):
        now = datetime.now(timezone.utc)
        old_ok = _event(now - timedelta(days=settings.snapshot_retention_days + 2), "events/ok.jpg")
        old_fail = _event(now - timedelta(days=settings.snapshot_retention_days + 1), "events/fail.jpg")
        db_session.add_all([old_ok, old_fail])
        await db_session.commit()
        fake_storage["fail"].add("events/fail.jpg")

        counts = await run_cleanup_once(db_session)

        assert counts["snapshots_pruned"] == 1
        await db_session.refresh(old_ok)
        await db_session.refresh(old_fail)
        assert old_ok.snapshot_key is None
        assert old_fail.snapshot_key == "events/fail.jpg"

    async def test_zero_snapshot_retention_leaves_snapshots_to_event_purge(
        self, db_session, fake_storage, monkeypatch
    ):
        monkeypatch.setattr(settings, "snapshot_retention_days", 0)
        event = _event(datetime.now(timezone.utc) - timedelta(days=100), "events/keep.jpg")
        db_session.add(event)
        await db_session.commit()

        counts = await run_cleanup_once(db_session)

        assert counts["snapshots_pruned"] == 0
        await db_session.refresh(event)
        assert event.snapshot_key == "events/keep.jpg"


@pytest.mark.usefixtures("seeded")
class TestLogRetention:
    async def test_old_access_events_and_notification_logs_are_deleted(self, db_session, monkeypatch):
        monkeypatch.setattr(cleanup, "ROW_BATCH_SIZE", 2)
        now = datetime.now(timezone.utc)
        old_access = now - timedelta(days=settings.access_event_retention_days + 1)
        old_log = now - timedelta(days=settings.notification_log_retention_days + 1)
        db_session.add_all(
            [AccessEvent(external_id=f"old-{i}", occurred_at=old_access) for i in range(5)]
            + [AccessEvent(external_id="new", occurred_at=now)]
            + [
                NotificationLog(channel="telegram", recipient="1", kind="event", status="yuborildi", created_at=old_log)
                for _ in range(3)
            ]
            + [NotificationLog(channel="telegram", recipient="1", kind="event", status="yuborildi")]
        )
        await db_session.commit()

        counts = await run_cleanup_once(db_session)

        assert counts["access_events"] == 5
        assert counts["notification_logs"] == 3
        remaining = (await db_session.execute(select(AccessEvent.external_id))).scalars().all()
        assert remaining == ["new"]
        assert (await db_session.execute(select(func.count()).select_from(NotificationLog))).scalar_one() == 1

    async def test_zero_retention_keeps_everything(self, db_session, monkeypatch):
        monkeypatch.setattr(settings, "access_event_retention_days", 0)
        monkeypatch.setattr(settings, "notification_log_retention_days", 0)
        ancient = datetime.now(timezone.utc) - timedelta(days=5000)
        db_session.add_all([
            AccessEvent(external_id="old", occurred_at=ancient),
            NotificationLog(channel="sms", recipient="1", kind="event", status="xato", created_at=ancient),
        ])
        await db_session.commit()

        counts = await run_cleanup_once(db_session)

        assert counts["access_events"] == 0
        assert counts["notification_logs"] == 0
