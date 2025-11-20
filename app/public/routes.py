from datetime import datetime

from flask import flash, redirect, render_template, request, session, url_for

from app import db
from app.models import Candidate, Election, Position, VoterInvitation, Vote
from app.public import public_bp
from app.utils import record_audit


@public_bp.route('/', methods=['GET', 'POST'])
def vote():
    """Landing page where voters prove they belong in a specific election."""
    if request.method == 'POST':
        election_code = request.form.get('election_code', '').strip()
        voting_key = request.form.get('voting_key', '').strip()
        if not election_code or not voting_key:
            flash('Election code and voting key are required.', 'danger')
            return redirect(request.url)
        election = _find_election_by_code(election_code)
        if not election:
            flash('Election code not recognized.', 'danger')
            return redirect(request.url)
        invitation = _find_invitation(election, voting_key)
        if not invitation:
            flash('Invalid or already-used key.', 'danger')
            return redirect(request.url)
        if not election.is_open():
            flash('Election is not accepting votes right now.', 'warning')
            return redirect(request.url)
        # stash the bare minimum context in session so the next view loads instantly
        session['election_id'] = election.id
        session['invitation_id'] = invitation.id
        session['voter_name'] = invitation.name or invitation.email or 'Voter'
        record_audit(
            'voter_key_verified',
            f"Voting key accepted for {election.name} ({invitation.email})",
            election_id=election.id,
            invitation_id=invitation.id,
        )
        flash('Key accepted. Please cast your ballot.', 'success')
        return redirect(url_for('public.ballot'))
    return render_template('public/vote_key.html')


@public_bp.route('/ballot')
def ballot():
    """Renders the ballot for the election tied to the current session."""
    election_id = session.get('election_id')
    invitation_id = session.get('invitation_id')
    if not election_id or not invitation_id:
        flash('Start by entering your key.', 'warning')
        return redirect(url_for('public.vote'))
    election = Election.query.get_or_404(election_id)
    if not election.is_open():
        flash('Election is closed.', 'warning')
        return redirect(url_for('public.vote'))
    positions = Position.query.filter_by(election_id=election.id).order_by(Position.order_index.asc()).all()
    # greeting with their captured name reinforces that they landed in the right place
    voter_name = session.get('voter_name')
    return render_template('public/ballot.html', election=election, positions=positions, voter_name=voter_name)


@public_bp.route('/submit_ballot', methods=['POST'])
def submit_ballot():
    """Persists the ballot choices and finalizes the invitation."""
    election_id = session.get('election_id')
    invitation_id = session.get('invitation_id')
    if not election_id or not invitation_id:
        flash('Session expired. Enter your key again.', 'danger')
        return redirect(url_for('public.vote'))
    election = Election.query.get_or_404(election_id)
    invitation = VoterInvitation.query.get_or_404(invitation_id)
    if not election.is_open():
        flash('Election is closed.', 'warning')
        return redirect(url_for('public.vote'))
    if invitation.election_id != election.id:
        flash('Session mismatch. Please start again.', 'danger')
        return redirect(url_for('public.vote'))
    if invitation.used:
        flash('This key was already used.', 'danger')
        return redirect(url_for('public.vote'))

    positions = Position.query.filter_by(election_id=election.id).order_by(Position.order_index.asc()).all()
    for position in positions:
        # each form field is namespaced with the position id making iteration simple
        field = f'position_{position.id}'
        selected_candidate = request.form.get(field)
        if not selected_candidate:
            continue
        candidate = Candidate.query.filter_by(id=selected_candidate, position_id=position.id).first()
        if not candidate:
            continue
        vote = Vote(
            election_id=election.id,
            position_id=position.id,
            candidate_id=candidate.id,
            cast_at=datetime.utcnow(),
        )
        db.session.add(vote)
    invitation.used = True
    invitation.used_at = datetime.utcnow()
    db.session.add(invitation)
    db.session.commit()  # Invitation is marked as used here to prevent reuse.
    record_audit(
        'ballot_submitted',
        f"Ballot submitted for {election.name} ({invitation.email})",
        election_id=election.id,
        invitation_id=invitation.id,
    )
    session.pop('election_id', None)
    session.pop('invitation_id', None)
    session.pop('voter_name', None)
    return render_template('public/thank_you.html', election=election)


def _find_election_by_code(code: str):
    """Simple helper that normalizes the election code lookup."""
    normalized = code.strip()
    if not normalized:
        return None
    return Election.query.filter(
        db.func.lower(Election.access_code) == normalized.lower(),
        Election.is_active.is_(True),
    ).first()


def _find_invitation(election: Election, raw_key: str):
    """Linear scan against loaded invitations so we avoid storing raw keys."""
    for invitation in election.invitations:
        if invitation.used:
            continue
        # hashed keys never leave the DB, so we compare with Werkzeug's helper
        if invitation.check_key(raw_key):
            return invitation
    return None


@public_bp.route('/results/<slug>')
def public_results(slug):
    """Delivers a shareable view of results once an admin publishes them."""
    election = Election.query.filter_by(results_slug=slug, results_public=True).first_or_404()
    summary = election.summarize_results()
    # totals block gives public visitors quick context on turnout
    totals = {
        'total': len(election.invitations),
        'voted': sum(1 for inv in election.invitations if inv.used),
        'not_voted': 0,
    }
    totals['not_voted'] = totals['total'] - totals['voted']
    return render_template('public/results.html', election=election, summary=summary, totals=totals)
