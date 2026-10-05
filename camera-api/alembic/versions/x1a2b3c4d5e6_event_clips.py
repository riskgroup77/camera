"""Hodisa klipi: arxivdan kesilgan qisqa video (MinIO kaliti).

Revision ID: x1a2b3c4d5e6
Revises: w1a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op

revision = "x1a2b3c4d5e6"
down_revision = "w1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("clip_key", sa.String(), nullable=True))
    # "none" — arxivda yozuv topilmadi, qayta urinilmaydi; "ok" — saqlandi.
    op.add_column("events", sa.Column("clip_status", sa.String(length=16), nullable=True))
    op.add_column("events", sa.Column("clip_saved_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "clip_saved_at")
    op.drop_column("events", "clip_status")
    op.drop_column("events", "clip_key")
