from datetime import datetime
from urllib.parse import quote

from flask import abort, flash, redirect, render_template, request, session, url_for

from app import db, limiter
from app.models import Candidate, Election, Position, VoterInvitation, Vote
from app.public import public_bp
from app.utils import record_audit

VOTER_KEYS = ("election_id", "invitation_id", "voter_name", "draft", "thanks_election_id")


def _clear_voter_session() -> None:
    for key in VOTER_KEYS:
        session.pop(key, None)


def _find_election_by_code(code: str):
    code = (code or "").strip()
    if not code:
        return None
    return Election.query.filter(db.func.lower(Election.access_code) == code.lower(),
                                 Election.is_active.is_(True)).first()


def _find_invitation(election: Election, raw_key: str):
    """Direct lookup on the keyed digest; legacy slow hashes are checked only if any remain."""
    digest = VoterInvitation.hash_key(election.id, raw_key)
    found = VoterInvitation.query.filter_by(election_id=election.id, voting_key_hash=digest, used=False).first()
    if found:
        return found
    # Self-heal after FLASK_SECRET_KEY rotation: the key is also stored for admins, so match on it and re-hash.
    rotated = VoterInvitation.query.filter_by(election_id=election.id, last_generated_key=raw_key, used=False).first()
    if rotated:
        rotated.set_key(raw_key)
        db.session.commit()
        return rotated
    legacy = VoterInvitation.query.filter(
        VoterInvitation.election_id == election.id, VoterInvitation.used.is_(False),
        ~VoterInvitation.voting_key_hash.like(VoterInvitation.HMAC_PREFIX + '%')).all()
    for invitation in legacy:
        if invitation.check_key(raw_key):
            return invitation
    return None


def _session_voter():
    election_id, invitation_id = session.get('election_id'), session.get('invitation_id')
    if not election_id or not invitation_id:
        return None, None
    election = db.session.get(Election, election_id)
    invitation = db.session.get(VoterInvitation, invitation_id)
    if not election or not invitation or invitation.election_id != election.id or invitation.used:
        _clear_voter_session()
        return None, None
    return election, invitation


def _positions(election):
    return Position.query.filter_by(election_id=election.id).order_by(Position.order_index, Position.id).all()


@public_bp.route('/', methods=['GET', 'POST'])
@limiter.limit("10 per minute; 60 per hour", methods=["POST"], deduct_when=lambda r: r.status_code != 302)
def vote():
    code = (request.form.get('election_code') if request.method == 'POST' else request.args.get('code', '')) or ''
    code = code.strip()
    election = _find_election_by_code(code)
    error = None
    if request.method == 'POST':
        key = ''.join(ch for ch in request.form.get('voting_key', '') if ch.isdigit())
        if not code or len(key) != 6:
            error = 'Enter your election code and the 6-digit voting key from your email.'
        elif not election:
            error = "We couldn't find that election code. Check your invitation email."
        else:
            invitation = _find_invitation(election, key)
            if not invitation:
                error = 'That key is invalid or has already been used.'
            elif not election.is_open():
                error = ('Voting has not started yet.' if election.status() == 'scheduled'
                         else 'Voting is closed for this election.')
            else:
                _clear_voter_session()
                session['election_id'] = election.id
                session['invitation_id'] = invitation.id
                session['voter_name'] = invitation.name or ''
                record_audit('voter_key_verified', f"Voting key accepted for {election.name} ({invitation.email})",
                             election_id=election.id, invitation_id=invitation.id)
                return redirect(url_for('public.ballot'))
    return render_template('public/enter.html', election=election, code=code, error=error)


@public_bp.route('/ballot', methods=['GET', 'POST'])
def ballot():
    election, invitation = _session_voter()
    if not election:
        flash('Enter your election code and voting key to start.', 'info')
        return redirect(url_for('public.vote'))
    if not election.is_open():
        _clear_voter_session()
        flash('Voting is closed for this election.', 'warning')
        return redirect(url_for('public.vote'))
    positions = _positions(election)
    if request.method == 'POST':
        draft = {}
        for position in positions:
            raw = request.form.get(f'position_{position.id}', '')
            if raw.isdigit() and any(c.id == int(raw) for c in position.candidates):
                draft[str(position.id)] = int(raw)
        session['draft'] = draft
        return redirect(url_for('public.review'))
    return render_template('public/ballot.html', election=election, positions=positions,
                           draft=session.get('draft', {}), voter_name=session.get('voter_name'))


@public_bp.route('/ballot/review')
def review():
    election, invitation = _session_voter()
    if not election:
        return redirect(url_for('public.vote'))
    if not election.is_open():
        _clear_voter_session()
        flash('Voting is closed for this election.', 'warning')
        return redirect(url_for('public.vote'))
    draft = session.get('draft')
    if draft is None:
        return redirect(url_for('public.ballot'))
    rows = []
    for position in _positions(election):
        chosen = next((c for c in position.candidates if draft.get(str(position.id)) == c.id), None)
        rows.append({"position": position, "candidate": chosen})
    return render_template('public/review.html', election=election, rows=rows, voter_name=session.get('voter_name'))


@public_bp.route('/ballot/submit', methods=['POST'])
def submit_ballot():
    election, invitation = _session_voter()
    if not election:
        flash('Your session expired. Enter your key again.', 'warning')
        return redirect(url_for('public.vote'))
    if not election.is_open():
        _clear_voter_session()
        flash('Voting is closed for this election.', 'warning')
        return redirect(url_for('public.vote'))
    draft = session.get('draft')
    if draft is None:
        return redirect(url_for('public.ballot'))

    now = datetime.utcnow()
    claimed = VoterInvitation.query.filter_by(id=invitation.id, used=False).update(
        {"used": True, "used_at": now}, synchronize_session=False)
    if claimed != 1:
        db.session.rollback()
        _clear_voter_session()
        flash('This key has already been used.', 'danger')
        return redirect(url_for('public.vote'))
    cast = 0
    for position in _positions(election):
        candidate_id = draft.get(str(position.id))
        if candidate_id and Candidate.query.filter_by(id=candidate_id, position_id=position.id).first():
            db.session.add(Vote(election_id=election.id, position_id=position.id, candidate_id=candidate_id, cast_at=now))
            cast += 1
    db.session.commit()
    record_audit('ballot_submitted', f"Ballot submitted for {election.name} ({invitation.email})",
                 election_id=election.id, invitation_id=invitation.id)
    _clear_voter_session()
    session['thanks_election_id'] = election.id
    return redirect(url_for('public.thanks'))


@public_bp.route('/thanks')
def thanks():
    election = db.session.get(Election, session.get('thanks_election_id') or 0)
    if not election:
        return redirect(url_for('public.vote'))
    results_url = None
    if election.results_public and election.results_slug:
        results_url = url_for('public.public_results', slug=election.results_slug)
    return render_template('public/thanks.html', election=election, results_url=results_url)


@public_bp.route('/results/<slug>')
def public_results(slug):
    election = Election.query.filter_by(results_slug=slug, results_public=True).first_or_404()
    total = VoterInvitation.query.filter_by(election_id=election.id).count()
    voted = VoterInvitation.query.filter_by(election_id=election.id, used=True).count()
    totals = {'total': total, 'voted': voted, 'turnout': round(100 * voted / total) if total else 0}
    return render_template('public/results.html', election=election, summary=election.summarize_results(), totals=totals)
