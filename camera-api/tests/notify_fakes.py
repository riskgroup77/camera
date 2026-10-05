"""Bildirishnoma testlari uchun soxta Telegram va Eskiz serverlari
(httpx.MockTransport) — haqiqiy tashqi xizmatga hech qachon murojaat qilinmaydi."""

import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from urllib.parse import parse_qs

import httpx
import pytest

TG_BASE = "https://tg.test"
TG_TOKEN = "123456:SECRET-TOKEN"
ESKIZ_BASE = "https://eskiz.test/api"


@dataclass
class Call:
    service: str  # "telegram" | "eskiz"
    method: str  # "sendMessage", "auth/login", "message/sms/send", ...
    body: dict
    headers: dict
    raw: bytes = b""


@dataclass
class FakeApis:
    calls: list[Call] = field(default_factory=list)
    # method -> navbatdagi javoblar (status, json). Navbat bo'sh bo'lsa — muvaffaqiyat.
    queued: dict[str, deque] = field(default_factory=lambda: defaultdict(deque))
    updates: list[dict] = field(default_factory=list)
    eskiz_tokens: int = 0

    def queue(self, method: str, status: int, payload: dict) -> None:
        self.queued[method].append((status, payload))

    def of(self, method: str) -> list[Call]:
        return [c for c in self.calls if c.method == method]

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        raw = request.content
        ctype = request.headers.get("content-type", "")
        if "application/json" in ctype:
            body = json.loads(raw or b"{}")
        elif "application/x-www-form-urlencoded" in ctype:
            body = {k: v[0] for k, v in parse_qs(raw.decode()).items()}
        else:
            body = {}
        if url.startswith(TG_BASE):
            method = url.rsplit("/", 1)[-1]
            self.calls.append(Call("telegram", method, body, dict(request.headers), raw))
            if self.queued[method]:
                status, payload = self.queued[method].popleft()
                return httpx.Response(status, json=payload)
            if method == "getUpdates":
                result, self.updates = self.updates, []
                return httpx.Response(200, json={"ok": True, "result": result})
            if method == "getMe":
                return httpx.Response(200, json={"ok": True, "result": {"id": 1, "username": "situatsion_bot"}})
            return httpx.Response(200, json={"ok": True, "result": {"message_id": len(self.calls)}})
        if url.startswith(ESKIZ_BASE):
            method = url[len(ESKIZ_BASE) + 1 :]
            self.calls.append(Call("eskiz", method, body, dict(request.headers), raw))
            if self.queued[method]:
                status, payload = self.queued[method].popleft()
                return httpx.Response(status, json=payload)
            if method == "auth/login":
                self.eskiz_tokens += 1
                return httpx.Response(200, json={"message": "token_generated", "data": {"token": f"eskiz-token-{self.eskiz_tokens}"}})
            if method == "message/sms/send":
                return httpx.Response(200, json={"id": "abc", "message": "Waiting for SMS provider", "status": "waiting"})
        return httpx.Response(404, json={"message": "not found"})


@pytest.fixture
def apis(monkeypatch):
    """Telegram va Eskiz sozlangan, lekin barcha so'rovlar FakeApis'ga
    boradi; fondagi yuborishlar test bazasidan foydalanadi."""
    from app.config import settings
    from app.database import SessionLocal
    from app.services.notifications import dispatcher, sms, telegram
    from app.services.notifications.http import set_transport_for_tests
    from tests.conftest import TestSessionLocal

    fake = FakeApis()
    set_transport_for_tests(httpx.MockTransport(fake.handler))
    monkeypatch.setattr(settings, "telegram_bot_token", TG_TOKEN)
    monkeypatch.setattr(settings, "telegram_api_base_url", TG_BASE)
    monkeypatch.setattr(settings, "telegram_bot_username", "")
    monkeypatch.setattr(settings, "sms_provider", "eskiz")
    monkeypatch.setattr(settings, "eskiz_email", "ops@example.uz")
    monkeypatch.setattr(settings, "eskiz_password", "eskiz-pw-secret")
    monkeypatch.setattr(settings, "eskiz_base_url", ESKIZ_BASE)
    monkeypatch.setattr(settings, "frontend_base_url", "https://markaz.example.uz")

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(telegram, "_sleep", _no_sleep)

    async def _no_snapshot(_key: str) -> bytes | None:
        return None

    monkeypatch.setattr(dispatcher, "_load_snapshot", _no_snapshot)
    dispatcher.set_session_factory(TestSessionLocal)
    dispatcher.reset_state_for_tests()
    telegram.reset_cache_for_tests()
    sms.reset_token_for_tests()
    yield fake
    set_transport_for_tests(None)
    dispatcher.set_session_factory(SessionLocal)
    dispatcher.reset_state_for_tests()
    telegram.reset_cache_for_tests()
    sms.reset_token_for_tests()
