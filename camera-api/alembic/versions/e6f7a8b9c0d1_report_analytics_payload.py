"""Hisobotlar: jonli tahlil ma'lumoti va hisobot so'rovlari uchun indekslar

Hisobot sahifasi endi matnli yozuvlar ro'yxati emas, jonli tahlil
(app/services/analytics.py). Arxivga saqlangan hisobot aynan sahifada
ko'ringan tuzilmani saqlaydi — reports.payload. Ustunlar nullable: eski
hisobotlar buzilmaydi va "eski format" sifatida ochiladi.

Indekslar hisobot va Hodisalar jurnali filtrlari uchun (status, muhimlik,
modul + vaqt). CREATE INDEX IF NOT EXISTS: lesson_sessions.date da indeks
allaqachon bo'lishi mumkin.

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-09-15
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e6f7a8b9c0d1"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None

INDEXES = (
    ("ix_events_status_occurred", "events", "status, occurred_at"),
    ("ix_events_severity_occurred", "events", "severity, occurred_at"),
    ("ix_events_module_occurred", "events", "module_code, occurred_at"),
    ("ix_lesson_sessions_date", "lesson_sessions", "date"),
)


def upgrade() -> None:
    op.add_column("reports", sa.Column("payload", postgresql.JSONB(), nullable=True))
    op.add_column("reports", sa.Column("range_start", sa.Date(), nullable=True))
    op.add_column("reports", sa.Column("range_end", sa.Date(), nullable=True))
    op.add_column("reports", sa.Column("created_by", sa.String(), nullable=True))
    for name, table, columns in INDEXES:
        op.execute(sa.text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns})"))


def downgrade() -> None:
    for name, _table, _columns in INDEXES:
        op.execute(sa.text(f"DROP INDEX IF EXISTS {name}"))
    op.drop_column("reports", "created_by")
    op.drop_column("reports", "range_end")
    op.drop_column("reports", "range_start")
    op.drop_column("reports", "payload")
