"""Foydalanuvchi: ikki bosqichli kirish (TOTP) va bino doirasi.

Revision ID: j2a2b3c4d5e6
Revises: i2a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "j2a2b3c4d5e6"
down_revision = "i2a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Sir Fernet bilan shifrlangan holda (app/crypto.py).
    op.add_column("users", sa.Column("totp_secret", sa.String(), nullable=True))
    op.add_column(
        "users", sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false"))
    )
    op.add_column("users", sa.Column("totp_confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("totp_last_step", sa.BigInteger(), nullable=True))
    # NULL — barcha binolar (mavjud hisoblar hech narsa yo'qotmaydi).
    op.add_column("users", sa.Column("allowed_building_ids", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "allowed_building_ids")
    op.drop_column("users", "totp_last_step")
    op.drop_column("users", "totp_confirmed_at")
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret")
