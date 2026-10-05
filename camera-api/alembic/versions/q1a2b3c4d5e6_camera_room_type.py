"""Kamera xona turi va xona raqami

AI modullari endi kameraning xona turiga qarab yo'naltiriladi
(app/services/camera_roles.py): uyqu faqat auditoriyada, oq xalat va
qo'lqop/niqob faqat laboratoriyada, kunlik davomat faqat kirishda. Xona
raqami dars jadvalini kameraga bog'laydi.

Boshlang'ich to'ldirish: kirish/chiqish yoki perimetr belgisi YO'Q va nomi
"27-xona" / "211" ko'rinishidagi kameralar auditoriya deb belgilanadi,
raqami room_code ga yoziladi. Belgili kameralarga tegilmaydi: ularning turi
bayroqdan olinadi ("211" nomli kirish kamerasi auditoriya bo'lib qolsa,
davomat kuzatuvi to'xtab qolardi). Qolganlarini admin CSV orqali belgilaydi.

Revision ID: q1a2b3c4d5e6
Revises: p9d0e1f2a3b4
Create Date: 2026-09-18
"""

import re

import sqlalchemy as sa
from alembic import op

revision = "q1a2b3c4d5e6"
down_revision = "p9d0e1f2a3b4"
branch_labels = None
depends_on = None

_ROOM_NAME = re.compile(r"^\s*(\d{1,4}[a-zа-я]?)\s*-?\s*(xona|xonasi)?\s*$", re.IGNORECASE)


def upgrade() -> None:
    op.add_column("cameras", sa.Column("room_type", sa.String(), nullable=True))
    op.add_column("cameras", sa.Column("room_code", sa.String(), nullable=True))
    op.create_index("ix_cameras_room_code", "cameras", ["room_code"])
    op.create_check_constraint(
        "ck_cameras_room_type",
        "cameras",
        "room_type IS NULL OR room_type IN "
        "('kirish', 'auditoriya', 'laboratoriya', 'koridor', 'ofis', 'cheklangan', 'tashqi')",
    )

    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, name FROM cameras WHERE NOT is_entrance AND NOT is_exit AND NOT is_perimeter")
    ).all()
    for camera_id, name in rows:
        match = _ROOM_NAME.match(name or "")
        if not match:
            continue
        connection.execute(
            sa.text("UPDATE cameras SET room_type = 'auditoriya', room_code = :code WHERE id = :id"),
            {"code": match.group(1).lower(), "id": camera_id},
        )


def downgrade() -> None:
    op.drop_constraint("ck_cameras_room_type", "cameras", type_="check")
    op.drop_index("ix_cameras_room_code", table_name="cameras")
    op.drop_column("cameras", "room_code")
    op.drop_column("cameras", "room_type")
