"""add is_entrance to cameras

Revision ID: 8308cbd7e4cc
Revises: 881e74ac758b
Create Date: 2026-08-25 13:37:45.575546

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8308cbd7e4cc'
down_revision: Union[str, None] = '881e74ac758b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('cameras', sa.Column('is_entrance', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('cameras', 'is_entrance')
