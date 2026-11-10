"""Preserve transaction amount units without assuming units for legacy rows."""

from alembic import op
import sqlalchemy as sa

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("validators") as batch:
        batch.alter_column("uptime_percentage", existing_type=sa.Float(), nullable=True)
    with op.batch_alter_table("transactions") as batch:
        batch.add_column(sa.Column("asset_symbol", sa.String(50), nullable=True))
        batch.add_column(sa.Column("asset_address", sa.String(255), nullable=True))
    # Older token quantities occupied the same value column. Only known native
    # routes can safely be labelled; unknown legacy units stay unknown.
    op.execute("UPDATE transactions SET asset_symbol = 'QIE' "
               "WHERE source_chain = 'QIE Native Transfer' AND sender IS NOT NULL")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM validators WHERE uptime_percentage IS NULL")).scalar():
        raise RuntimeError("Cannot downgrade unknown uptime to a required percentage without supplying measured values")
    with op.batch_alter_table("validators") as batch:
        batch.alter_column("uptime_percentage", existing_type=sa.Float(), nullable=False)
    with op.batch_alter_table("transactions") as batch:
        batch.drop_column("asset_address")
        batch.drop_column("asset_symbol")
