"""presence_visits jadvali — kim qaysi kamera oldida qachon bo'lgani

Kunlik davomat kuniga bitta qator saqlaydi va "o'qituvchi soat 11 da
qayerda edi, darsiga kirdimi" degan savolga javob bera olmaydi. Bu jadval
yuz tanishni kamera bo'yicha tashriflarga yig'ib saqlaydi — qarang
app/models/presence_visit.py.

Revision ID: c3d4e5f6a7b8
Revises: b7e2c9d4a1f3
Create Date: 2026-09-15
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c3d4e5f6a7b8"
down_revision = "b7e2c9d4a1f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "presence_visits",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("student_staff_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("camera_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sightings", sa.Integer(), server_default="1", nullable=False),
        sa.Column("best_similarity", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["student_staff_id"], ["students_staff.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_presence_visits_person_last_seen", "presence_visits", ["student_staff_id", "last_seen_at"])
    op.create_index("ix_presence_visits_camera_last_seen", "presence_visits", ["camera_id", "last_seen_at"])
    op.create_index("ix_presence_visits_first_seen", "presence_visits", ["first_seen_at"])


def downgrade() -> None:
    op.drop_index("ix_presence_visits_first_seen", table_name="presence_visits")
    op.drop_index("ix_presence_visits_camera_last_seen", table_name="presence_visits")
    op.drop_index("ix_presence_visits_person_last_seen", table_name="presence_visits")
    op.drop_table("presence_visits")
