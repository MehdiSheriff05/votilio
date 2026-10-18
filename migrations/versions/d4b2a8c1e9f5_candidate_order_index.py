"""candidate ordering (no-op when the 2026 migration already added it)

Revision ID: d4b2a8c1e9f5
Revises: c3a1f0d2b7e4
Create Date: 2026-10-18 03:10:00
"""
from alembic import op
import sqlalchemy as sa

revision = "d4b2a8c1e9f5"
down_revision = "c3a1f0d2b7e4"
branch_labels = None
depends_on = None


def upgrade():
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("candidate")}
    if "order_index" in cols:
        return
    with op.batch_alter_table("candidate") as batch:
        batch.add_column(sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"))
    op.execute("UPDATE candidate SET order_index = id")


def downgrade():
    pass
