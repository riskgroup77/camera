"""Institut tuzilmasi (org_units), xodimning bo'linmasi/lavozimi va
ro'yxatdan o'tishdagi chap/o'ng yuz rasmlari.

Revision ID: n2a2b3c4d5e6
Revises: l2a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "n2a2b3c4d5e6"
down_revision = "l2a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "org_units",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("hemis_id", sa.String(), nullable=True, unique=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False, server_default="boshqa"),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("org_units.id", ondelete="SET NULL"), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_org_units_parent_id", "org_units", ["parent_id"])
    op.add_column(
        "students_staff",
        sa.Column("org_unit_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("org_units.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column("students_staff", sa.Column("position", sa.String(), nullable=True))
    op.add_column("students_staff", sa.Column("biometric_photo_left_key", sa.String(), nullable=True))
    op.add_column("students_staff", sa.Column("biometric_photo_right_key", sa.String(), nullable=True))
    op.create_index("ix_students_staff_org_unit_id", "students_staff", ["org_unit_id"])


def downgrade() -> None:
    op.drop_index("ix_students_staff_org_unit_id", table_name="students_staff")
    op.drop_column("students_staff", "biometric_photo_right_key")
    op.drop_column("students_staff", "biometric_photo_left_key")
    op.drop_column("students_staff", "position")
    op.drop_column("students_staff", "org_unit_id")
    op.drop_index("ix_org_units_parent_id", table_name="org_units")
    op.drop_table("org_units")
