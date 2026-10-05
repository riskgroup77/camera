"""Dars jadvali asosidagi davomat jadvali

Davomat shu paytgacha kun bo'yicha hisoblanardi: kamera odamni tanidi ->
o'sha kunga bitta qator. Bu institutning haqiqiy savoliga javob bermaydi
— kirish eshigidan o'tib, keyin darsga kirmagan talaba kun bo'yicha
"keldi" bo'lib qolaverardi. Bu jadval dars darajasidagi javobni saqlaydi:
kim qaysi darsda bo'ldi, birinchi marta qachon ko'rindi, necha marta.

To'ldirish uchun qo'shimcha kamera so'rovi qilinmaydi — batafsil izoh
app/jobs/lesson_attendance.py docstringida.

Revision ID: d8e9f0a1b2c3
Revises: c4d5e6f7a8b9
Create Date: 2026-09-07
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d8e9f0a1b2c3"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lesson_attendance",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("lesson_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("student_staff_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sightings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["lesson_session_id"], ["lesson_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_staff_id"], ["students_staff.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # status NULL = dars hali tugamagan / yakunlanmagan. Bu holat
        # "kelmadi" dan qat'iy farq qiladi va shu sabab ruxsat etilgan.
        sa.CheckConstraint(
            "status IS NULL OR status IN ('keldi', 'kech_keldi', 'kelmadi')",
            name="ck_lesson_attendance_status",
        ),
        sa.UniqueConstraint("lesson_session_id", "student_staff_id", name="uq_lesson_attendance_person"),
    )
    op.create_index("ix_lesson_attendance_session", "lesson_attendance", ["lesson_session_id"])
    op.create_index("ix_lesson_attendance_student", "lesson_attendance", ["student_staff_id"])


def downgrade() -> None:
    op.drop_index("ix_lesson_attendance_student", table_name="lesson_attendance")
    op.drop_index("ix_lesson_attendance_session", table_name="lesson_attendance")
    op.drop_table("lesson_attendance")
