import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.schemas.base import CamelModel
from app.services.notifications.sms import normalize_phone

NotificationKind = Literal[
    "event", "event_overdue", "camera_offline", "camera_online", "access_denied", "system", "teacher_absent"
]
NotificationChannel = Literal["telegram", "sms"]
Severity = Literal["past", "o'rta", "yuqori"]

# Telegram chat_id: shaxsiy chat (musbat), guruh/kanal (manfiy, -100...) yoki
# ochiq kanal nomi (@kanal).
_TELEGRAM_RECIPIENT_RE = re.compile(r"^(-?\d{1,20}|@[A-Za-z][A-Za-z0-9_]{4,31})$")

MAX_RECIPIENTS = 50


def clean_recipients(channel: str, recipients: list[str]) -> list[str]:
    """Qabul qiluvchilarni tekshiradi va bir xil ko'rinishga keltiradi
    (telefon — +998XXXXXXXXX). Takrorlar olib tashlanadi."""
    cleaned: list[str] = []
    for raw in recipients:
        value = str(raw).strip()
        if not value:
            continue
        if channel == "sms":
            phone = normalize_phone(value)
            if phone is None:
                raise ValueError(f"Telefon raqami noto'g'ri: {value} (+998XXXXXXXXX)")
            value = phone
        elif not _TELEGRAM_RECIPIENT_RE.match(value):
            raise ValueError(f"Telegram chat ID noto'g'ri: {value} (raqam yoki @kanal)")
        if value not in cleaned:
            cleaned.append(value)
    if len(cleaned) > MAX_RECIPIENTS:
        raise ValueError(f"Qabul qiluvchilar {MAX_RECIPIENTS} tadan oshmasligi kerak")
    return cleaned


class NotificationRuleOut(CamelModel):
    id: str
    name: str
    enabled: bool
    channel: NotificationChannel
    recipients: list[str]
    kinds: list[str]
    module_codes: list[int] | None = None
    building_ids: list[str] | None = None
    min_severity: Severity | None = None
    created_at: str


class _RuleFields(CamelModel):
    @field_validator("kinds", check_fields=False)
    @classmethod
    def _unique_kinds(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        return list(dict.fromkeys(value))

    @field_validator("module_codes", "building_ids", check_fields=False)
    @classmethod
    def _empty_is_none(cls, value: list | None) -> list | None:
        # Bo'sh ro'yxat — "cheklov yo'q", bazada NULL bilan bir xil.
        return list(dict.fromkeys(value)) if value else None


class NotificationRuleCreateIn(_RuleFields):
    name: str = Field(min_length=2, max_length=120)
    enabled: bool = True
    channel: NotificationChannel
    recipients: list[str] = Field(min_length=1)
    kinds: list[NotificationKind] = Field(min_length=1)
    module_codes: list[int] | None = None
    building_ids: list[str] | None = None
    min_severity: Severity | None = None

    @model_validator(mode="after")
    def _check_recipients(self) -> "NotificationRuleCreateIn":
        self.recipients = clean_recipients(self.channel, self.recipients)
        if not self.recipients:
            raise ValueError("Kamida bitta qabul qiluvchi kiriting")
        return self


class NotificationRuleUpdateIn(_RuleFields):
    """Qisman yangilash: yuborilmagan maydon o'zgarmaydi. Kanal yoki
    qabul qiluvchilar o'zgarsa, ular birgalikda qayta tekshiriladi (router)."""

    name: str | None = Field(default=None, min_length=2, max_length=120)
    enabled: bool | None = None
    channel: NotificationChannel | None = None
    recipients: list[str] | None = None
    kinds: list[NotificationKind] | None = None
    module_codes: list[int] | None = None
    building_ids: list[str] | None = None
    min_severity: Severity | None = None


class NotificationLogOut(CamelModel):
    id: str
    created_at: str
    channel: str
    recipient: str
    kind: str
    status: Literal["yuborildi", "xato", "otkazildi"]
    text: str
    error: str | None = None
    ref_id: str | None = None


class NotificationTestIn(CamelModel):
    channel: NotificationChannel
    recipient: str = Field(min_length=1, max_length=64)
    text: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _check_recipient(self) -> "NotificationTestIn":
        self.recipient = clean_recipients(self.channel, [self.recipient])[0]
        return self


class NotificationTestOut(CamelModel):
    ok: bool
    error: str | None = None


class NotificationStatusOut(CamelModel):
    telegram_configured: bool
    telegram_bot_username: str | None = None
    telegram_polling_enabled: bool
    sms_provider: str
    sms_configured: bool
    sms_sender: str | None = None
    parent_arrival_enabled: bool
    parent_absence_enabled: bool
    org_name: str


class MyNotificationsOut(CamelModel):
    telegram_linked: bool
    telegram_bot_configured: bool
    phone: str | None = None


class TelegramLinkOut(CamelModel):
    code: str
    deep_link: str
    bot_username: str
