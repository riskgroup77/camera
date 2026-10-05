"""Telegram bot: /start <kod> bog'lash, /stop, /chatid, yordam, getUpdates offset."""

import pytest
from sqlalchemy import select

from app.jobs import telegram_bot
from app.models import AuditLog, StudentStaff, User
from app.services.notifications import telegram
from tests.conftest import TestSessionLocal
from tests.notify_fakes import apis  # noqa: F401 — fixture

pytestmark = pytest.mark.asyncio


def _update(update_id: int, text: str, chat_id: int = 5001, chat_type: str = "private") -> dict:
    return {
        "update_id": update_id,
        "message": {"message_id": update_id, "chat": {"id": chat_id, "type": chat_type}, "text": text},
    }


async def _handle(update: dict) -> str | None:
    return await telegram_bot.handle_update(update, TestSessionLocal)


async def test_start_links_user_and_clears_code(apis, db_session):
    user = User(login="op1", password_hash="x", full_name="Operator Bir", role="admin", telegram_link_code="CodeUser_123-abc")
    db_session.add(user)
    await db_session.commit()

    reply = await _handle(_update(1, "/start CodeUser_123-abc"))
    assert "Hisobingiz bog'landi: Operator Bir" in reply

    refreshed = await db_session.get(User, user.id, populate_existing=True)
    assert refreshed.telegram_chat_id == "5001"
    assert refreshed.telegram_link_code is None
    sent = apis.of("sendMessage")
    assert sent[0].body["chat_id"] == "5001"
    assert "parse_mode" not in sent[0].body
    audit = (await db_session.execute(select(AuditLog))).scalars().all()
    assert any("op1" in a.action for a in audit)

    # Kod bir martalik
    again = await _handle(_update(2, "/start CodeUser_123-abc", chat_id=6002))
    assert "noto'g'ri" in again


async def test_start_links_parent(apis, db_session):
    person = StudentStaff(
        full_name="Aliyev Vali", type="talaba", group_or_position="2-kurs, DI-1625", telegram_link_code="ParentCode9"
    )
    db_session.add(person)
    await db_session.commit()

    reply = await _handle(_update(1, "/start ParentCode9", chat_id=7007))
    assert "Aliyev Valining ota-onasi sifatida bog'landingiz" in reply
    refreshed = await db_session.get(StudentStaff, person.id, populate_existing=True)
    assert refreshed.parent_telegram_chat_id == "7007"
    assert refreshed.telegram_link_code is None


async def test_start_with_unknown_or_malformed_code(apis):
    assert "noto'g'ri" in await _handle(_update(1, "/start nosuchcode"))
    assert "noto'g'ri" in await _handle(_update(2, "/start ' OR 1=1 --"))


async def test_stop_unlinks_everything_for_chat(apis, db_session):
    user = User(login="op2", password_hash="x", full_name="Operator Ikki", role="admin", telegram_chat_id="5001")
    person = StudentStaff(full_name="Karimova Oy", type="talaba", group_or_position="1-kurs", parent_telegram_chat_id="5001")
    other = User(login="op3", password_hash="x", full_name="Boshqa Odam", role="admin", telegram_chat_id="9999")
    db_session.add_all([user, person, other])
    await db_session.commit()

    reply = await _handle(_update(1, "/stop"))
    assert "bekor qilindi" in reply
    assert (await db_session.get(User, user.id, populate_existing=True)).telegram_chat_id is None
    assert (await db_session.get(StudentStaff, person.id, populate_existing=True)).parent_telegram_chat_id is None
    assert (await db_session.get(User, other.id, populate_existing=True)).telegram_chat_id == "9999"

    assert "bog'lanmagan" in await _handle(_update(2, "/stop"))


async def test_help_chatid_and_groups(apis):
    help_reply = await _handle(_update(1, "salom"))
    assert "/stop" in help_reply
    assert await _handle(_update(2, "/start")) == help_reply
    assert await _handle(_update(3, "/chatid@situatsion_bot", chat_id=-100123, chat_type="supergroup")) == "Chat ID: -100123"
    # Guruhda boshqa xabarlarga javob berilmaydi
    assert await _handle(_update(4, "salom hammaga", chat_id=-100123, chat_type="group")) is None
    assert await _handle({"update_id": 5, "edited_message": {}}) is None


async def test_poll_once_tracks_offset(apis, db_session):
    apis.updates = [_update(10, "/chatid"), _update(11, "salom")]
    offset = await telegram_bot.poll_once(None, TestSessionLocal)
    assert offset == 12
    get_updates = apis.of("getUpdates")[0].body
    assert get_updates["timeout"] == telegram_bot.POLL_TIMEOUT_SECONDS
    assert "offset" not in get_updates

    offset = await telegram_bot.poll_once(offset, TestSessionLocal)
    assert offset == 12
    assert apis.of("getUpdates")[1].body["offset"] == 12


async def test_poll_once_survives_bad_update(apis, monkeypatch):
    calls: list[int] = []

    async def flaky(update, session_factory):
        calls.append(update["update_id"])
        if update["update_id"] == 20:
            raise RuntimeError("buzuq")
        return None

    monkeypatch.setattr(telegram_bot, "handle_update", flaky)
    apis.updates = [_update(20, "x"), _update(21, "y")]
    assert await telegram_bot.poll_once(None, TestSessionLocal) == 22
    assert calls == [20, 21]


async def test_get_updates_error_raises_for_backoff(apis):
    apis.queue("getUpdates", 409, {"ok": False, "error_code": 409, "description": "Conflict: terminated by other getUpdates request"})
    with pytest.raises(telegram.TelegramError) as info:
        await telegram_bot.poll_once(None, TestSessionLocal)
    assert info.value.status == 409
