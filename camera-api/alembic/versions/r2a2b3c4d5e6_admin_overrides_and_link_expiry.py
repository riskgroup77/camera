"""Admin qarorlari HEMIS sinxronida saqlanadi, rozilik qaytarilgani belgisi,
Telegram havolasi muddati, bildirishnoma qayta yuborilgani.

Revision ID: r2a2b3c4d5e6
Revises: q2a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op

revision = "r2a2b3c4d5e6"
down_revision = "q2a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "students_staff",
        sa.Column("manually_deactivated", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("students_staff", sa.Column("biometrics_opt_out_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("students_staff", sa.Column("telegram_link_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("telegram_link_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("notification_log", sa.Column("resent_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("notification_log", "resent_at")
    op.drop_column("users", "telegram_link_expires_at")
    op.drop_column("students_staff", "telegram_link_expires_at")
    op.drop_column("students_staff", "biometrics_opt_out_at")
    op.drop_column("students_staff", "manually_deactivated")
