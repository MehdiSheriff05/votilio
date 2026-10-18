import csv
import io
import re
import secrets

from flask import (Response, abort, current_app, flash, jsonify, redirect, render_template,
                   request, url_for)

from app import db
from app.admin import admin_bp
from app.admin.helpers import (done, election_stats, fail, is_super, parse_local_datetime, wants_json)
from app.imports import csv_safe
from app.models import Candidate, Election, Position, Vote
from app.utils import (delete_uploaded_file, login_required, public_url, record_audit,
                       save_uploaded_image, super_admin_required, utc_naive_to_local_input)

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _color(value):
    value = (value or "").strip()
    return value if HEX.match(value) else None


def _slug_code(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:20] or "vote"
    while True:
        code = f"{base}-{secrets.randbelow(900) + 100}"
        if not Election.query.filter(db.func.lower(Election.access_code) == code).first():
            return code


@admin_bp.route('/')
@login_required
def dashboard():
    elections = Election.query.order_by(Election.id.desc()).all()
    cards = [{"election": e, "stats": election_stats(e)} for e in elections]
    return render_template('admin/elections.html', cards=cards)


@admin_bp.route('/elections/create', methods=['GET', 'POST'])
@login_required
def create_election():
    form = request.form if request.method == 'POST' else {}
    if request.method == 'POST':
        name = form.get('name', '').strip()
        access_code = form.get('access_code', '').strip() or (_slug_code(name) if name else '')
        start_time, start_error = parse_local_datetime(form.get('start_time', '').strip(), 'Start time')
        end_time, end_error = parse_local_datetime(form.get('end_time', '').strip(), 'End time')
        errors = []
        if not name:
            errors.append('Give the election a name.')
        elif Election.query.filter(db.func.lower(Election.access_code) == access_code.lower()).first():
            errors.append('That election code is already in use.')
        errors += [e for e in (start_error, end_error) if e]
        if start_time and end_time and end_time <= start_time:
            errors.append('The end must be after the start.')
        if not errors:
            election = Election(
                name=name, description=form.get('description', '').strip(), start_time=start_time,
                end_time=end_time, is_active=True, access_code=access_code,
                theme_primary=_color(form.get('theme_primary')),
            )
            db.session.add(election)
            db.session.commit()
            record_audit('election_created', f"Election '{election.name}' created", election_id=election.id)
            flash('Election created. Add positions and candidates next.', 'success')
            return redirect(url_for('admin.setup', election_id=election.id))
        for error in errors:
            flash(error, 'danger')
    return render_template('admin/election_new.html', form=form)


@admin_bp.route('/elections/<int:election_id>')
@login_required
def election_home(election_id):
    return redirect(url_for('admin.setup', election_id=election_id))


@admin_bp.route('/elections/<int:election_id>/setup', methods=['GET', 'POST'])
@login_required
def setup(election_id):
    election = Election.query.get_or_404(election_id)
    if request.method == 'POST':
        form = request.form
        name = form.get('name', '').strip()
        access_code = form.get('access_code', '').strip()
        start_time, start_error = parse_local_datetime(form.get('start_time', '').strip(), 'Start time')
        end_time, end_error = parse_local_datetime(form.get('end_time', '').strip(), 'End time')
        url = url_for('admin.setup', election_id=election.id)
        if not name or not access_code:
            return fail('Name and election code are required.', url)
        clash = Election.query.filter(db.func.lower(Election.access_code) == access_code.lower(),
                                      Election.id != election.id).first()
        if clash:
            return fail('That election code is already in use.', url)
        for error in (start_error, end_error):
            if error:
                return fail(error, url)
        if start_time and end_time and end_time <= start_time:
            return fail('The end must be after the start.', url)
        election.name, election.access_code = name, access_code
        election.description = form.get('description', '').strip()
        election.start_time, election.end_time = start_time, end_time
        election.theme_primary = _color(form.get('theme_primary'))
        election.theme_secondary = _color(form.get('theme_secondary'))
        election.theme_accent = _color(form.get('theme_accent'))
        db.session.commit()
        record_audit('election_updated', f"Election '{election.name}' updated", election_id=election.id)
        return done('Changes saved.', url)
    positions = Position.query.filter_by(election_id=election.id).order_by(Position.order_index, Position.id).all()
    return render_template(
        'admin/setup.html', election=election, positions=positions, section='setup',
        stats=election_stats(election),
        start_value=utc_naive_to_local_input(election.start_time),
        end_value=utc_naive_to_local_input(election.end_time),
    )


@admin_bp.route('/elections/<int:election_id>/toggle', methods=['POST'])
@login_required
def toggle_election(election_id):
    election = Election.query.get_or_404(election_id)
    election.is_active = not election.is_active
    db.session.commit()
    record_audit('election_toggled', f"Election '{election.name}' {'resumed' if election.is_active else 'paused'}",
                 election_id=election.id)
    return done('Voting resumed.' if election.is_active else 'Voting paused.',
                request.form.get('next') or url_for('admin.setup', election_id=election.id),
                status=election.status())


