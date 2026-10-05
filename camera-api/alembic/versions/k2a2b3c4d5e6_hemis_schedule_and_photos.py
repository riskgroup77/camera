"""HEMIS: dars jadvali (auditoriya, bino, tugash vaqti) va talaba/xodim rasmi.

Revision ID: k2a2b3c4d5e6
Revises: j2a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op

revision = "k2a2b3c4d5e6"
down_revision = "j2a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # HEMIS schedule-list identifikatori — qayta sinxronlashda takror qator
    # yaratilmaydi, o'zgargan dars yangilanadi.
    op.add_column("lesson_sessions", sa.Column("hemis_id", sa.String(), nullable=True))
    op.create_index("ix_lesson_sessions_hemis_id", "lesson_sessions", ["hemis_id"], unique=True)
    op.add_column("lesson_sessions", sa.Column("auditorium", sa.String(), nullable=True))
    op.add_column("lesson_sessions", sa.Column("building", sa.String(), nullable=True))
    op.add_column("lesson_sessions", sa.Column("scheduled_end_time", sa.DateTime(timezone=True), nullable=True))
    # HEMIS'dagi rasm (image_full) — yuzi yo'q odamni shu rasmdan tanitish uchun.
    op.add_column("students_staff", sa.Column("hemis_photo_url", sa.String(), nullable=True))
    op.add_column("students_staff", sa.Column("hemis_photo_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("students_staff", sa.Column("hemis_photo_error", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("students_staff", "hemis_photo_error")
    op.drop_column("students_staff", "hemis_photo_checked_at")
    op.drop_column("students_staff", "hemis_photo_url")
    op.drop_column("lesson_sessions", "scheduled_end_time")
    op.drop_column("lesson_sessions", "building")
    op.drop_column("lesson_sessions", "auditorium")
    op.drop_index("ix_lesson_sessions_hemis_id", table_name="lesson_sessions")
    op.drop_column("lesson_sessions", "hemis_id")
