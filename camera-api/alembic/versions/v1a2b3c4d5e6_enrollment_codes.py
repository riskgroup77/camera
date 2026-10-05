"""Guruh/bo'lim uchun ro'yxatdan o'tish kodi (enrollment_codes).

Revision ID: v1a2b3c4d5e6
Revises: u1a2b3c4d5e6
Create Date: 2026-09-20

Ochiq ro'yxatdan o'tish sahifasi shu paytgacha faqat JSHSHIRga tayanardi,
JSHSHIR esa sir emas. Endi topshirish uchun guruhning kodi ham kerak.

MAVJUD GURUHLARGA KOD SHU YERDA YARATILADI. Aks holda migratsiyadan
keyingi birinchi kunda hech kim ro'yxatdan o'ta olmay qolardi: kod
majburiy, lekin bironta ham kod yo'q edi. Admin kodlarni panelda ko'radi
va xohlaganini yangilaydi.
"""

import secrets

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "v1a2b3c4d5e6"
down_revision = "u1a2b3c4d5e6"
branch_labels = None
depends_on = None

# app/services/enrollment_code.py dagi alifbo bilan AYNAN bir xil
# (O, 0, I, 1 yo'q — ular og'zaki aytilganda chalkashadi).
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6


def _code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def upgrade() -> None:
    op.create_table(
        "enrollment_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("unit_key", sa.String(160), nullable=False),
        sa.Column("unit_name", sa.String(160), nullable=False, server_default=""),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("scope IN ('guruh', 'bolim', 'umumiy')", name="ck_enrollment_codes_scope"),
        sa.UniqueConstraint("scope", "unit_key", name="uq_enrollment_codes_scope_unit"),
    )

    bind = op.get_bind()
    rows: list[tuple[str, str, str]] = []

    # Talabalar guruhlari. Bitta nom ikki fakultetda uchrashi mumkin —
    # kalit bo'yicha yagonalashtiramiz (kod baribir nom bo'yicha topiladi).
    seen: set[tuple[str, str]] = set()
    for (name,) in bind.execute(sa.text("SELECT name FROM student_groups")):
        key = " ".join((name or "").split()).lower()
        if not key or ("guruh", key) in seen:
            continue
        seen.add(("guruh", key))
        rows.append(("guruh", key, " ".join((name or "").split())))

    # Talabalar jadvalidagi guruh nomlari (student_groups'da bo'lmasligi mumkin).
    for (name,) in bind.execute(
        sa.text("SELECT DISTINCT group_or_position FROM students_staff WHERE type = 'talaba'")
    ):
        key = " ".join((name or "").split()).lower()
        if not key or ("guruh", key) in seen:
            continue
        seen.add(("guruh", key))
        rows.append(("guruh", key, " ".join((name or "").split())))

    # Xodimlar bo'limlari — fakultet nomi bo'yicha.
    for (name,) in bind.execute(sa.text("SELECT name FROM faculties")):
        key = " ".join((name or "").split()).lower()
        if not key or ("bolim", key) in seen:
            continue
        seen.add(("bolim", key))
        rows.append(("bolim", key, " ".join((name or "").split())))

    # Zaxira: fakulteti belgilanmagan xodim va o'zini o'zi qo'shgan odam.
    rows.append(("umumiy", "", "Butun institut"))

    if rows:
        bind.execute(
            sa.text(
                "INSERT INTO enrollment_codes (scope, unit_key, unit_name, code) "
                "VALUES (:scope, :unit_key, :unit_name, :code) ON CONFLICT DO NOTHING"
            ),
            [{"scope": s, "unit_key": k, "unit_name": n, "code": _code()} for s, k, n in rows],
        )


def downgrade() -> None:
    op.drop_table("enrollment_codes")
