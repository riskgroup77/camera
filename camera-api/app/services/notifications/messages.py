"""Bildirishnoma matnlari (o'zbek tilida).

Har bir xabar ikki ko'rinishda: Telegram uchun HTML (sarlavha qalin,
havola bosiladigan) va SMS/jurnal uchun oddiy matn. Vaqt har doim
institut vaqtida (Asia/Tashkent) — app/timezone.py.
"""

import html
from dataclasses import dataclass, field
from datetime import date, datetime, time

from app.config import settings
from app.timezone import local_now, to_local
from app.timezone import business_today

SEVERITY_LABELS = {"past": "Past", "o'rta": "O'rta", "yuqori": "Yuqori"}
SEVERITY_ORDER = {"past": 0, "o'rta": 1, "yuqori": 2}

KIND_LABELS = {
    "event": "AI hodisa",
    "event_overdue": "Muddati o'tgan hodisa",
    "camera_offline": "Kamera o'chdi",
    "camera_online": "Kamera tiklandi",
    "access_denied": "Turniket rad etdi",
    "system": "Tizim",
    "parent_arrival": "Ota-ona: keldi",
    "parent_absence": "Ota-ona: kelmadi",
    "teacher_absent": "O'qituvchi darsga kelmadi",
}


@dataclass
class Message:
    title: str
    lines: list[tuple[str, str]] = field(default_factory=list)  # (yorliq, qiymat)
    link: str | None = None
    link_label: str = "Ochish"
    footer: str | None = None

    def html(self) -> str:
        parts = [f"<b>{html.escape(self.title)}</b>"]
        parts += [f"{html.escape(label)}: {html.escape(value)}" for label, value in self.lines if value]
        if self.footer:
            parts.append(html.escape(self.footer))
        if self.link:
            parts.append(f'<a href="{html.escape(self.link, quote=True)}">{html.escape(self.link_label)}</a>')
        return "\n".join(parts)

    def plain(self) -> str:
        parts = [self.title]
        parts += [f"{label}: {value}" for label, value in self.lines if value]
        if self.footer:
            parts.append(self.footer)
        if self.link:
            parts.append(self.link)
        return "\n".join(parts)

    def sms(self) -> str:
        """SMS qisqa bo'lishi kerak (har 70 belgi — alohida qism, alohida
        pul): sarlavha va qiymatlar bir qatorda, yorliqlarsiz."""
        values = [value for _, value in self.lines if value]
        body = f"{settings.org_name}: {self.title}"
        if values:
            body += ". " + ", ".join(values)
        if self.footer:
            body += ". " + self.footer
        return body


def format_moment(moment: datetime) -> str:
    """'19.09.2026 14:05:33' — Toshkent vaqti."""
    return to_local(moment).strftime("%d.%m.%Y %H:%M:%S")


def severity_label(severity: str | None) -> str:
    return SEVERITY_LABELS.get(severity or "", severity or "")


def event_link(event_id: str) -> str:
    return f"{settings.frontend_base_url.rstrip('/')}/hodisalar?id={event_id}"


def event_message(
    *,
    event_id: str,
    module_name: str,
    camera_name: str,
    building: str,
    severity: str,
    occurred_at: datetime,
    person_name: str | None = None,
    confidence: int | None = None,
) -> Message:
    return Message(
        title=f"AI hodisa: {module_name}",
        lines=[
            ("Kamera", camera_name),
            ("Bino", building),
            ("Daraja", severity_label(severity)),
            ("Shaxs", person_name or ""),
            ("Ishonch", f"{confidence}%" if confidence is not None else ""),
            ("Vaqt", format_moment(occurred_at)),
        ],
        link=event_link(event_id),
        link_label="Hodisani ochish",
    )


def event_overdue_message(
    *,
    event_id: str,
    module_name: str,
    camera_name: str,
    building: str,
    severity: str,
    occurred_at: datetime,
    due_at: datetime | None,
    assignee_name: str | None = None,
) -> Message:
    return Message(
        title=f"Hodisa muddati o'tdi: {module_name}",
        lines=[
            ("Kamera", camera_name),
            ("Bino", building),
            ("Daraja", severity_label(severity)),
            ("Sodir bo'lgan", format_moment(occurred_at)),
            ("Muddat", format_moment(due_at) if due_at else ""),
            ("Mas'ul", assignee_name or "tayinlanmagan"),
        ],
        link=event_link(event_id),
        link_label="Hodisani ochish",
    )


def camera_status_message(
    *,
    camera_name: str,
    building: str,
    ip: str | None,
    online: bool,
    offline_since: datetime | None,
    now: datetime,
) -> Message:
    if online:
        title = f"Kamera tiklandi: {camera_name}"
        lines = [("Bino", building), ("Manzil", ip or ""), ("Vaqt", format_moment(now))]
    else:
        title = f"Kamera o'chdi: {camera_name}"
        lines = [
            ("Bino", building),
            ("Manzil", ip or ""),
            ("O'chgan payt", format_moment(offline_since) if offline_since else ""),
            ("Davomiyligi", _duration(offline_since, now) if offline_since else ""),
        ]
    return Message(
        title=title,
        lines=lines,
        link=f"{settings.frontend_base_url.rstrip('/')}/sozlamalar/kameralar",
        link_label="Kameralar",
    )


def _duration(since: datetime, now: datetime) -> str:
    minutes = max(0, int((now - since).total_seconds() // 60))
    if minutes < 60:
        return f"{minutes} daqiqa"
    hours, rest = divmod(minutes, 60)
    return f"{hours} soat {rest} daqiqa" if rest else f"{hours} soat"


def access_denied_message(
    *, device_name: str, person_name: str | None, card_number: str | None, occurred_at: datetime
) -> Message:
    return Message(
        title=f"Turniket rad etdi: {device_name}",
        lines=[
            ("Shaxs", person_name or "Noma'lum shaxs"),
            ("Karta", card_number or ""),
            ("Vaqt", format_moment(occurred_at)),
        ],
    )


def parent_arrival_text(full_name: str, check_in: time | None, fallback_moment: datetime | None = None) -> str:
    """"Farg'ona JSSTI: Farzandingiz Aliyev Vali 08:12 da institutga keldi."

    check_in — davomat yozuvidagi mahalliy vaqt (attendance_ai uni
    institut vaqtida yozadi)."""
    if check_in is not None:
        clock = check_in.strftime("%H:%M")
    elif fallback_moment is not None:
        clock = to_local(fallback_moment).strftime("%H:%M")
    else:
        clock = ""
    when = f" {clock} da" if clock else ""
    return f"{settings.org_name}: Farzandingiz {full_name}{when} institutga keldi."


def parent_absence_text(full_name: str, day: date) -> str:
    """Kelmaganlar kun oxirida (yoki ertasi tongda) belgilanadi — shuning
    uchun "bugun" faqat sana haqiqatan bugungi bo'lsa yoziladi."""
    stamp = day.strftime("%d.%m.%Y")
    when = f"bugun ({stamp})" if day == business_today() else f"{stamp} kuni"
    return f"{settings.org_name}: Farzandingiz {full_name} {when} institutga kelmadi."


def sample_message(text: str | None) -> Message:
    return Message(
        title=f"{settings.org_system_name}: sinov xabari",
        footer=text or "Bildirishnomalar to'g'ri sozlangan. Bu xabarga javob berish shart emas.",
    )
