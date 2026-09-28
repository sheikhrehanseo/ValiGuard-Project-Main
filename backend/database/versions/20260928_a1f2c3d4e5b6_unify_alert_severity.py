"""unify alert severity to 4-tier scale

Alerts previously used the INFO/WARNING/ERROR/CRITICAL scale. The canonical
scale (backend/core/severity.py, FR-10) is LOW/MEDIUM/HIGH/CRITICAL, shared
with anomaly_detections. Data migration maps the old values onto the new
tiers: info->low, warning->medium, error->high.

Revision ID: a1f2c3d4e5b6
Revises: 73004a4a6ea8
Create Date: 2026-09-28 19:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1f2c3d4e5b6'
down_revision: Union[str, None] = '73004a4a6ea8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_ENUM = sa.Enum('INFO', 'WARNING', 'ERROR', 'CRITICAL', name='alertseverity')
_NEW_ENUM = sa.Enum('LOW', 'MEDIUM', 'HIGH', 'CRITICAL', name='severitylevel')


def upgrade() -> None:
    # 1) Remap stored values onto the canonical tiers BEFORE touching the
    #    column type, so the CHECK constraint never sees a bad value.
    op.execute("UPDATE alerts SET severity = 'LOW' WHERE severity = 'INFO'")
    op.execute("UPDATE alerts SET severity = 'MEDIUM' WHERE severity = 'WARNING'")
    op.execute("UPDATE alerts SET severity = 'HIGH' WHERE severity = 'ERROR'")

    # 2) Swap the enum (batch mode recreates the table on SQLite).
    with op.batch_alter_table('alerts') as batch_op:
        batch_op.alter_column(
            'severity',
            existing_type=_OLD_ENUM,
            type_=_NEW_ENUM,
            existing_nullable=False,
        )


def downgrade() -> None:
    # Reverse the value mapping, losing the Low tier distinction (low -> info).
    op.execute("UPDATE alerts SET severity = 'INFO' WHERE severity = 'LOW'")
    op.execute("UPDATE alerts SET severity = 'WARNING' WHERE severity = 'MEDIUM'")
    op.execute("UPDATE alerts SET severity = 'ERROR' WHERE severity = 'HIGH'")

    with op.batch_alter_table('alerts') as batch_op:
        batch_op.alter_column(
            'severity',
            existing_type=_NEW_ENUM,
            type_=_OLD_ENUM,
            existing_nullable=False,
        )
