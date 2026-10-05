"""AI aniqligi: modul sinov rejimi, hodisa dalili, shovqinli juftliklarni o'chirish

- ai_modules.mode: 'ishchi' | 'sinov'. Kalibrlanmagan evristikalar sinovga
  o'tadi — signal yoziladi, lekin operator navbatiga chiqmaydi.
- events.is_trial, events.details: sinov signali belgisi va dalil (sabab,
  o'lchangan qiymatlar).
- module_camera_suppressions: operatorlar ko'p rad etgan kamera×modul
  juftliklari (app/jobs/module_suppression.py).

Revision ID: h1b2c3d4e5f6
Revises: g8b9c0d1e2f3
Create Date: 2026-09-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "h1b2c3d4e5f6"
down_revision = "g8b9c0d1e2f3"
branch_labels = None
depends_on = None

# app/seed.py TRIAL_MODULE_CODES bilan bir xil.
TRIAL_CODES = (2, 10, 13, 14, 15, 17, 19, 21, 23)


def upgrade() -> None:
    op.add_column("ai_modules", sa.Column("mode", sa.String(), nullable=False, server_default="ishchi"))
    op.create_check_constraint("ck_ai_modules_mode", "ai_modules", "mode IN ('ishchi', 'sinov')")
    codes = ", ".join(str(code) for code in TRIAL_CODES)
    op.execute(sa.text(f"UPDATE ai_modules SET mode = 'sinov' WHERE code IN ({codes})"))

    # Doimiy default bilan ustun qo'shish Postgres'da faqat metama'lumot —
    # katta events jadvali qayta yozilmaydi.
    op.add_column("events", sa.Column("is_trial", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("events", sa.Column("details", postgresql.JSONB(), nullable=True))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_events_trial_occurred ON events (is_trial, occurred_at)"))

    op.create_table(
        "module_camera_suppressions",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "camera_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cameras.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("module_code", sa.Integer(), nullable=False),
        sa.Column("confirmed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("precision", sa.Float(), nullable=True),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("restored_by", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_module_suppressions_lookup",
        "module_camera_suppressions",
        ["camera_id", "module_code", "restored_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_module_suppressions_lookup", table_name="module_camera_suppressions")
    op.drop_table("module_camera_suppressions")
    op.execute(sa.text("DROP INDEX IF EXISTS ix_events_trial_occurred"))
    op.drop_column("events", "details")
    op.drop_column("events", "is_trial")
    op.drop_constraint("ck_ai_modules_mode", "ai_modules", type_="check")
    op.drop_column("ai_modules", "mode")
