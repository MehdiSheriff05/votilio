"""sender display name

Revision ID: f6d4c2b8e0a3
Revises: e5c3b1a7d9f2
Create Date: 2026-10-18 07:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "f6d4c2b8e0a3"
down_revision = "e5c3b1a7d9f2"
branch_labels = None
depends_on = None


def upgrade():
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("system_settings")}
    if "mail_sender_name" not in cols:
        with op.batch_alter_table("system_settings") as batch:
            batch.add_column(sa.Column("mail_sender_name", sa.String(128), nullable=True))


def downgrade():
    with op.batch_alter_table("system_settings") as batch:
        batch.drop_column("mail_sender_name")
