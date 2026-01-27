"""add candidate status and winner override

Revision ID: 4c2f1a9f0b12
Revises: 7f2c3b9e1a10
Create Date: 2026-01-27 02:05:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "4c2f1a9f0b12"
down_revision = "7f2c3b9e1a10"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("candidate", schema=None) as batch_op:
        batch_op.add_column(sa.Column("is_declined", sa.Boolean(), nullable=False, server_default=sa.text("false")))
        batch_op.add_column(sa.Column("is_disqualified", sa.Boolean(), nullable=False, server_default=sa.text("false")))

    with op.batch_alter_table("position", schema=None) as batch_op:
        batch_op.add_column(sa.Column("winner_override_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_position_winner_override_candidate",
            "candidate",
            ["winner_override_id"],
            ["id"],
        )

    with op.batch_alter_table("candidate", schema=None) as batch_op:
        batch_op.alter_column("is_declined", server_default=None)
        batch_op.alter_column("is_disqualified", server_default=None)


def downgrade():
    with op.batch_alter_table("position", schema=None) as batch_op:
        batch_op.drop_constraint("fk_position_winner_override_candidate", type_="foreignkey")
        batch_op.drop_column("winner_override_id")

    with op.batch_alter_table("candidate", schema=None) as batch_op:
        batch_op.drop_column("is_disqualified")
        batch_op.drop_column("is_declined")
