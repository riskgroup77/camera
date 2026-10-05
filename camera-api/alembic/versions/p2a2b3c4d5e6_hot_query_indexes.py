"""Tez-tez ishlaydigan so'rovlar uchun indekslar.

- events: ochiq (yangi/jarayonda) hodisalar — qisman indeks; Nazorat,
  devor ekrani va hodisalar xulosasi har 15 soniyada sanaydi.
- presence_visits(last_seen_at): "bugun/so'nggi 10 daqiqa" oralig'i.
- unknown_sightings: kutilayotganlar (kun bo'yicha).
- notification_log: ref_id va (kind, created_at).
- access_events: (student_staff_id, occurred_at).

CONCURRENTLY — ishlab turgan tizimda jadvalni qulflamasdan.

Revision ID: p2a2b3c4d5e6
Revises: o2a2b3c4d5e6
"""

from alembic import op

revision = "p2a2b3c4d5e6"
down_revision = "o2a2b3c4d5e6"
branch_labels = None
depends_on = None

INDEXES = (
    ("ix_events_open", "events (occurred_at DESC) WHERE status IN ('yangi', 'jarayonda') AND is_trial = false"),
    ("ix_presence_visits_last_seen", "presence_visits (last_seen_at)"),
    ("ix_unknown_sightings_pending", "unknown_sightings (day) WHERE status = 'kutilmoqda'"),
    ("ix_notification_log_ref", "notification_log (ref_id)"),
    ("ix_notification_log_kind_created", "notification_log (kind, created_at)"),
    ("ix_access_events_person_time", "access_events (student_staff_id, occurred_at DESC)"),
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for name, definition in INDEXES:
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {definition}")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, _definition in INDEXES:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
