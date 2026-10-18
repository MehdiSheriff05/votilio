"""add results email templates

Revision ID: 1c7e1d5a3c2a
Revises: 9db801b5bcaf
Create Date: 2026-01-27 00:30:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "1c7e1d5a3c2a"
down_revision = "9db801b5bcaf"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("system_settings", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "results_subject",
                sa.String(length=255),
                nullable=False,
                server_default="Results for {{ election_name }}",
            )
        )
        batch_op.add_column(
            sa.Column(
                "results_body",
                sa.Text(),
                nullable=False,
                server_default=(
                    "Results are now available for '{{ election_name }}'.\n\n"
                    "Election Code: {{ election_code }}\n"
                    "Results link: {{ results_url }}\n"
                ),
            )
        )


def downgrade():
    with op.batch_alter_table("system_settings", schema=None) as batch_op:
        batch_op.drop_column("results_body")
        batch_op.drop_column("results_subject")
