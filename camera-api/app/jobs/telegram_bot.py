"""Telegram bot: '/start <kod>' orqali foydalanuvchi va ota-onalarni bog'lash (getUpdates).

Faqat AI lider jarayonida ishlaydi (app/main.py) — Telegram bitta tokenga
bir vaqtda faqat bitta getUpdates so'roviga ruxsat beradi (aks holda 409).

Buyruqlar:
- /start <kod> — kod users.telegram_link_code yoki
  students_staff.telegram_link_code bilan solishtiriladi; topilsa chat
  bog'lanadi, kod o'chiriladi (bir martalik).
- /stop — shu chatga tegishli barcha bog'lanishlarni uzadi.
- /chatid — chat identifikatori (guruhni qoidaga qabul qiluvchi qilib
  qo'shish uchun).
- boshqa har qanday xabar — qisqa yordam matni.
"""

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import SessionLocal
from app.models import AuditLog, StudentStaff, User
from app.services.notifications import telegram

logger = logging.getLogger("app.telegram_bot")

POLL_TIMEOUT_SECONDS = 25
IDLE_SLEEP_SECONDS = 60
MAX_BACKOFF_SECONDS = 300

HELP_TEXT = (
    "Assalomu alaykum! Bu {system} ({org}) bildirishnomalar boti.\n\n"
    "Hisobingizni bog'lash uchun tizimdagi \"Telegramni bog'lash\" havolasini oching "
    "yoki administrator bergan havoladan foydalaning.\n\n"
    "/stop — bog'lanishni bekor qilish\n"
    "/chatid — shu chat identifikatori"
)


def _help() -> str:
    return HELP_TEXT.format(system=settings.org_system_name, org=settings.org_name)


def _audit(db: AsyncSession, action: str) -> None:
    db.add(
        AuditLog(
            user_id=None,
            user_name="Telegram bot",
            action=action,
            module="Bildirishnomalar",
            status="muvaffaqiyatli",
            ip="telegram",
        )
    )


def _expired(expires_at) -> bool:
    from datetime import datetime, timezone

    return expires_at is not None and expires_at < datetime.now(timezone.utc)


EXPIRED_TEXT = "Havola muddati tugagan (7 kun). Tizimdan yangi havola oling."


async def _link(db: AsyncSession, code: str, chat_id: str) -> str:
    user = (await db.execute(select(User).where(User.telegram_link_code == code))).scalar_one_or_none()
    if user is not None and _expired(user.telegram_link_expires_at):
        return EXPIRED_TEXT
    if user is not None:
        user.telegram_chat_id = chat_id
        user.telegram_link_code = None
        _audit(db, f"Telegram bog'landi: foydalanuvchi {user.login}")
        await db.commit()
        return (
            f"Hisobingiz bog'landi: {user.full_name}.\n"
            f"Endi {settings.org_system_name} shaxsiy bildirishnomalari shu yerga keladi."
        )

    person = (
        await db.execute(select(StudentStaff).where(StudentStaff.telegram_link_code == code))
    ).scalar_one_or_none()
    if person is not None and _expired(person.telegram_link_expires_at):
        return EXPIRED_TEXT
    if person is not None:
        person.parent_telegram_chat_id = chat_id
        person.telegram_link_code = None
        _audit(db, f"Ota-ona Telegrami bog'landi: {person.full_name}")
        await db.commit()
        return (
            f"{settings.org_name}: siz {person.full_name}ning ota-onasi sifatida bog'landingiz.\n"
            "Farzandingizning institutga kelgani (yoki kelmagani) haqidagi xabarlar shu yerga keladi."
        )

    return "Kod noto'g'ri yoki allaqachon ishlatilgan. Tizimdan yangi havola oling."


