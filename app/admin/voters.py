import csv
import io
from datetime import datetime
from typing import List
from urllib.parse import quote

from flask import Response, current_app, jsonify, render_template, request, url_for

from app import db
from app.admin import admin_bp
from app.admin.helpers import (KeyAllocator, done, election_stats, fail, new_invitation)
from app.imports import csv_safe, is_valid_email
from app.mailer import Message, build_mailer, send_messages, text_to_html
from app.models import Election, SystemSettings, VoterInvitation
from app.utils import (active_timezone_label, format_display_time, login_required, public_url,
                       record_audit, render_email_template, super_admin_required)

PAGE_SIZE = 50
STATUS_FILTERS = {"all", "unsent", "sent", "voted", "pending"}


def _filtered(election: Election, q: str, status: str):
    query = VoterInvitation.query.filter_by(election_id=election.id)
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(db.or_(db.func.lower(VoterInvitation.email).like(like),
                                    db.func.lower(VoterInvitation.name).like(like)))
    if status == "unsent":
        query = query.filter(VoterInvitation.sent_at.is_(None), VoterInvitation.used.is_(False))
    elif status == "sent":
        query = query.filter(VoterInvitation.sent_at.isnot(None), VoterInvitation.used.is_(False))
    elif status == "voted":
        query = query.filter(VoterInvitation.used.is_(True))
    elif status == "pending":
        query = query.filter(VoterInvitation.used.is_(False))
    return query


