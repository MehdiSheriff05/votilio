"""email provider switch: smtp or resend

Revision ID: c3a1f0d2b7e4
Revises: 9db801b5bcaf
Create Date: 2026-10-18 03:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "c3a1f0d2b7e4"
down_revision = "9db801b5bcaf"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("system_settings") as batch:
        batch.add_column(sa.Column("email_provider", sa.String(16), nullable=False, server_default="smtp"))
        batch.add_column(sa.Column("smtp_security", sa.String(16), nullable=False, server_default="starttls"))
        batch.add_column(sa.Column("resend_api_key", sa.String(512), nullable=True))


def downgrade():
    with op.batch_alter_table("system_settings") as batch:
        batch.drop_column("resend_api_key")
        batch.drop_column("smtp_security")
        batch.drop_column("email_provider")
