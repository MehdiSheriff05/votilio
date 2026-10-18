"""Who may manage which election.

Super admins manage everything. Any other admin manages only the elections they were added to directly
or through a group. `guard()` runs before every admin request, resolves the election behind the URL
(election, position, candidate or voter) and answers 404 when the admin has no access, so a new route
cannot forget the check.
"""
from typing import Optional, Set

from flask import abort, flash, g, redirect, request, session, url_for

from app import db
from app.models import (AdminUser, Candidate, Election, Position, VoterInvitation, admin_group_member,
                        election_admin, election_group)


def current_admin() -> Optional[AdminUser]:
    if "_admin" not in g:
        admin_id = session.get("admin_id")
        g._admin = db.session.get(AdminUser, admin_id) if admin_id else None
    return g._admin


def accessible_election_ids(admin: Optional[AdminUser] = None) -> Optional[Set[int]]:
    """None means every election (super admin). Otherwise the set of election ids."""
    admin = admin or current_admin()
    if admin is None:
        return set()
    if admin.is_super_admin:
        return None
    direct = db.session.query(election_admin.c.election_id).filter(election_admin.c.admin_id == admin.id)
    via_group = (
        db.session.query(election_group.c.election_id)
        .join(admin_group_member, admin_group_member.c.group_id == election_group.c.group_id)
        .filter(admin_group_member.c.admin_id == admin.id)
    )
    return {row[0] for row in direct.union(via_group).all()}


def can_manage(election_id: int) -> bool:
    ids = accessible_election_ids()
    return ids is None or election_id in ids


def visible_elections():
    query = Election.query.order_by(Election.id.desc())
    ids = accessible_election_ids()
    return query if ids is None else query.filter(Election.id.in_(ids or {-1}))


def _election_id_for(view_args: dict) -> Optional[int]:
    if "election_id" in view_args:
        return view_args["election_id"]
    if "position_id" in view_args:
        position = db.session.get(Position, view_args["position_id"])
        return position.election_id if position else None
    if "candidate_id" in view_args:
        candidate = db.session.get(Candidate, view_args["candidate_id"])
        return candidate.position.election_id if candidate else None
    if "invitation_id" in view_args:
        invitation = db.session.get(VoterInvitation, view_args["invitation_id"])
        return invitation.election_id if invitation else None
    return None


PUBLIC_ENDPOINTS = {"admin.login", "static"}


def guard():
    if request.endpoint in PUBLIC_ENDPOINTS or request.endpoint is None:
        return None
    if session.get("admin_id") and current_admin() is None:
        session.clear()
        flash("Your account is no longer available.", "warning")
        return redirect(url_for("admin.login"))
    if not session.get("admin_id"):
        return None  # login_required sends them to the sign-in page
    session["is_super_admin"] = bool(current_admin().is_super_admin)
    election_id = _election_id_for(request.view_args or {})
    if election_id is not None and not can_manage(election_id):
        abort(404)
    return None