async def _unlink(db: AsyncSession, chat_id: str) -> str:
    users = await db.execute(
        update(User).where(User.telegram_chat_id == chat_id).values(telegram_chat_id=None).returning(User.id)
    )
    people = await db.execute(
        update(StudentStaff)
        .where(StudentStaff.parent_telegram_chat_id == chat_id)
        .values(parent_telegram_chat_id=None)
        .returning(StudentStaff.id)
    )
    count = len(users.all()) + len(people.all())
    if count:
        _audit(db, f"Telegram bog'lanishi bekor qilindi ({count} ta)")
    await db.commit()
    if not count:
        return "Bu chat hech qanday hisobga bog'lanmagan."
    return "Bog'lanish bekor qilindi. Endi bu chatga bildirishnomalar kelmaydi."


def _command(text: str) -> tuple[str, str]:
    """'/start@MyBot abc' -> ('/start', 'abc')."""
    head, _, rest = text.strip().partition(" ")
    return head.split("@", 1)[0].lower(), rest.strip()


async def handle_update(update: dict[str, Any], session_factory: Callable[[], Any] = SessionLocal) -> str | None:
    """Bitta update'ni qayta ishlaydi va javob yuboradi. Javob matnini
    qaytaradi (testlar uchun); javob kerak bo'lmasa — None."""
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = message.get("text")
    if chat_id is None or not isinstance(text, str):
        return None
    chat_id = str(chat_id)
    command, argument = _command(text)
    is_private = chat.get("type", "private") == "private"

    if command == "/chatid":
        reply = f"Chat ID: {chat_id}"
    elif command == "/start" and argument and is_private:
        # Kod — faqat token_urlsafe belgilari; boshqa narsa bazaga ham bormaydi.
        code = argument[:64]
        if not code.replace("-", "").replace("_", "").isalnum():
            reply = "Kod noto'g'ri yoki allaqachon ishlatilgan. Tizimdan yangi havola oling."
        else:
            async with session_factory() as db:
                reply = await _link(db, code, chat_id)
    elif command == "/stop" and is_private:
        async with session_factory() as db:
            reply = await _unlink(db, chat_id)
    elif not is_private:
        # Guruhda faqat /chatid ga javob beramiz — suhbatni buzmaslik uchun.
        return None
    else:
        reply = _help()

    result = await telegram.send_message(chat_id, reply, html=False)
    if not result.ok:
        logger.warning("telegram bot reply failed", extra={"error": result.error})
    return reply


async def poll_once(offset: int | None, session_factory: Callable[[], Any] = SessionLocal) -> int | None:
    """Bitta getUpdates sikli; keyingi offset'ni qaytaradi. Tarmoq xatosi
    chaqiruvchiga (telegram.TelegramError) ko'tariladi."""
    updates = await telegram.get_updates(offset, timeout=POLL_TIMEOUT_SECONDS)
    for upd in updates:
        update_id = upd.get("update_id")
        if isinstance(update_id, int):
            # Offset avval suriladi: bitta buzuq update butun navbatni
            # cheksiz qayta o'qishga majburlamasin.
            offset = max(offset or 0, update_id + 1)
        try:
            await handle_update(upd, session_factory)
        except Exception:
            logger.exception("telegram update handling failed", extra={"update_id": update_id})
    return offset


async def telegram_bot_loop() -> None:
    offset: int | None = None
    backoff = 1.0
    while True:
        if not settings.telegram_bot_token or not settings.telegram_polling_enabled:
            await asyncio.sleep(IDLE_SLEEP_SECONDS)
            continue
        try:
            offset = await poll_once(offset)
            backoff = 1.0
        except asyncio.CancelledError:
            raise
        except telegram.TelegramError as exc:
            if exc.status == 409:
                # Boshqa jarayon getUpdates qilyapti yoki webhook o'rnatilgan.
                logger.warning("telegram getUpdates conflict (webhook or another poller)", extra={"error": str(exc)})
                await asyncio.sleep(IDLE_SLEEP_SECONDS)
                continue
            if exc.status == 401:
                logger.error("telegram bot token rejected")
                await asyncio.sleep(MAX_BACKOFF_SECONDS)
                continue
            logger.warning("telegram polling failed", extra={"error": str(exc), "retry_in": backoff})
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
        except Exception:
            logger.exception("telegram polling crashed", extra={"retry_in": backoff})
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
