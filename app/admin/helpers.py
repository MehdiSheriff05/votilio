from datetime import datetime
from typing import Optional, Set

from flask import flash, jsonify, redirect, request, session

from app import db
from app.email_utils import generate_6_digit_code
from app.models import Election, VoterInvitation
from app.utils import local_to_utc_naive


def wants_json() -> bool:
    if request.headers.get("X-Requested-With") == "fetch":
        return True
    best = request.accept_mimetypes.best
    return best == "application/json" and request.accept_mimetypes[best] > request.accept_mimetypes["text/html"]


def done(message: str, url: str, category: str = "success", **data):
    """Success response: JSON for fetch() callers, flash + redirect for plain form posts."""
    if wants_json():
        return jsonify(ok=True, message=message, redirect=url, **data)
    flash(message, category)
    return redirect(url)


def fail(message: str, url: str, status: int = 400, **data):
    if wants_json():
        return jsonify(ok=False, message=message, **data), status
    flash(message, "danger")
    return redirect(url)


def parse_local_datetime(raw: str, label: str):
    """Parses a datetime-local value in the display timezone into naive UTC."""
    if not raw:
        return None, None
    try:
        return local_to_utc_naive(datetime.fromisoformat(raw)), None
    except ValueError:
        return None, f"{label} must be a valid date and time."


def is_super() -> bool:
    return bool(session.get("is_super_admin"))


class KeyAllocator:
    """Hands out voting keys that are unique within an election without scanning password hashes."""

    def __init__(self, election: Election):
        self.taken: Set[str] = set()
        self.legacy = []
        with db.session.no_autoflush:
            rows = db.session.query(VoterInvitation.last_generated_key, VoterInvitation.id).filter(
                VoterInvitation.election_id == election.id).all()
            legacy_ids = []
            for key, inv_id in rows:
                if key:
                    self.taken.add(key)
                else:
                    legacy_ids.append(inv_id)
            if legacy_ids:
                self.legacy = VoterInvitation.query.filter(VoterInvitation.id.in_(legacy_ids)).all()

    def allocate(self) -> str:
        while True:
            key = generate_6_digit_code()
            if key in self.taken:
                continue
            if any(inv.check_key(key) for inv in self.legacy):
                continue
            self.taken.add(key)
            return key


def new_invitation(election: Election, allocator: KeyAllocator, name: Optional[str], email: Optional[str]) -> VoterInvitation:
    invitation = VoterInvitation(election_id=election.id, name=name or None, email=email or None)
    key = allocator.allocate()
    invitation.set_key(key)
    invitation.last_generated_key = key
    return invitation


def election_stats(election: Election) -> dict:
    from app.models import Candidate, Position

    total, sent, voted = db.session.query(
        db.func.count(VoterInvitation.id),
        db.func.count(VoterInvitation.sent_at),
        db.func.coalesce(db.func.sum(db.case((VoterInvitation.used.is_(True), 1), else_=0)), 0),
    ).filter(VoterInvitation.election_id == election.id).one()
    positions = Position.query.filter_by(election_id=election.id).count()
    candidates = (
        db.session.query(db.func.count(Candidate.id))
        .join(Position, Candidate.position_id == Position.id)
        .filter(Position.election_id == election.id)
        .scalar()
    )
    voted = int(voted or 0)
    return {
        "voters": total,
        "sent": sent,
        "voted": voted,
        "not_voted": total - voted,
        "turnout": round(100 * voted / total) if total else 0,
        "positions": positions,
        "candidates": candidates or 0,
        "status": election.status(),
    }
