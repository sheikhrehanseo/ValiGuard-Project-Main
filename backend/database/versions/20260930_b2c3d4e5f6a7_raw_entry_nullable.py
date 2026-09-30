"""allow honest NULL fields for undecoded raw transaction entries

Revision ID: b2c3d4e5f6a7
Revises: a1f2c3d4e5b6

Empty sender/receiver sentinels are converted to NULL. Existing zero values
and QIE chain labels are intentionally preserved because they may be genuine.
Downgrade restores sentinels and is lossy for raw-entry rows.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1f2c3d4e5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE transactions SET sender = NULL WHERE sender = ''")
    op.execute("UPDATE transactions SET receiver = NULL WHERE receiver = ''")

    with op.batch_alter_table("transactions") as batch_op:
        batch_op.alter_column(
            "sender", existing_type=sa.String(length=255), nullable=True
        )
        batch_op.alter_column(
            "receiver", existing_type=sa.String(length=255), nullable=True
        )
        batch_op.alter_column(
            "value", existing_type=sa.Float(), nullable=True
        )
        batch_op.alter_column(
            "source_chain", existing_type=sa.String(length=50), nullable=True
        )
        batch_op.alter_column(
            "destination_chain", existing_type=sa.String(length=50), nullable=True
        )
        batch_op.alter_column(
            "bridge_id", existing_type=sa.Integer(), nullable=True
        )


def downgrade() -> None:
    connection = op.get_bind()
    bridge_id = connection.execute(
        sa.text("SELECT id FROM bridges ORDER BY id LIMIT 1")
    ).scalar()
    if bridge_id is None:
        connection.execute(
            sa.text(
                "INSERT INTO bridges "
                "(address, chain_name, status, created_at, last_verified_at) "
                "VALUES ('migration:downgrade:default', 'QIE', 'ACTIVE', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        bridge_id = connection.execute(
            sa.text("SELECT id FROM bridges WHERE address = 'migration:downgrade:default'")
        ).scalar()

    connection.execute(sa.text("UPDATE transactions SET sender = '' WHERE sender IS NULL"))
    connection.execute(sa.text("UPDATE transactions SET receiver = '' WHERE receiver IS NULL"))
    connection.execute(sa.text("UPDATE transactions SET value = 0.0 WHERE value IS NULL"))
    connection.execute(sa.text("UPDATE transactions SET source_chain = 'QIE' WHERE source_chain IS NULL"))
    connection.execute(sa.text("UPDATE transactions SET destination_chain = 'QIE' WHERE destination_chain IS NULL"))
    connection.execute(
        sa.text("UPDATE transactions SET bridge_id = :bridge_id WHERE bridge_id IS NULL"),
        {"bridge_id": bridge_id},
    )

    with op.batch_alter_table("transactions") as batch_op:
        batch_op.alter_column(
            "sender", existing_type=sa.String(length=255), nullable=False
        )
        batch_op.alter_column(
            "receiver", existing_type=sa.String(length=255), nullable=False
        )
        batch_op.alter_column(
            "value", existing_type=sa.Float(), nullable=False
        )
        batch_op.alter_column(
            "source_chain", existing_type=sa.String(length=50), nullable=False
        )
        batch_op.alter_column(
            "destination_chain", existing_type=sa.String(length=50), nullable=False
        )
        batch_op.alter_column(
            "bridge_id", existing_type=sa.Integer(), nullable=False
        )
