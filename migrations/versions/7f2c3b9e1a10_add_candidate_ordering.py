"""add candidate ordering

Revision ID: 7f2c3b9e1a10
Revises: 1c7e1d5a3c2a
Create Date: 2026-01-27 01:10:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7f2c3b9e1a10"
down_revision = "1c7e1d5a3c2a"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("candidate", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("order_index", sa.Integer(), nullable=False, server_default=sa.text("0"))
        )

    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, position_id FROM candidate ORDER BY position_id, id")
    ).fetchall()
    current_position = None
    index = 0
    for row in rows:
        if row.position_id != current_position:
            current_position = row.position_id
            index = 0
        bind.execute(
            sa.text("UPDATE candidate SET order_index = :idx WHERE id = :cid"),
            {"idx": index, "cid": row.id},
        )
        index += 1

    with op.batch_alter_table("candidate", schema=None) as batch_op:
        batch_op.alter_column("order_index", server_default=None)


def downgrade():
    with op.batch_alter_table("candidate", schema=None) as batch_op:
        batch_op.drop_column("order_index")
