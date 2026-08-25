"""add has_detector to ai_modules

Revision ID: 31f957220215
Revises: 8308cbd7e4cc
Create Date: 2026-08-25 14:41:30.518571

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '31f957220215'
down_revision: Union[str, None] = '8308cbd7e4cc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('ai_modules', sa.Column('has_detector', sa.Boolean(), nullable=False, server_default=sa.true()))
    # The 4 registry-only criteria with no detector code at all (see
    # app/seed.py's DEFAULT_AI_MODULES) — every other criterion already
    # has a real app/jobs/*.py sweep behind it, just not yet benchmarked.
    op.execute("UPDATE ai_modules SET has_detector = false WHERE code IN (12, 13, 15, 18)")
    # Code 1 (Notanish/begona shaxsni aniqlash) has a real InsightFace
    # detector (app/jobs/unauthorized_person_ai.py) and was meant to
    # default active=True per app/seed.py, but this production row
    # predates that default and got stuck inactive — the old accuracy==0
    # gate this migration replaces then blocked re-enabling it from the
    # admin UI. Correcting it here since it was never a deliberate
    # "turn this off" admin decision, just the stale gate.
    op.execute("UPDATE ai_modules SET active = true WHERE code = 1")


def downgrade() -> None:
    op.drop_column('ai_modules', 'has_detector')
