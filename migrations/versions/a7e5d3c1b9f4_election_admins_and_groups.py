"""per-election admins and admin groups

Revision ID: a7e5d3c1b9f4
Revises: f6d4c2b8e0a3
Create Date: 2026-10-19 09:00:00

Existing non-super admins are granted every existing election, so nobody loses access on upgrade.
A super admin can then remove people from the elections they should not manage.
"""
from alembic import op
import sqlalchemy as sa

revision = "a7e5d3c1b9f4"
down_revision = "f6d4c2b8e0a3"
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "admin_group" not in existing:
        op.create_table(
            "admin_group",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(80), nullable=False, unique=True),
        )
    if "admin_group_member" not in existing:
        op.create_table(
            "admin_group_member",
            sa.Column("group_id", sa.Integer(), sa.ForeignKey("admin_group.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("admin_id", sa.Integer(), sa.ForeignKey("admin_user.id", ondelete="CASCADE"), primary_key=True),
        )
    if "election_admin" not in existing:
        op.create_table(
            "election_admin",
            sa.Column("election_id", sa.Integer(), sa.ForeignKey("election.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("admin_id", sa.Integer(), sa.ForeignKey("admin_user.id", ondelete="CASCADE"), primary_key=True),
        )
        op.execute(
            "INSERT INTO election_admin (election_id, admin_id) "
            "SELECT e.id, a.id FROM election e CROSS JOIN admin_user a WHERE a.is_super_admin = false"
        )
    if "election_group" not in existing:
        op.create_table(
            "election_group",
            sa.Column("election_id", sa.Integer(), sa.ForeignKey("election.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("group_id", sa.Integer(), sa.ForeignKey("admin_group.id", ondelete="CASCADE"), primary_key=True),
        )


def downgrade():
    for table in ("election_group", "election_admin", "admin_group_member", "admin_group"):
        op.drop_table(table)
