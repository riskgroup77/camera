"""Avtomatik hisobot jadvali (report_schedules): haftalik/oylik Telegram yuborish.

Revision ID: f2a2b3c4d5e6
Revises: e2a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f2a2b3c4d5e6"
down_revision = "e2a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("report", sa.String(), nullable=False),
        sa.Column(
            "telegram_chat_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.CheckConstraint("kind IN ('haftalik', 'oylik')", name="ck_report_schedules_kind"),
        sa.CheckConstraint(
            "report IN ('kpi', 'davomat_xodim', 'davomat_talaba', 'tabel_xodim', 'tabel_talaba')",
            name="ck_report_schedules_report",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("report_schedules")
