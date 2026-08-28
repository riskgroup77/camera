"""add mac_address to cameras

Revision ID: 2b4b0b711ae0
Revises: a1b2c3d4e5f6
Create Date: 2026-08-28 10:49:31.152097

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2b4b0b711ae0'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('cameras', sa.Column('mac_address', sa.String(), nullable=True))
    op.create_index(op.f('ix_cameras_mac_address'), 'cameras', ['mac_address'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_cameras_mac_address'), table_name='cameras')
    op.drop_column('cameras', 'mac_address')
