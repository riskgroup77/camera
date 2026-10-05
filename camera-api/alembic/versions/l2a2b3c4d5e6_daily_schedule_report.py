"""Avtomatik hisobot: kunlik davr va "jadval bo'yicha davomat".

Revision ID: l2a2b3c4d5e6
Revises: k2a2b3c4d5e6
"""

from alembic import op

revision = "l2a2b3c4d5e6"
down_revision = "k2a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_report_schedules_kind", "report_schedules", type_="check")
    op.drop_constraint("ck_report_schedules_report", "report_schedules", type_="check")
    op.create_check_constraint("ck_report_schedules_kind", "report_schedules", "kind IN ('kunlik', 'haftalik', 'oylik')")
    op.create_check_constraint(
        "ck_report_schedules_report",
        "report_schedules",
        "report IN ('kpi', 'davomat_xodim', 'davomat_talaba', 'tabel_xodim', 'tabel_talaba', 'jadval_davomat')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_report_schedules_kind", "report_schedules", type_="check")
    op.drop_constraint("ck_report_schedules_report", "report_schedules", type_="check")
    op.create_check_constraint("ck_report_schedules_kind", "report_schedules", "kind IN ('haftalik', 'oylik')")
    op.create_check_constraint(
        "ck_report_schedules_report",
        "report_schedules",
        "report IN ('kpi', 'davomat_xodim', 'davomat_talaba', 'tabel_xodim', 'tabel_talaba')",
    )
