"""Add departments (kafedra) and link cameras to them.

Cameras were grouped by building only. One building holds dozens of
departments, so an operator looking for "the Biophysics department's
cameras" had to page through the whole building — 107 cameras with no
way to narrow past the first level.

Camera.department_id is separate from building_id rather than derived
through it: a camera whose department has not been assigned yet must
keep filtering by building, and every one of the 107 starts that way.

Revision ID: e1f2a3b4c5d6
Revises: d9e3f4a5b6c7
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "d9e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "building_id",
            UUID(as_uuid=True),
            sa.ForeignKey("buildings.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_departments_building_id", "departments", ["building_id"])

    op.add_column("cameras", sa.Column("department_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_cameras_department_id", "cameras", "departments", ["department_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_cameras_department_id", "cameras", ["department_id"])


def downgrade() -> None:
    op.drop_index("ix_cameras_department_id", table_name="cameras")
    op.drop_constraint("fk_cameras_department_id", "cameras", type_="foreignkey")
    op.drop_column("cameras", "department_id")
    op.drop_index("ix_departments_building_id", table_name="departments")
    op.drop_table("departments")
