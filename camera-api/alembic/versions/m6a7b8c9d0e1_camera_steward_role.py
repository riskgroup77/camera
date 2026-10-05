"""Yangi rol: Kamera mas'uli

Buyurtmachi talabi (2026-09-16): kamera ma'lumotlarini — qaysi binoda,
qaysi qavatda, qaysi xonada ekanini — to'g'rilaydigan xodimlar uchun
alohida rol. Ular faqat ikkita sahifani ko'radi ("Tashkiliy tuzilma" va
"Kameralar va Zonalar") va kameraning ULANISH sozlamalariga (IP, port,
RTSP yo'li, login/parol) umuman tegmaydi — bu ma'lumotlar ular
yuboradigan so'rovda umuman bo'lmaydi.

O'zgarishlar:
- users.role cheklovi uchinchi qiymatni qabul qiladi;
- permissions jadvaliga camera_steward ustuni;
- yangi huquq kaliti "editCameraLocation" — uchala rolda ham bor, ya'ni
  admin va super-admin uchun hech narsa o'zgarmaydi.

Revision ID: m6a7b8c9d0e1
Revises: l5f6a7b8c9d0
Create Date: 2026-09-16
"""

from alembic import op
import sqlalchemy as sa

revision = "m6a7b8c9d0e1"
down_revision = "l5f6a7b8c9d0"
branch_labels = None
depends_on = None

ROLE_CHECK = "role IN ('super-admin', 'admin', 'kamera-masuli')"
OLD_ROLE_CHECK = "role IN ('super-admin', 'admin')"


def upgrade() -> None:
    op.add_column(
        "permissions",
        sa.Column("camera_steward", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_role")
    op.create_check_constraint("ck_users_role", "users", ROLE_CHECK)
    op.execute(
        "INSERT INTO permissions (key, super_admin, admin, camera_steward) "
        "VALUES ('editCameraLocation', true, true, true) "
        "ON CONFLICT (key) DO UPDATE SET camera_steward = true"
    )


def downgrade() -> None:
    """Rolda foydalanuvchi qolgan bo'lsa ATAYLAB xato beradi: ularni
    jimgina o'chirish yoki rolini o'zgartirish ma'lumotni yo'qotish
    bo'lardi. Avval foydalanuvchilarni boshqa rolga o'tkazing."""
    op.execute("DELETE FROM permissions WHERE key = 'editCameraLocation'")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_role")
    op.create_check_constraint("ck_users_role", "users", OLD_ROLE_CHECK)
    op.drop_column("permissions", "camera_steward")