@admin_bp.route('/elections/<int:election_id>/voters')
@login_required
def voters(election_id):
    election = Election.query.get_or_404(election_id)
    q = request.args.get('q', '').strip()[:100]
    status = request.args.get('status', 'all')
    status = status if status in STATUS_FILTERS else 'all'
    page = max(1, request.args.get('page', 1, type=int) or 1)
    query = _filtered(election, q, status).order_by(VoterInvitation.id.desc())
    total_filtered = query.count()
    items = query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()
    base = VoterInvitation.query.filter_by(election_id=election.id)
    counts = {
        "all": base.count(),
        "unsent": base.filter(VoterInvitation.sent_at.is_(None), VoterInvitation.used.is_(False)).count(),
        "sent": base.filter(VoterInvitation.sent_at.isnot(None), VoterInvitation.used.is_(False)).count(),
        "voted": base.filter(VoterInvitation.used.is_(True)).count(),
    }
    reminder_ready = base.filter(
        VoterInvitation.sent_at.isnot(None), VoterInvitation.used.is_(False),
        VoterInvitation.reminder_sent_at.is_(None), VoterInvitation.email.isnot(None)).count()
    unsendable = base.filter(VoterInvitation.sent_at.is_(None), VoterInvitation.used.is_(False),
                             VoterInvitation.email.isnot(None)).count()
    return render_template(
        'admin/voters.html', election=election, section='voters', stats=election_stats(election),
        items=items, q=q, status=status, page=page, pages=max(1, -(-total_filtered // PAGE_SIZE)),
        total_filtered=total_filtered, counts=counts, reminder_ready=reminder_ready, sendable=unsendable,
        page_size=PAGE_SIZE, mail_ready=_mail_ready(),
    )


def _mail_ready() -> bool:
    try:
        return build_mailer().configuration_error() is None
    except Exception:
        return False


def _voters_url(election_id: int) -> str:
    return url_for('admin.voters', election_id=election_id)


@admin_bp.route('/elections/<int:election_id>/voters/add', methods=['POST'])
@login_required
def add_voter(election_id):
    election = Election.query.get_or_404(election_id)
    url = _voters_url(election.id)
    name = request.form.get('name', '').strip()[:255]
    email = request.form.get('email', '').strip()
    if not is_valid_email(email):
        return fail('Enter a valid email address.', url)
    if VoterInvitation.query.filter(VoterInvitation.election_id == election.id,
                                    db.func.lower(VoterInvitation.email) == email.lower()).first():
        return fail('That email is already on the list.', url, 409)
    invitation = new_invitation(election, KeyAllocator(election), name, email)
    db.session.add(invitation)
    db.session.commit()
    record_audit('invitation_created_manual', f'Added voter {email}', election_id=election.id, invitation_id=invitation.id)
    if request.form.get('send_now') in ('on', '1', 'true'):
        sent, failures = _deliver(election, 'invite', [invitation])
        if failures:
            return done(f'Voter added, but the email failed: {failures[0]["error"]}', url, 'warning')
        return done('Voter added and invitation sent.', url)
    return done('Voter added.', url)


@admin_bp.route('/invitations/<int:invitation_id>/update', methods=['POST'])
@login_required
def update_voter(invitation_id):
    invitation = VoterInvitation.query.get_or_404(invitation_id)
    url = _voters_url(invitation.election_id)
    name = request.form.get('name', '').strip()[:255] or None
    email = request.form.get('email', '').strip() or None
    if email:
        if not is_valid_email(email):
            return fail('Enter a valid email address.', url)
        clash = VoterInvitation.query.filter(
            VoterInvitation.election_id == invitation.election_id, VoterInvitation.id != invitation.id,
            db.func.lower(VoterInvitation.email) == email.lower()).first()
        if clash:
            return fail('Another voter already uses that email.', url, 409)
    invitation.name, invitation.email = name, email
    db.session.commit()
    record_audit('invitation_updated', f'Voter details updated for {email or name or invitation.id}',
                 election_id=invitation.election_id, invitation_id=invitation.id)
    return done('Voter updated.', url)


@admin_bp.route('/invitations/<int:invitation_id>/delete', methods=['POST'])
@login_required
def delete_voter(invitation_id):
    invitation = VoterInvitation.query.get_or_404(invitation_id)
    election_id, label = invitation.election_id, invitation.email or invitation.id
    if invitation.used:
        return fail('This voter has already voted and cannot be removed.', _voters_url(election_id), 409)
    db.session.delete(invitation)
    db.session.commit()
    record_audit('invitation_deleted', f'Voter {label} removed', election_id=election_id)
    return done('Voter removed.', _voters_url(election_id), 'info')


@admin_bp.route('/elections/<int:election_id>/voters/bulk-delete', methods=['POST'])
@login_required
def bulk_delete_voters(election_id):
    election = Election.query.get_or_404(election_id)
    ids = [int(i) for i in request.form.getlist('ids') if i.isdigit()]
    if not ids:
        return fail('Select at least one voter.', _voters_url(election.id))
    removed = VoterInvitation.query.filter(
        VoterInvitation.election_id == election.id, VoterInvitation.id.in_(ids),
        VoterInvitation.used.is_(False)).delete(synchronize_session=False)
    db.session.commit()
    record_audit('invitations_deleted', f'Removed {removed} voter(s) from {election.name}', election_id=election.id)
    return done(f'Removed {removed} voter{"s" if removed != 1 else ""}.', _voters_url(election.id), 'info')


@admin_bp.route('/invitations/<int:invitation_id>/key')
@login_required
def reveal_key(invitation_id):
    invitation = VoterInvitation.query.get_or_404(invitation_id)
    record_audit('key_revealed', f'Voting key viewed for {invitation.email or invitation.id}',
                 election_id=invitation.election_id, invitation_id=invitation.id)
    return jsonify(key=invitation.last_generated_key or "")


# ---- sending ----------------------------------------------------------------

def _context(election: Election, invitation: VoterInvitation, key: str) -> dict:
    tz = active_timezone_label()
    fallback = f"Not specified ({tz})"
    return {
        "election_name": election.name,
        "voting_key": key,
        "election_code": election.access_code or "",
        "vote_url": public_url('public.vote') + (f"?code={quote(election.access_code, safe='')}" if election.access_code else ""),
        "recipient": invitation.name or invitation.email or "Votilio voter",
        "recipient_email": invitation.email,
        "opening_time": format_display_time(election.start_time, fallback, render_html=False),
        "closing_time": format_display_time(election.end_time, fallback, render_html=False),
    }


def _deliver(election: Election, kind: str, invitations: List[VoterInvitation]):
    """Send invitations or reminders for the given rows. Returns (sent_count, failures)."""
    settings = SystemSettings.get_or_create()
    allocator = None
    messages, rows = [], []
    for inv in invitations:
        if not inv.email:
            continue
        if kind == 'results':
            key = ''
            ctx = _context(election, inv, key)
            ctx['results_url'] = public_url('public.public_results', slug=election.results_slug)
            subject_t, body_t = settings.results_subject, settings.results_body
        else:
            key = inv.last_generated_key
            if not key:
                allocator = allocator or KeyAllocator(election)
                key = allocator.allocate()
                inv.set_key(key)
                inv.last_generated_key = key
            ctx = _context(election, inv, key)
            subject_t, body_t = ((settings.invite_subject, settings.invite_body) if kind == 'invite'
                                 else (settings.reminder_subject, settings.reminder_body))
        try:
            subject = render_email_template(subject_t, ctx)
            body = render_email_template(body_t, ctx)
        except Exception as exc:
            messages.append(None)
            rows.append((inv, f"Template error: {exc}"))
            continue
        messages.append(Message(inv.email, subject, body, text_to_html(body)))
        rows.append((inv, None))
    real = [m for m in messages if m]
    results = iter(send_messages(real))
    now = datetime.utcnow()
    sent, failures = 0, []
    for message, (inv, pre_error) in zip(messages, rows):
        if message is None:
            failures.append({"id": inv.id, "email": inv.email, "error": pre_error})
            continue
        result = next(results)
        if result.ok:
            sent += 1
            if kind == 'invite':
                inv.sent_at, inv.reminder_sent_at = now, None
            elif kind == 'reminder':
                inv.reminder_sent_at = now
        else:
            failures.append({"id": inv.id, "email": inv.email, "error": result.error or "Unknown error"})
    db.session.commit()
    return sent, failures


def _send_query(election: Election, kind: str, ids, audience: str = 'all'):
    if kind == 'results':
        q = VoterInvitation.query.filter(
            VoterInvitation.election_id == election.id, VoterInvitation.email.isnot(None), VoterInvitation.email != "")
        return q.filter(VoterInvitation.used.is_(True)) if audience == 'voted' else q
    q = VoterInvitation.query.filter(
        VoterInvitation.election_id == election.id, VoterInvitation.used.is_(False),
        VoterInvitation.email.isnot(None), VoterInvitation.email != "")
    if ids is not None:
        return q.filter(VoterInvitation.id.in_(ids))
    if kind == 'invite':
        return q.filter(VoterInvitation.sent_at.is_(None))
    return q.filter(VoterInvitation.sent_at.isnot(None), VoterInvitation.reminder_sent_at.is_(None))


@admin_bp.route('/elections/<int:election_id>/send', methods=['POST'])
@login_required
def send_chunk(election_id):
    """Sends one chunk and reports progress; the browser calls this repeatedly until `done`."""
    election = Election.query.get_or_404(election_id)
    data = request.get_json(silent=True) or {}
    kind = data.get('kind')
    if kind not in ('invite', 'reminder', 'results'):
        return jsonify(ok=False, message='Unknown send type.'), 400
    audience = 'voted' if data.get('audience') == 'voted' else 'all'
    if kind == 'results' and not (election.results_public and election.results_slug):
        return jsonify(ok=False, message='Publish the results link before emailing it.'), 409
    ids = data.get('ids')
    if ids is not None:
        ids = [int(i) for i in ids if str(i).isdigit()]
    cursor = int(data.get('cursor') or 0)
    size = current_app.config['EMAIL_CHUNK_SIZE']
    base = _send_query(election, kind, ids, audience)
    total_remaining = base.filter(VoterInvitation.id > cursor).count()
    batch = base.filter(VoterInvitation.id > cursor).order_by(VoterInvitation.id).limit(size).all()
    if not batch:
        return jsonify(ok=True, done=True, sent=0, failed=[], cursor=cursor, remaining=0, total=0)
    sent, failures = _deliver(election, kind, batch)
    new_cursor = batch[-1].id
    remaining = total_remaining - len(batch)
    if sent:
        event, noun = {'invite': ('invitations_sent', 'invitation'), 'reminder': ('reminders_sent', 'reminder'),
                       'results': ('results_sent', 'results email')}[kind]
        record_audit(event, f"Sent {sent} {noun}(s) for {election.name}", election_id=election.id)
    return jsonify(ok=True, done=remaining <= 0, sent=sent, failed=failures, cursor=new_cursor,
                   remaining=remaining, total=total_remaining)


@admin_bp.route('/invitations/<int:invitation_id>/send', methods=['POST'])
@login_required
def send_one(invitation_id):
    invitation = VoterInvitation.query.get_or_404(invitation_id)
    url = _voters_url(invitation.election_id)
    kind = 'reminder' if request.form.get('kind') == 'reminder' else 'invite'
    if not invitation.email:
        return fail('This voter has no email address.', url)
    if invitation.used:
        return fail('This voter has already voted.', url, 409)
    sent, failures = _deliver(invitation.election, kind, [invitation])
    if failures:
        return fail(f'Email failed: {failures[0]["error"]}', url, 502)
    record_audit('invitation_sent_single' if kind == 'invite' else 'reminder_sent_single',
                 f'{"Invitation" if kind == "invite" else "Reminder"} sent to {invitation.email}',
                 election_id=invitation.election_id, invitation_id=invitation.id)
    return done('Invitation sent.' if kind == 'invite' else 'Reminder sent.', url)


# ---- exports ----------------------------------------------------------------

def _csv_response(rows, filename):
    out = io.StringIO()
    writer = csv.writer(out)
    for row in rows:
        writer.writerow([csv_safe(c) for c in row])
    return Response(out.getvalue(), mimetype='text/csv',
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@admin_bp.route('/elections/<int:election_id>/voters.csv')
@login_required
def export_voters(election_id):
    election = Election.query.get_or_404(election_id)
    rows = [["name", "email", "status", "invited_at", "reminded_at", "voted_at"]]
    for inv in VoterInvitation.query.filter_by(election_id=election.id).order_by(VoterInvitation.id):
        status = "voted" if inv.used else ("invited" if inv.sent_at else "not invited")
        fmt = lambda d: d.strftime("%Y-%m-%d %H:%M UTC") if d else ""
        rows.append([inv.name or "", inv.email or "", status, fmt(inv.sent_at), fmt(inv.reminder_sent_at), fmt(inv.used_at)])
    return _csv_response(rows, f"voters-{election.id}.csv")


@admin_bp.route('/elections/<int:election_id>/voter-keys.csv')
@login_required
@super_admin_required
def export_keys(election_id):
    election = Election.query.get_or_404(election_id)
    rows = [["name", "email", "election_code", "voting_key", "vote_url"]]
    for inv in VoterInvitation.query.filter_by(election_id=election.id, used=False).order_by(VoterInvitation.id):
        rows.append([inv.name or "", inv.email or "", election.access_code or "", inv.last_generated_key or "",
                     public_url('public.vote')])
    record_audit('keys_exported', f'Voting keys exported for {election.name}', election_id=election.id)
    return _csv_response(rows, f"voter-keys-{election.id}.csv")
