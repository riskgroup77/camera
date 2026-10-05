"""Bayram va qo'shimcha dam olish kunlari (holidays).

Revision ID: o2a2b3c4d5e6
Revises: n2a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op

revision = "o2a2b3c4d5e6"
down_revision = "n2a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "holidays",
        sa.Column("date", sa.Date(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("holidays")