@admin_bp.route('/elections/<int:election_id>/delete', methods=['POST'])
@login_required
@super_admin_required
def delete_election(election_id):
    election = Election.query.get_or_404(election_id)
    name = election.name
    photos = [c.photo_url for p in election.positions for c in p.candidates]
    Vote.query.filter_by(election_id=election.id).delete()
    db.session.delete(election)
    db.session.commit()
    for photo in photos:
        delete_uploaded_file(photo)
    record_audit('election_deleted', f"Election '{name}' deleted")
    return done('Election deleted.', url_for('admin.dashboard'), 'info')


# ---- positions -------------------------------------------------------------

def _slots(raw) -> int:
    try:
        return max(1, min(50, int(raw)))
    except (TypeError, ValueError):
        return 1


@admin_bp.route('/elections/<int:election_id>/positions/create', methods=['POST'])
@login_required
def create_position(election_id):
    election = Election.query.get_or_404(election_id)
    url = url_for('admin.setup', election_id=election.id)
    name = request.form.get('name', '').strip()
    if not name:
        return fail('Give the position a name.', url)
    position = Position(
        election=election, name=name[:128], description=request.form.get('description', '').strip(),
        candidate_slots=_slots(request.form.get('candidate_slots', '1')),
        order_index=(db.session.query(db.func.max(Position.order_index)).filter_by(election_id=election.id).scalar() or 0) + 1,
    )
    db.session.add(position)
    db.session.commit()
    record_audit('position_created', f"Position '{position.name}' added to {election.name}", election_id=election.id)
    return done('Position added.', url, position_id=position.id)


@admin_bp.route('/positions/<int:position_id>/update', methods=['POST'])
@login_required
def update_position(position_id):
    position = Position.query.get_or_404(position_id)
    url = url_for('admin.setup', election_id=position.election_id)
    name = request.form.get('name', '').strip()
    if not name:
        return fail('Give the position a name.', url)
    position.name = name[:128]
    position.description = request.form.get('description', '').strip()
    position.candidate_slots = _slots(request.form.get('candidate_slots', position.candidate_slots))
    db.session.commit()
    record_audit('position_updated', f"Position '{position.name}' updated", election_id=position.election_id)
    return done('Position saved.', url)


def _vote_count_for(candidate_ids) -> int:
    if not candidate_ids:
        return 0
    return Vote.query.filter(Vote.candidate_id.in_(candidate_ids)).count()


@admin_bp.route('/positions/<int:position_id>/delete', methods=['POST'])
@login_required
def delete_position(position_id):
    position = Position.query.get_or_404(position_id)
    url = url_for('admin.setup', election_id=position.election_id)
    if _vote_count_for([c.id for c in position.candidates]):
        return fail('Votes have already been cast for this position, so it cannot be deleted.', url, 409)
    name, photos = position.name, [c.photo_url for c in position.candidates]
    election_id = position.election_id
    db.session.delete(position)
    db.session.commit()
    for photo in photos:
        delete_uploaded_file(photo)
    record_audit('position_deleted', f"Position '{name}' deleted", election_id=election_id)
    return done('Position deleted.', url, 'info')


def _apply_order(model, ids, scope_filter):
    items = {i.id: i for i in model.query.filter(scope_filter).all()}
    clean = [int(i) for i in ids if str(i).isdigit() and int(i) in items]
    for order, item_id in enumerate(clean, start=1):
        items[item_id].order_index = order
    seen = set(clean)
    tail = len(clean)
    for item_id, item in items.items():
        if item_id not in seen:
            tail += 1
            item.order_index = tail
    db.session.commit()


@admin_bp.route('/elections/<int:election_id>/positions/reorder', methods=['POST'])
@login_required
def reorder_positions(election_id):
    Election.query.get_or_404(election_id)
    ids = (request.get_json(silent=True) or {}).get('ids', [])
    _apply_order(Position, ids, Position.election_id == election_id)
    return jsonify(ok=True)


# ---- candidates ------------------------------------------------------------

@admin_bp.route('/positions/<int:position_id>/candidates/create', methods=['POST'])
@login_required
def create_candidate(position_id):
    position = Position.query.get_or_404(position_id)
    url = url_for('admin.setup', election_id=position.election_id)
    if len(position.candidates) >= position.candidate_slots:
        return fail(f'{position.name} is full. Raise its slots to add more candidates.', url, 409)
    name = request.form.get('name', '').strip()
    if not name:
        return fail('Give the candidate a name.', url)
    photo_file = request.files.get('photo')
    photo = None
    if photo_file and photo_file.filename:
        photo = save_uploaded_image(photo_file)
        if not photo:
            return fail('That file is not a valid PNG, JPG, GIF or WEBP image.', url)
    nxt = (db.session.query(db.func.max(Candidate.order_index)).filter_by(position_id=position.id).scalar() or 0) + 1
    candidate = Candidate(position=position, name=name[:128], description=request.form.get('description', '').strip(),
                          photo_url=photo, order_index=nxt)
    db.session.add(candidate)
    db.session.commit()
    record_audit('candidate_created', f"Candidate '{candidate.name}' added to {position.name}", election_id=position.election_id)
    return done('Candidate added.', url, candidate_id=candidate.id)


