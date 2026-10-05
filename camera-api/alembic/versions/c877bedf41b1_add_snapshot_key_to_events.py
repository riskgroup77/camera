"""add snapshot_key to events

Revision ID: c877bedf41b1
Revises: 2b4b0b711ae0
Create Date: 2026-08-28 19:48:07.276683

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c877bedf41b1'
down_revision: Union[str, None] = '2b4b0b711ae0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('events', sa.Column('snapshot_key', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('events', 'snapshot_key')
