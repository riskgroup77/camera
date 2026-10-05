"""Rol tekshiruvlari: hodisalar, davomat, tashkiliy tuzilma, dars jadvali

Bu bo'limlarning endpointlari faqat "tizimga kirgan" bo'lishni talab
qilardi — kamera mas'uli (m6a7b8c9d0e1) ham hodisalarni o'chira,
davomatni tuzata va fakultetlarni o'chira olardi. Endi har biri alohida
huquq kaliti ostida va "Foydalanuvchilar va Rollar" sahifasidan
boshqariladi.

Admin va super-admin uchun hech narsa o'zgarmaydi, bitta istisno bilan:
hodisani butunlay o'chirish endi faqat super-admin'da (deleteEvents).

ON CONFLICT DO NOTHING: kalit qandaydir yo'l bilan allaqachon qo'shilgan
bo'lsa, admin qo'lda o'rnatgan qiymat ustidan yozilmaydi.

Revision ID: n7b8c9d0e1f2
Revises: m6a7b8c9d0e1
Create Date: 2026-09-17
"""

from alembic import op

revision = "n7b8c9d0e1f2"
down_revision = "m6a7b8c9d0e1"
branch_labels = None
depends_on = None

# key -> (super_admin, admin, camera_steward); app/seed.py bilan bir xil.
NEW_PERMISSIONS = {
    "reviewEvents": (True, True, False),
    "deleteEvents": (True, False, False),
    "manageAttendance": (True, True, False),
    "manageOrgStructure": (True, True, False),
    "manageLessons": (True, True, False),
}


def _sql_bool(value: bool) -> str:
    return "true" if value else "false"


def upgrade() -> None:
    for key, (super_admin, admin, camera_steward) in NEW_PERMISSIONS.items():
        op.execute(
            "INSERT INTO permissions (key, super_admin, admin, camera_steward) "
            f"VALUES ('{key}', {_sql_bool(super_admin)}, {_sql_bool(admin)}, {_sql_bool(camera_steward)}) "
            "ON CONFLICT (key) DO NOTHING"
        )


def downgrade() -> None:
    keys = ", ".join(f"'{key}'" for key in NEW_PERMISSIONS)
    op.execute(f"DELETE FROM permissions WHERE key IN ({keys})")
