from flask import current_app, jsonify, request

from app import db
from app.admin import admin_bp
from app.admin.helpers import KeyAllocator, new_invitation
from app.admin.voters import _csv_response
from app.imports import validate_candidates, validate_voters
from app.models import Candidate, Election, Position, VoterInvitation
from app.utils import login_required, record_audit


def _rows_from_request():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get('rows'), list):
        return None, (jsonify(ok=False, message='Expected a JSON body with a "rows" list.'), 400), {}
    limit = current_app.config['MAX_IMPORT_ROWS']
    if len(data['rows']) > limit:
        return None, (jsonify(ok=False, message=f'Too many rows. The limit is {limit:,} per import.'), 413), {}
    rows = [r if isinstance(r, dict) else {} for r in data['rows']]
    return rows, None, data


def _voter_report(election, rows):
    existing = [e for (e,) in db.session.query(VoterInvitation.email).filter(
        VoterInvitation.election_id == election.id, VoterInvitation.email.isnot(None)).all()]
    return validate_voters(rows, existing)


def _position_state(election):
    positions = Position.query.filter_by(election_id=election.id).all()
    return {p.name.lower(): {"name": p.name, "slots": p.candidate_slots,
                             "names": {c.name.lower() for c in p.candidates}} for p in positions}


# ---- templates ---------------------------------------------------------------

@admin_bp.route('/elections/<int:election_id>/voters/template.csv')
@login_required
def voters_template(election_id):
    Election.query.get_or_404(election_id)
    return _csv_response([["name", "email"], ["Amina Yusuf", "amina@example.com"], ["Daniel Okoye", "daniel@example.com"]],
                         "voters-template.csv")


@admin_bp.route('/elections/<int:election_id>/candidates/template.csv')
@login_required
def candidates_template(election_id):
    Election.query.get_or_404(election_id)
    return _csv_response([
        ["position", "name", "bio", "photo_url"],
        ["President", "Amina Yusuf", "Third-year engineering student.", "https://example.com/amina.jpg"],
        ["President", "Daniel Okoye", "Runs the debate society.", ""],
        ["Treasurer", "Priya Nair", "", ""],
    ], "candidates-template.csv")


# ---- voters ---------------------------------------------------------------------

@admin_bp.route('/elections/<int:election_id>/voters/import/validate', methods=['POST'])
@login_required
def voters_import_validate(election_id):
    election = Election.query.get_or_404(election_id)
    rows, error, _ = _rows_from_request()
    if error:
        return error
    return jsonify(ok=True, **_voter_report(election, rows).as_dict())


@admin_bp.route('/elections/<int:election_id>/voters/import', methods=['POST'])
@login_required
def voters_import(election_id):
    election = Election.query.get_or_404(election_id)
    rows, error, data = _rows_from_request()
    if error:
        return error
    report = _voter_report(election, rows)
    skip_invalid = bool(data.get('skip_invalid'))
    if report.invalid and not skip_invalid:
        return jsonify(ok=False, message=f'{len(report.invalid)} row(s) need fixing before import.',
                       **report.as_dict()), 422
    allocator = KeyAllocator(election)
    created = [new_invitation(election, allocator, r.row['name'], r.row['email']) for r in report.valid]
    db.session.add_all(created)
    db.session.commit()
    if created:
        record_audit('invitations_imported', f'Imported {len(created)} voter(s) into {election.name}', election_id=election.id)
    return jsonify(ok=True, created=len(created), skipped=len(report.invalid),
                   rejected=[r.as_dict() for r in report.invalid],
                   message=f'Imported {len(created)} voter{"s" if len(created) != 1 else ""}.')


# ---- candidates -------------------------------------------------------------------

@admin_bp.route('/elections/<int:election_id>/candidates/import/validate', methods=['POST'])
@login_required
def candidates_import_validate(election_id):
    election = Election.query.get_or_404(election_id)
    rows, error, data = _rows_from_request()
    if error:
        return error
    report = validate_candidates(rows, _position_state(election), bool(data.get('create_missing')))
    return jsonify(ok=True, **report.as_dict())


@admin_bp.route('/elections/<int:election_id>/candidates/import', methods=['POST'])
@login_required
def candidates_import(election_id):
    election = Election.query.get_or_404(election_id)
    rows, error, data = _rows_from_request()
    if error:
        return error
    report = validate_candidates(rows, _position_state(election), bool(data.get('create_missing')))
    if report.invalid and not data.get('skip_invalid'):
        return jsonify(ok=False, message=f'{len(report.invalid)} row(s) need fixing before import.',
                       **report.as_dict()), 422

    positions = {p.name.lower(): p for p in Position.query.filter_by(election_id=election.id).all()}
    next_position_order = (db.session.query(db.func.max(Position.order_index)).filter_by(election_id=election.id).scalar() or 0)
    # Only create positions that at least one valid row will use.
    needed = {r.row['position'].lower() for r in report.valid}
    for new in report.new_positions:
        key = new['name'].lower()
        if key in needed and key not in positions:
            next_position_order += 1
            position = Position(election=election, name=new['name'], candidate_slots=max(1, new['slots']),
                                order_index=next_position_order)
            db.session.add(position)
            positions[key] = position
    db.session.flush()

    order = {}
    for result in report.valid:
        row = result.row
        position = positions[row['position'].lower()]
        if position.id not in order:
            order[position.id] = (db.session.query(db.func.max(Candidate.order_index)).filter_by(position_id=position.id).scalar() or 0)
        order[position.id] += 1
        db.session.add(Candidate(position=position, name=row['name'], description=row['bio'] or None,
                                 photo_url=row['photo_url'] or None, order_index=order[position.id]))
    db.session.commit()
    if report.valid:
        record_audit('candidates_imported', f'Imported {len(report.valid)} candidate(s) into {election.name}',
                     election_id=election.id)
    n = len(report.valid)
    return jsonify(ok=True, created=n, skipped=len(report.invalid),
                   new_positions=len([p for p in report.new_positions if p['name'].lower() in needed]),
                   rejected=[r.as_dict() for r in report.invalid],
                   message=f'Imported {n} candidate{"s" if n != 1 else ""}.')
