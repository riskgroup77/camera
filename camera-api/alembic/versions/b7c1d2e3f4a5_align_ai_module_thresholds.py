"""Align AIModuleConfig.threshold with what each module can emit.

Until now the column was write-only: the admin panel saved it, the admin
panel read it back, and no detection code consulted it. The values in it
were therefore aspirations, and several sit ABOVE the highest confidence
their module is capable of producing.

app/services/event_bus.py now enforces the column. Applying that to an
existing database without this migration would silently switch several
modules off — including fire detection, whose threshold was 90 while it
starts alerting at a fire-pixel fraction of 0.015, i.e. confidence 15.
Every real fire alert that did not fill 9% of the frame would have been
dropped.

Existing rows are corrected rather than left alone because no operator
can have tuned these deliberately: the control did nothing until now.
Only rows still holding the old default are touched, so a value someone
sets after this migration is never clobbered by a re-run.

Revision ID: b7c1d2e3f4a5
Revises: f6a7b8c9d0e1
"""

from typing import Sequence, Union

from alembic import op

revision: str = "b7c1d2e3f4a5"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# code -> (old default we expect to find, new value = lowest confidence
# the module can actually emit; see app/seed.py's DEFAULT_AI_MODULES).
THRESHOLDS: dict[int, tuple[int, int]] = {
    1: (85, 70),
    2: (80, 65),
    4: (75, 55),
    5: (78, 60),
    10: (55, 40),
    11: (55, 40),
    12: (70, 35),
    13: (85, 40),
    14: (88, 35),
    15: (75, 35),
    16: (80, 50),
    17: (65, 55),
    18: (70, 35),
    22: (85, 70),
    23: (90, 15),
    24: (85, 65),
    25: (75, 50),
}


def upgrade() -> None:
    for code, (old, new) in THRESHOLDS.items():
        op.execute(
            f"UPDATE ai_modules SET threshold = {new} WHERE code = {code} AND threshold = {old}"
        )


def downgrade() -> None:
    for code, (old, new) in THRESHOLDS.items():
        op.execute(
            f"UPDATE ai_modules SET threshold = {old} WHERE code = {code} AND threshold = {new}"
        )
