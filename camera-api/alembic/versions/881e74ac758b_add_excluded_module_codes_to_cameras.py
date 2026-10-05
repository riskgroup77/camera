"""add excluded_module_codes to cameras

Revision ID: 881e74ac758b
Revises: a3acff7e6c11
Create Date: 2026-08-25 12:43:10.804736

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '881e74ac758b'
down_revision: Union[str, None] = 'a3acff7e6c11'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('cameras', sa.Column('excluded_module_codes', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('cameras', 'excluded_module_codes')
