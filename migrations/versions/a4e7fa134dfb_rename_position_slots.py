"""rename position slots

Revision ID: a4e7fa134dfb
Revises: d50dfec712f8
Create Date: 2025-11-18 05:56:37.571253

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a4e7fa134dfb'
down_revision = 'd50dfec712f8'
branch_labels = None
depends_on = None


def upgrade():
    position_table = sa.table(
        'position',
        sa.column('id', sa.Integer),
        sa.column('candidate_slots', sa.Integer),
        sa.column('max_selections', sa.Integer),
    )

    with op.batch_alter_table('position', schema=None) as batch_op:
        batch_op.add_column(sa.Column('candidate_slots', sa.Integer(), nullable=True))

    bind = op.get_bind()
    bind.execute(
        position_table.update().values(candidate_slots=position_table.c.max_selections)
    )

    with op.batch_alter_table('position', schema=None) as batch_op:
        batch_op.alter_column('candidate_slots', existing_type=sa.Integer(), nullable=False, existing_nullable=True)
        batch_op.drop_column('max_selections')


def downgrade():
    position_table = sa.table(
        'position',
        sa.column('id', sa.Integer),
        sa.column('candidate_slots', sa.Integer),
        sa.column('max_selections', sa.Integer),
    )

    with op.batch_alter_table('position', schema=None) as batch_op:
        batch_op.add_column(sa.Column('max_selections', sa.Integer(), nullable=True))

    bind = op.get_bind()
    bind.execute(
        position_table.update().values(max_selections=position_table.c.candidate_slots)
    )

    with op.batch_alter_table('position', schema=None) as batch_op:
        batch_op.alter_column('max_selections', existing_type=sa.Integer(), nullable=False, existing_nullable=True)
        batch_op.drop_column('candidate_slots')
