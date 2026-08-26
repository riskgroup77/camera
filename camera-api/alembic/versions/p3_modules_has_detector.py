"""Enable has_detector for P3 modules 12, 13, 15, 18."""

from alembic import op

revision = "p3_modules_has_detector"
down_revision = "31f957220215"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE ai_modules
        SET has_detector = true
        WHERE code IN (12, 13, 15, 18)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE ai_modules
        SET has_detector = false
        WHERE code IN (12, 13, 15, 18)
        """
    )
