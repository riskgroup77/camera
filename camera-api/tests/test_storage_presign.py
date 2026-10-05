"""Imzolangan URL yarim umri davomida qayta beriladi — brauzer keshi ishlashi uchun."""

from types import SimpleNamespace

from app import storage


def test_same_key_reuses_url_until_half_life(monkeypatch):
    calls: list[str] = []

    def fake_presign(operation, Params, ExpiresIn):
        calls.append(Params["Key"])
        return f"https://s3.test/{Params['Key']}?imzo={len(calls)}"

    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(storage._s3_public, "generate_presigned_url", fake_presign)
    monkeypatch.setattr(storage, "_presign_cache", {})
    monkeypatch.setattr(storage, "time", SimpleNamespace(monotonic=lambda: clock.now))

    first = storage.presigned_url("events/a.jpg")
    assert storage.presigned_url("events/a.jpg") == first
    assert storage.presigned_url("events/b.jpg") != first

    clock.now += storage.PRESIGNED_URL_TTL_SECONDS / 2 + 1
    renewed = storage.presigned_url("events/a.jpg")
    assert renewed != first
    assert calls == ["events/a.jpg", "events/b.jpg", "events/a.jpg"]


def test_deleted_object_is_not_served_from_cache(monkeypatch):
    monkeypatch.setattr(storage._s3_public, "generate_presigned_url", lambda operation, Params, ExpiresIn: "u")
    monkeypatch.setattr(storage._s3, "delete_object", lambda **kwargs: None)
    monkeypatch.setattr(storage, "_presign_cache", {})

    storage.presigned_url("biometrics/x.jpg")
    storage.delete_file("biometrics/x.jpg")
    assert "biometrics/x.jpg" not in storage._presign_cache
