"""multi-select positions; make sure the candidate status and results-email columns exist

Revision ID: e5c3b1a7d9f2
Revises: d4b2a8c1e9f5
Create Date: 2026-10-18 05:00:00

Databases reach this point by three routes (2025 schema, 2026 schema, or an earlier v3 build),
so every change here checks what is already present.
"""
from alembic import op
import sqlalchemy as sa

revision = "e5c3b1a7d9f2"
down_revision = "d4b2a8c1e9f5"
branch_labels = None
depends_on = None

RESULTS_BODY = (
    "Results are now available for '{{ election_name }}'.\n\n"
    "Election Code: {{ election_code }}\n"
    "Results link: {{ results_url }}\n"
)


def _cols(table):
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    cand, pos, settings = _cols("candidate"), _cols("position"), _cols("system_settings")

    if not {"is_declined", "is_disqualified"} <= cand:
        with op.batch_alter_table("candidate") as batch:
            if "is_declined" not in cand:
                batch.add_column(sa.Column("is_declined", sa.Boolean(), nullable=False, server_default=sa.false()))
            if "is_disqualified" not in cand:
                batch.add_column(sa.Column("is_disqualified", sa.Boolean(), nullable=False, server_default=sa.false()))

    with op.batch_alter_table("position") as batch:
        if "winner_override_id" not in pos:
            batch.add_column(sa.Column("winner_override_id", sa.Integer(), nullable=True))
            batch.create_foreign_key("fk_position_winner_override_candidate", "candidate", ["winner_override_id"], ["id"])
        if "max_selections" not in pos:
            batch.add_column(sa.Column("max_selections", sa.Integer(), nullable=False, server_default="1"))

    with op.batch_alter_table("system_settings") as batch:
        if "results_subject" not in settings:
            batch.add_column(sa.Column("results_subject", sa.String(255), nullable=False,
                                       server_default="Results for {{ election_name }}"))
        if "results_body" not in settings:
            batch.add_column(sa.Column("results_body", sa.Text(), nullable=False, server_default=RESULTS_BODY))


def downgrade():
    with op.batch_alter_table("position") as batch:
        batch.drop_column("max_selections")
