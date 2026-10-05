"""Kampus kesimi: bino qavatlari va kamera qavati

Video Monitoring Markazi bino -> qavat -> kamera bo'lib ochilishi kerak
(buyurtmachi talabi, 2026-09-16): shunda bir sahifada 100+ kamera emas,
faqat tanlangan qavatdagilar yuklanadi. Buning uchun kameraning qaysi
qavatda turgani kerak, hozir bu ma'lumot faqat zona matnida
("3-qavat koridor") tasodifiy uchraydi.

- cameras.floor — qavat raqami. NULL = belgilanmagan: bunday kameralar
  UI'da "Qavat belgilanmagan" guruhida ko'rinadi, ya'ni yo'qolmaydi.
- buildings.floors — binodagi qavatlar soni, kamerasi yo'q qavat ham
  kesimda ko'rinsin.
- buildings.sort_order — binolar tartibi: nom bo'yicha saralash
  "10-bino"ni "2-bino"dan oldin qo'yadi.

Mavjud zona/nom matnidan qavat bir marta ko'chiriladi ("3-qavat",
"3 qavat", "3-QAVAT"). Xato chiqqani admin panelidan tuzatiladi.

Revision ID: j3d4e5f6a7b8
Revises: i2c3d4e5f6a7
Create Date: 2026-09-16
"""

from alembic import op
import sqlalchemy as sa

revision = "j3d4e5f6a7b8"
down_revision = "i2c3d4e5f6a7"
branch_labels = None
depends_on = None

# 1..30 oralig'i — "2024-qavat" kabi tasodifiy moslik olinmasin.
_FLOOR_FROM = (
    "UPDATE cameras SET floor = sub.value::smallint FROM ("
    r"  SELECT id, (regexp_match({column}, '([0-9]{{1,2}})\s*-?\s*qavat', 'i'))[1] AS value FROM cameras"
    ") sub WHERE cameras.id = sub.id AND cameras.floor IS NULL"
    " AND sub.value IS NOT NULL AND sub.value::int BETWEEN 1 AND 30"
)


def upgrade() -> None:
    op.add_column("cameras", sa.Column("floor", sa.SmallInteger(), nullable=True))
    op.add_column("buildings", sa.Column("floors", sa.SmallInteger(), nullable=True))
    op.add_column("buildings", sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_cameras_building_floor", "cameras", ["building_id", "floor"])

    op.execute(sa.text(_FLOOR_FROM.format(column="zone")))
    op.execute(sa.text(_FLOOR_FROM.format(column="name")))
    op.execute(
        sa.text(
            "UPDATE buildings SET floors = sub.max_floor FROM ("
            "  SELECT building_id, MAX(floor) AS max_floor FROM cameras"
            "  WHERE floor IS NOT NULL AND building_id IS NOT NULL GROUP BY building_id"
            ") sub WHERE buildings.id = sub.building_id"
        )
    )
    op.execute(
        sa.text("UPDATE buildings SET sort_order = COALESCE(((regexp_match(name, '([0-9]{1,3})'))[1])::int, 999)")
    )


def downgrade() -> None:
    op.drop_index("ix_cameras_building_floor", table_name="cameras")
    op.drop_column("buildings", "sort_order")
    op.drop_column("buildings", "floors")
    op.drop_column("cameras", "floor")
