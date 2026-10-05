"""Fon ishlari va hodisalar xulosasi uchun indekslar.

- lesson_sessions(scheduled_start_time): dars sifati (30 s), punktuallik
  (60 s) va dars davomati (300 s) aylanishlari boshlanish vaqti oralig'i
  bo'yicha — faqat `date` indeksi bor edi, har aylanish to'liq skan.
- lesson_sessions: tekshirilmagan darslar (punktuallik navbati).
- events(reviewed_at): hodisalar xulosasidagi "ko'rib chiqilgan" sanog'i.
- events: suratli eski hodisalar — tozalash suratni o'chirgan qatorlar
  ustidan har partiyada qayta yurmasin.

Revision ID: s2a2b3c4d5e6
Revises: r2a2b3c4d5e6
"""

from alembic import op

revision = "s2a2b3c4d5e6"
down_revision = "r2a2b3c4d5e6"
branch_labels = None
depends_on = None

INDEXES = (
    ("ix_lesson_sessions_start", "lesson_sessions (scheduled_start_time)"),
    (
        "ix_lesson_sessions_punctuality_pending",
        "lesson_sessions (scheduled_start_time) WHERE punctuality_checked_at IS NULL AND teacher_id IS NOT NULL",
    ),
    ("ix_events_reviewed_at", "events (reviewed_at) WHERE reviewed_at IS NOT NULL"),
    ("ix_events_snapshot_pending", "events (occurred_at) WHERE snapshot_key IS NOT NULL"),
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for name, definition in INDEXES:
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {definition}")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, _definition in INDEXES:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
