"""Add reports.sections.

The report was five numbers and two sentences. Everything that would let
a reader act on it — which module raised the alerts, which camera, at
what hour, how the attendance figure is actually made up — had to be
inferred or asked for separately.

Nullable, and existing rows are left alone: a report records what the
data said at the moment it was generated, and back-filling sections now
would attach today's numbers to yesterday's document.

Revision ID: c8d2e3f4a5b6
Revises: b7c1d2e3f4a5
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "c8d2e3f4a5b6"
down_revision: Union[str, None] = "b7c1d2e3f4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("sections", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("reports", "sections")
