"""email provider switch: smtp or resend

Revision ID: c3a1f0d2b7e4
Revises: 4c2f1a9f0b12
Create Date: 2026-10-18 03:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "c3a1f0d2b7e4"
down_revision = "4c2f1a9f0b12"
branch_labels = None
depends_on = None


def _columns(table):
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    # Idempotent: a database deployed from an earlier v3 build may already have these.
    have = _columns("system_settings")
    with op.batch_alter_table("system_settings") as batch:
        if "email_provider" not in have:
            batch.add_column(sa.Column("email_provider", sa.String(16), nullable=False, server_default="smtp"))
        if "smtp_security" not in have:
            batch.add_column(sa.Column("smtp_security", sa.String(16), nullable=False, server_default="starttls"))
        if "resend_api_key" not in have:
            batch.add_column(sa.Column("resend_api_key", sa.String(512), nullable=True))


def downgrade():
    with op.batch_alter_table("system_settings") as batch:
        batch.drop_column("resend_api_key")
        batch.drop_column("smtp_security")
        batch.drop_column("email_provider")
