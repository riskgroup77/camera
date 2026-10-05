from typing import Literal

from pydantic import Field

from app.schemas.base import CamelModel

EventStatusLiteral = Literal["yangi", "jarayonda", "tasdiqlangan", "rad_etilgan", "hal_qilindi"]
# Bir nechta hodisaga birdan qo'llash mumkin bo'lgan qarorlar.
BulkStatusLiteral = Literal["tasdiqlangan", "rad_etilgan", "hal_qilindi"]
CommentKindLiteral = Literal["izoh", "holat", "tayinlash"]


class EventOut(CamelModel):
    """Matches src/types/index.ts `AIEvent` exactly."""

    id: str
    timestamp: str
    camera_id: str
    camera_name: str
    building: str
    module_code: int
    module_name: str
    group: Literal["A", "B", "C", "D", "E", "F"]
    confidence: int
    severity: Literal["past", "o'rta", "yuqori"]
    status: EventStatusLiteral
    person_name: str | None = None
    reviewed_by: str | None = None
    # Presigned URL to the frame that triggered this event — see
    # app/services/event_bus.py. Null when no frame was captured (or the
    # upload failed) for this particular event.
    snapshot_url: str | None = None
    # Arxivdan kesilgan hodisa videosi (app/jobs/event_clips.py) — presigned.
    clip_url: str | None = None
    # ISO vaqt institut mintaqasi bilan — frontend "12 daq oldin" hisoblaydi.
    occurred_at: str | None = None
    # Operator qaror qilgan payt ("2026-09-15 14:20", institut vaqti).
    reviewed_at: str | None = None
    # Sinov rejimidagi modul signali — operator navbatiga chiqmaydi.
    is_trial: bool = False
    # Dalil: {"reason": "...", "metrics": {...}} — app/services/event_bus.py.
    details: dict | None = None
    # Ish jarayoni. Vaqtlar ISO (institut mintaqasi) — frontend muddatgacha
    # qolgan vaqtni o'zi hisoblaydi.
    assigned_to_id: str | None = None
    assigned_to_name: str | None = None
    assigned_at: str | None = None
    due_at: str | None = None
    # Muddat o'tgan va hali qaror qilinmagan (yangi/jarayonda).
    overdue: bool = False
    escalated_at: str | None = None
    resolved_at: str | None = None
    resolved_by: str | None = None
    resolution_note: str | None = None
    # Ro'yxatda hisoblanadi; WebSocket xabarida null bo'lishi mumkin.
    comments_count: int | None = None
    # Operator ko'rsatmasi (SOP) qadamlari — app/services/sop.py.
    sop: list[str] = Field(default_factory=list)


class EventCreateIn(CamelModel):
    """Submitted by an AI inference service when it detects something —
    not by a human admin through the UI."""

    camera_id: str
    module_code: int
    module_name: str
    group: Literal["A", "B", "C", "D", "E", "F"]
    confidence: int
    severity: Literal["past", "o'rta", "yuqori"]
    person_name: str | None = None


class EventReviewIn(CamelModel):
    status: Literal["tasdiqlangan", "rad_etilgan"]


class EventBulkReviewIn(CamelModel):
    ids: list[str] = Field(min_length=1, max_length=200)
    status: BulkStatusLiteral
    # "hal_qilindi" uchun majburiy — barcha tanlangan hodisalarga yoziladi.
    note: str | None = Field(default=None, max_length=2000)


class EventBulkReviewOut(CamelModel):
    updated: int
    skipped: int
    status: BulkStatusLiteral


class EventAssignIn(CamelModel):
    # null — tayinlovni olib tashlash; "me" — joriy foydalanuvchiga.
    user_id: str | None = Field(default=None, max_length=64)


class EventStatusIn(CamelModel):
    status: EventStatusLiteral
    # "hal_qilindi" uchun majburiy (qanday chora ko'rilgani).
    note: str | None = Field(default=None, max_length=2000)


class EventCommentIn(CamelModel):
    body: str = Field(min_length=1, max_length=2000)


class EventCommentOut(CamelModel):
    id: str
    kind: CommentKindLiteral
    body: str
    author_id: str | None = None
    author_name: str
    created_at: str


class EventTimelineItemOut(CamelModel):
    """Hodisa tarixi: yaratilish, izohlar, holat/tayinlash o'zgarishlari va
    muddat o'tgani haqidagi ogohlantirish — vaqt bo'yicha."""

    id: str
    kind: Literal["yaratildi", "izoh", "holat", "tayinlash", "muddat"]
    at: str
    author_name: str | None = None
    body: str


class EventAssigneeOut(CamelModel):
    id: str
    full_name: str
    role: str


class EventFacetOut(CamelModel):
    """Filtr ro'yxati uchun: qiymat, ko'rinadigan nom va signallar soni."""

    value: str
    label: str
    count: int


class EventSummaryOut(CamelModel):
    """Hodisalar jurnalining tepa qatori va filtrlari — bitta so'rovda.
    Ilgari sahifa sonlarni olish uchun har ro'yxat o'zgarganda uchta to'liq
    /api/events so'rovi yuborardi."""

    total: int
    # Holatlar bo'yicha aniq sonlar (ro'yxat filtrlari bilan mos keladi).
    unreviewed: int
    in_progress: int = 0
    confirmed: int
    rejected: int
    resolved: int = 0
    unreviewed_high: int
    unreviewed_medium: int
    unreviewed_low: int
    today: int
    today_serious: int
    stale_serious_unreviewed: int
    oldest_unreviewed_hours: float | None = None
    # Oxirgi 30 kun: signal kelgandan operator qaroriga qadar o'rtacha vaqt.
    avg_review_minutes: float | None = None
    # Oxirgi 30 kun: tasdiqlangan (+ hal qilingan) / ko'rib chiqilgan
    # (kamida 10 ta bo'lsa). Nomida raqam yo'q: camelCase generatori
    # "precision_30d" ni kutilgan "precision30d" ga aylantirmaydi.
    recent_precision: float | None = None
    # Ish jarayoni: muddati o'tgan (yangi/jarayonda), menga tayinlangan
    # (yangi/jarayonda/tasdiqlangan) va hech kimga tayinlanmagan (yangi/jarayonda).
    overdue: int = 0
    assigned_to_me: int = 0
    unassigned: int = 0
    modules: list[EventFacetOut] = []
    # Sinov rejimidagi, hali baholanmagan signallar — "Sinov namunalari" uchun.
    trial_unreviewed: int = 0
    trial_modules: list[EventFacetOut] = []
    buildings: list[EventFacetOut] = []
