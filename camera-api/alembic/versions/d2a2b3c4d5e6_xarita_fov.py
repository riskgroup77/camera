"""Xarita: kamera ko'rish burchagi (plan_fov) va reja yangilangan vaqti.

Qavat rejalari jadvali (floor_plans) va kameraning rejadagi joyi
(plan_x/plan_y/plan_rotation) s1a2b3c4d5e6 da allaqachon bor — bu yerda
faqat yetishmagan ikki ustun qo'shiladi.

Revision ID: d2a2b3c4d5e6
Revises: b2a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op

revision = "d2a2b3c4d5e6"
down_revision = "b2a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column("plan_fov", sa.SmallInteger(), nullable=False, server_default="70"),
    )
    op.add_column(
        "floor_plans",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_column("floor_plans", "updated_at")
    op.drop_column("cameras", "plan_fov")
