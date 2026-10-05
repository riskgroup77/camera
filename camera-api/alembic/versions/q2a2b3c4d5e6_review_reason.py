"""Yuz tekshiruvga qolgan sabab (students_staff.biometrics_review_reason).

Revision ID: q2a2b3c4d5e6
Revises: p2a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op

revision = "q2a2b3c4d5e6"
down_revision = "p2a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("students_staff", sa.Column("biometrics_review_reason", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("students_staff", "biometrics_review_reason")
