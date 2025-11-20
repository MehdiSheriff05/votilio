"""add invitee name column

Revision ID: 6b7ddfa24b2c
Revises: 3ce26afb2548
Create Date: 2025-11-19 03:24:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6b7ddfa24b2c'
down_revision = '3ce26afb2548'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('voter_invitation', schema=None) as batch_op:
        batch_op.add_column(sa.Column('name', sa.String(length=255), nullable=True))


def downgrade():
    with op.batch_alter_table('voter_invitation', schema=None) as batch_op:
        batch_op.drop_column('name')