@admin_bp.route('/candidates/<int:candidate_id>/update', methods=['POST'])
@login_required
def update_candidate(candidate_id):
    candidate = Candidate.query.get_or_404(candidate_id)
    url = url_for('admin.setup', election_id=candidate.position.election_id)
    name = request.form.get('name', '').strip()
    if not name:
        return fail('Give the candidate a name.', url)
    photo_file = request.files.get('photo')
    old_photo = candidate.photo_url
    if photo_file and photo_file.filename:
        saved = save_uploaded_image(photo_file)
        if not saved:
            return fail('That file is not a valid PNG, JPG, GIF or WEBP image.', url)
        candidate.photo_url = saved
        delete_uploaded_file(old_photo)
    elif request.form.get('remove_photo') in ('on', '1', 'true'):
        candidate.photo_url = None
        delete_uploaded_file(old_photo)
    new_position = request.form.get('position_id')
    if new_position and str(new_position).isdigit() and int(new_position) != candidate.position_id:
        target = Position.query.filter_by(id=int(new_position), election_id=candidate.position.election_id).first()
        if target and len(target.candidates) < target.candidate_slots:
            candidate.position = target
        else:
            return fail('That position is full or does not exist.', url, 409)
    candidate.name = name[:128]
    candidate.description = request.form.get('description', '').strip()
    db.session.commit()
    record_audit('candidate_updated', f"Candidate '{candidate.name}' updated", election_id=candidate.position.election_id)
    return done('Candidate saved.', url)


@admin_bp.route('/candidates/<int:candidate_id>/delete', methods=['POST'])
@login_required
def delete_candidate(candidate_id):
    candidate = Candidate.query.get_or_404(candidate_id)
    election_id = candidate.position.election_id
    url = url_for('admin.setup', election_id=election_id)
    if _vote_count_for([candidate.id]):
        return fail('Votes have been cast for this candidate, so they cannot be deleted.', url, 409)
    name, photo = candidate.name, candidate.photo_url
    db.session.delete(candidate)
    db.session.commit()
    delete_uploaded_file(photo)
    record_audit('candidate_deleted', f"Candidate '{name}' deleted", election_id=election_id)
    return done('Candidate deleted.', url, 'info')


@admin_bp.route('/positions/<int:position_id>/candidates/reorder', methods=['POST'])
@login_required
def reorder_candidates(position_id):
    Position.query.get_or_404(position_id)
    ids = (request.get_json(silent=True) or {}).get('ids', [])
    _apply_order(Candidate, ids, Candidate.position_id == position_id)
    return jsonify(ok=True)


# ---- results ---------------------------------------------------------------

@admin_bp.route('/elections/<int:election_id>/results')
@login_required
def view_results(election_id):
    election = Election.query.get_or_404(election_id)
    public_results_url = None
    if election.results_public and election.results_slug:
        public_results_url = public_url('public.public_results', slug=election.results_slug)
    return render_template(
        'admin/results.html', election=election, section='results', stats=election_stats(election),
        summary=election.summarize_results(), public_results_url=public_results_url,
    )


@admin_bp.route('/elections/<int:election_id>/results/publish', methods=['POST'])
@login_required
def publish_results(election_id):
    election = Election.query.get_or_404(election_id)
    if request.form.get('state') == 'publish':
        if not election.results_slug:
            election.results_slug = _generate_results_slug(election.name)
        election.results_public = True
        message = 'Public results link is live.'
    else:
        election.results_public = False
        message = 'Public results link turned off.'
    db.session.commit()
    record_audit('results_visibility_changed', f"Results visibility updated for {election.name}", election_id=election.id)
    return done(message, url_for('admin.view_results', election_id=election.id))


@admin_bp.route('/elections/<int:election_id>/results.csv')
@login_required
def results_csv(election_id):
    election = Election.query.get_or_404(election_id)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["position", "candidate", "votes", "percent", "winner"])
    for block in election.summarize_results():
        total = block['total_votes']
        for item in block['candidates']:
            pct = f"{100 * item['count'] / total:.1f}" if total else "0.0"
            writer.writerow([csv_safe(block['position'].name), csv_safe(item['candidate'].name), item['count'], pct,
                             "yes" if item['candidate'] in block['winners'] else ""])
    return Response(out.getvalue(), mimetype='text/csv',
                    headers={"Content-Disposition": f'attachment; filename="results-{election.id}.csv"'})


def _generate_results_slug(name: str) -> str:
    base = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')[:50] or secrets.token_urlsafe(4).lower()
    slug, suffix = base, 1
    while Election.query.filter(Election.results_slug == slug).first():
        slug = f"{base}-{suffix}"[:63]
        suffix += 1
    return slug
