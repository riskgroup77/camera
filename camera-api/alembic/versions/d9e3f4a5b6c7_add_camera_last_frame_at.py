"""Add cameras.last_frame_at.

Camera health proved the camera answers on its RTSP port and nothing
more. Measured on production: 6 of 107 cameras showed "JONLI" on the
wall while their decoder produced only a flat grey picture — reachable,
and blind. Nothing in the system could tell those two states apart.

Revision ID: d9e3f4a5b6c7
Revises: c8d2e3f4a5b6
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d9e3f4a5b6c7"
down_revision: Union[str, None] = "c8d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cameras", sa.Column("last_frame_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("cameras", "last_frame_at")
