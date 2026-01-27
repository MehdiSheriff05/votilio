import secrets
import re
from datetime import datetime
from email.utils import parseaddr
from typing import Optional, Set
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import (current_app, flash, redirect, render_template, request,
                   session, url_for, jsonify)

from app import db
from app.admin import admin_bp
from app.email_utils import generate_6_digit_code, send_email
from app.models import (AdminUser, Candidate, Election, Position,
                        VoterInvitation, Vote, AuditLog, SystemSettings)
from app.utils import (login_required, record_audit, super_admin_required,
                       save_uploaded_image, render_email_template, format_display_time,
                       active_timezone_label)

COMMON_TIMEZONES = [
    "UTC",
    "Europe/London",
    "Europe/Berlin",
    "Europe/Paris",
    "Africa/Nairobi",
    "Asia/Dubai",
    "Asia/Kolkata",
    "Asia/Singapore",
    "Asia/Tokyo",
    "Australia/Sydney",
    "America/Toronto",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Sao_Paulo",
]


@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Basic username/password login for the admin console."""
    if request.method == 'POST':
        # this chunk just checks creds the simple way
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        admin = AdminUser.query.filter_by(username=username).first()
        if admin and admin.check_password(password):
            session['admin_id'] = admin.id
            session['is_super_admin'] = admin.is_super_admin
            session['admin_name'] = admin.username
            # log in audit trail so we know who hopped in
            record_audit('admin_login', f'Admin {admin.username} logged in', admin_id=admin.id)
            flash('Welcome back!', 'success')
            return redirect(url_for('admin.dashboard'))
        flash('Invalid credentials.', 'danger')
    return render_template('admin/login.html')


@admin_bp.route('/logout')
@login_required
def logout():
    """Clears the admin session and records the logout event."""
    admin_id = session.get('admin_id')
    session.pop('admin_id', None)
    session.pop('is_super_admin', None)
    session.pop('admin_name', None)
    # log out also lands in audit list so we have symmetry
    if admin_id:
        record_audit('admin_logout', 'Admin logged out', admin_id=admin_id)
    flash('Logged out.', 'info')
    return redirect(url_for('admin.login'))


@admin_bp.route('/')
@login_required
def dashboard():
    """Home screen that summarizes participation for every election."""
    # dashboard just shows quick stats for each election
    elections = Election.query.order_by(Election.id.desc()).all()
    stats = []
    for election in elections:
        total = len(election.invitations)
        voted = sum(1 for inv in election.invitations if inv.used)
        not_voted = total - voted
        stats.append({
            'election': election,
            'total': total,
            'voted': voted,
            'not_voted': not_voted,
        })
    return render_template('admin/dashboard.html', stats=stats)


@admin_bp.route('/admins')
@login_required
@super_admin_required
def manage_admins():
    """Super-admin only list of all accounts with CRUD options."""
    # only super admins can peek at this list of peers
    admins = AdminUser.query.order_by(AdminUser.username).all()
    return render_template('admin/admin_users.html', admins=admins)


@admin_bp.route('/admins/create', methods=['POST'])
@login_required
@super_admin_required
def create_admin_user():
    """Creates a new admin account from the modal on the admin list."""
    # lightweight admin creator, super only
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    is_super_admin = request.form.get('is_super_admin') == 'on'
    if not username or not password:
        flash('Username and password are required.', 'danger')
        return redirect(url_for('admin.manage_admins'))
    if AdminUser.query.filter_by(username=username).first():
        flash('Username already exists.', 'danger')
        return redirect(url_for('admin.manage_admins'))
    admin = AdminUser(username=username, is_super_admin=is_super_admin)
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()
    record_audit('admin_created', f'New admin {username} created')
    flash('Admin user created.', 'success')
    return redirect(url_for('admin.manage_admins'))


@admin_bp.route('/admins/<int:admin_id>/reset_password', methods=['POST'])
@login_required
@super_admin_required
def reset_admin_password(admin_id):
    """Resets a selected admin's password when super admin requests it."""
    # resetting passwords happens right here
    password = request.form.get('password', '').strip()
    if not password:
        flash('Password is required.', 'danger')
        return redirect(url_for('admin.manage_admins'))
    admin = AdminUser.query.get_or_404(admin_id)
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()
    record_audit('admin_password_reset', f'Password reset for {admin.username}')
    flash('Password updated.', 'success')
    return redirect(url_for('admin.manage_admins'))


@admin_bp.route('/admins/<int:admin_id>/update', methods=['POST'])
@login_required
@super_admin_required
def update_admin(admin_id):
    """Allows super admins to rename accounts or toggle super status."""
    # editing admin accounts in place
    admin = AdminUser.query.get_or_404(admin_id)
    username = request.form.get('username', '').strip()
    is_super = request.form.get('is_super_admin') == 'on'
    if not username:
        flash('Username is required.', 'danger')
        return redirect(url_for('admin.manage_admins'))
    existing = AdminUser.query.filter(AdminUser.username == username, AdminUser.id != admin.id).first()
    if existing:
        flash('Username already taken.', 'danger')
        return redirect(url_for('admin.manage_admins'))
    if admin.is_super_admin and not is_super:
        # if demoting make sure at least one other super stays
        others = AdminUser.query.filter(AdminUser.is_super_admin.is_(True), AdminUser.id != admin.id).count()
        if others == 0:
            flash('Need at least one super admin.', 'warning')
            return redirect(url_for('admin.manage_admins'))
    admin.username = username
    admin.is_super_admin = is_super
    db.session.add(admin)
    db.session.commit()
    record_audit('admin_updated', f'Admin {admin.username} updated')
    flash('Admin updated.', 'success')
    return redirect(url_for('admin.manage_admins'))


@admin_bp.route('/admins/<int:admin_id>/delete', methods=['POST'])
@login_required
@super_admin_required
def delete_admin(admin_id):
    """Removes an admin account after sanity checks."""
    # full delete with safety checks
    admin = AdminUser.query.get_or_404(admin_id)
    if admin.id == session.get('admin_id'):
        flash('You cannot delete your own account.', 'danger')
        return redirect(url_for('admin.manage_admins'))
    if admin.is_super_admin:
        others = AdminUser.query.filter(AdminUser.is_super_admin.is_(True), AdminUser.id != admin.id).count()
        if others == 0:
            flash('Need at least one super admin.', 'warning')
            return redirect(url_for('admin.manage_admins'))
    db.session.delete(admin)
    db.session.commit()
    record_audit('admin_deleted', f'Admin {admin.username} deleted')
    flash('Admin account deleted.', 'info')
    return redirect(url_for('admin.manage_admins'))


@admin_bp.route('/settings/email', methods=['GET', 'POST'])
@login_required
@super_admin_required
def system_settings():
    """UI for editing SMTP credentials and email templates."""
    settings = SystemSettings.get_or_create(current_app)
    if request.method == 'POST':
        host = request.form.get('smtp_host', '').strip()
        port = request.form.get('smtp_port', '').strip()
        user = request.form.get('smtp_user', '').strip()
        password = request.form.get('smtp_password', '').strip()
        sender = request.form.get('mail_sender', '').strip()
        invite_subject = request.form.get('invite_subject', '').strip()
        invite_body = request.form.get('invite_body', '').strip()
        reminder_subject = request.form.get('reminder_subject', '').strip()
        reminder_body = request.form.get('reminder_body', '').strip()
        results_subject = request.form.get('results_subject', '').strip()
        results_body = request.form.get('results_body', '').strip()
        timezone_name = request.form.get('timezone_name', '').strip() or settings.timezone_name or 'UTC'

        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            flash('Invalid timezone name. Use values such as America/New_York or Asia/Dubai.', 'danger')
            return redirect(url_for('admin.system_settings'))

        settings.smtp_host = host or settings.smtp_host
        try:
            settings.smtp_port = int(port)
        except ValueError:
            pass
        settings.smtp_user = user or None
        settings.smtp_password = password or None
        settings.mail_sender = sender or settings.mail_sender
        settings.invite_subject = invite_subject or settings.invite_subject
        settings.invite_body = invite_body or settings.invite_body
        settings.reminder_subject = reminder_subject or settings.reminder_subject
        settings.reminder_body = reminder_body or settings.reminder_body
        settings.results_subject = results_subject or settings.results_subject
        settings.results_body = results_body or settings.results_body
        settings.timezone_name = timezone_name
        db.session.add(settings)
        db.session.commit()

        current_app.config["SMTP_HOST"] = settings.smtp_host
        current_app.config["SMTP_PORT"] = settings.smtp_port
        current_app.config["SMTP_USER"] = settings.smtp_user
        current_app.config["SMTP_PASSWORD"] = settings.smtp_password
        current_app.config["MAIL_SENDER"] = settings.mail_sender

        record_audit('settings_updated', 'Email settings updated')
        flash('Email settings updated.', 'success')
        return redirect(url_for('admin.system_settings'))

    return render_template('admin/system_settings.html', settings=settings, timezone_options=COMMON_TIMEZONES)


@admin_bp.route('/logs')
@login_required
def audit_logs():
    """Shows the chronological audit trail for transparency."""
    # everybody logged in can view, but not clear
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(200).all()
    return render_template('admin/logs.html', logs=logs)


@admin_bp.route('/logs/clear', methods=['POST'])
@login_required
@super_admin_required
def clear_audit_logs():
    """Super admin only nuke button for clearing the audit trail."""
    # only super admins hit this route because of decorator up top
    # clean slate for logs and then mention that wiping happened
    AuditLog.query.delete()
    db.session.commit()
    record_audit('logs_cleared', 'Audit logs cleared by super admin')
    flash('Audit logs cleared.', 'info')
    return redirect(url_for('admin.audit_logs'))


@admin_bp.route('/elections/create', methods=['GET', 'POST'])
@login_required
def create_election():
    """Handles creation of an entirely new election shell."""
    if request.method == 'POST':
        # gather basic info from the form
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        start_time_str = request.form.get('start_time', '').strip()
        end_time_str = request.form.get('end_time', '').strip()
        access_code = request.form.get('access_code', '').strip()
        theme_primary = request.form.get('theme_primary', '').strip() or None
        theme_secondary = request.form.get('theme_secondary', '').strip() or None
        theme_accent = request.form.get('theme_accent', '').strip() or None

        if not name:
            flash('Name is required.', 'danger')
            return redirect(request.url)
        if not access_code:
            flash('Election access code is required.', 'danger')
            return redirect(request.url)
        existing_code = Election.query.filter(db.func.lower(Election.access_code) == access_code.lower()).first()
        if existing_code:
            flash('Access code already in use. Choose another.', 'danger')
            return redirect(request.url)

        start_time, start_error = _parse_local_datetime(start_time_str, 'Start time')
        end_time, end_error = _parse_local_datetime(end_time_str, 'End time')
        errors = [msg for msg in (start_error, end_error) if msg]
        if start_time and end_time and end_time <= start_time:
            errors.append('End time must be after the start time.')
        if errors:
            for message in errors:
                flash(message, 'danger')
            return redirect(request.url)

        election = Election(
            name=name,
            description=description,
            start_time=start_time,
            end_time=end_time,
            is_active=True,
            access_code=access_code,
            theme_primary=theme_primary,
            theme_secondary=theme_secondary,
            theme_accent=theme_accent,
        )
        db.session.add(election)
        db.session.commit()
        # log the fact we spun up a new election
        record_audit('election_created', f"Election '{election.name}' created", election_id=election.id)
        flash('Election created. Configure positions and candidates below.', 'success')
        return redirect(url_for('admin.edit_election', election_id=election.id))

    return render_template('admin/election_form.html')


@admin_bp.route('/elections/<int:election_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_election(election_id):
    """Primary edit surface for elections, including settings tabs."""
    # letting admins tweak the same election without running around
    election = Election.query.get_or_404(election_id)
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        start_time_str = request.form.get('start_time', '').strip()
        end_time_str = request.form.get('end_time', '').strip()
        access_code = request.form.get('access_code', '').strip()
        is_active = request.form.get('is_active') == 'on'
        theme_primary = request.form.get('theme_primary', '').strip() or None
        theme_secondary = request.form.get('theme_secondary', '').strip() or None
        theme_accent = request.form.get('theme_accent', '').strip() or None

        if not name:
            flash('Name is required.', 'danger')
            return redirect(request.url)
        if not access_code:
            flash('Election access code is required.', 'danger')
            return redirect(request.url)
        existing_code = Election.query.filter(
            db.func.lower(Election.access_code) == access_code.lower(),
            Election.id != election.id,
        ).first()
        if existing_code:
            flash('Access code already in use. Choose another.', 'danger')
            return redirect(request.url)

        start_time, start_error = _parse_local_datetime(start_time_str, 'Start time')
        end_time, end_error = _parse_local_datetime(end_time_str, 'End time')
        errors = [msg for msg in (start_error, end_error) if msg]
        if start_time and end_time and end_time <= start_time:
            errors.append('End time must be after the start time.')
        if errors:
            for message in errors:
                flash(message, 'danger')
            return redirect(request.url)

        election.name = name
        election.description = description
        election.start_time = start_time
        election.end_time = end_time
        election.access_code = access_code
        election.is_active = is_active
        election.theme_primary = theme_primary
        election.theme_secondary = theme_secondary
        election.theme_accent = theme_accent
        db.session.add(election)
        db.session.commit()
        # make sure we remember that settings got tweaked
        record_audit('election_updated', f"Election '{election.name}' updated", election_id=election.id)
        flash('Election updated.', 'success')
        return redirect(url_for('admin.edit_election', election_id=election.id))

    positions = Position.query.filter_by(election_id=election.id).order_by(Position.order_index.asc()).all()
    return render_template('admin/election_edit.html', election=election, positions=positions)


@admin_bp.route('/elections/<int:election_id>/delete', methods=['POST'])
@login_required
@super_admin_required
def delete_election(election_id):
    """Deletes an election and all of its related children."""
    # super admins can yeet an entire election when needed
    election = Election.query.get_or_404(election_id)
    name = election.name
    db.session.delete(election)
    db.session.commit()
    record_audit('election_deleted', f"Election '{name}' deleted")
    flash('Election deleted.', 'info')
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/elections/<int:election_id>/positions/create', methods=['GET', 'POST'])
@login_required
def create_position(election_id):
    """Adds a position under an election with customizable slot counts."""
    election = Election.query.get_or_404(election_id)
    if request.method == 'POST':
        # positions can roll in from edit page or direct link
        next_url = request.form.get('next') or request.args.get('next')
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        max_sel = request.form.get('candidate_slots')
        if not name:
            flash('Name is required.', 'danger')
            return redirect(next_url or request.url)
        try:
            candidate_slots = max(1, int(max_sel)) if max_sel is not None else 1
        except ValueError:
            candidate_slots = 1
        position = Position(
            election=election,
            name=name,
            description=description,
            candidate_slots=candidate_slots,
            order_index=(db.session.query(db.func.max(Position.order_index)).filter_by(election_id=election.id).scalar() or -1) + 1,
        )
        db.session.add(position)
        db.session.commit()
        record_audit('position_created', f"Position '{position.name}' added to {election.name}", election_id=election.id)
        flash('Position created. Add candidates.', 'success')
        return redirect(next_url or url_for('admin.edit_election', election_id=election.id))
    return render_template('admin/election_form.html', election=election, position_form=True)


@admin_bp.route('/positions/<int:position_id>/candidates/create', methods=['GET', 'POST'])
@login_required
def create_candidate(position_id):
    """Adds a candidate to a position, supporting optional photo upload."""
    position = Position.query.get_or_404(position_id)
    if request.method == 'POST':
        # candidate creation also supports direct file upload
        next_url = request.form.get('next') or request.args.get('next')
        current_total = len(position.candidates)
        if current_total >= position.candidate_slots:
            position.candidate_slots = current_total + 1
            db.session.add(position)
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        placeholder_choice = request.form.get('placeholder_choice', 'male').strip().lower()
        photo_file = request.files.get('photo')
        saved_path = save_uploaded_image(photo_file) if photo_file else None
        if not name:
            flash('Name is required.', 'danger')
            return redirect(next_url or request.url)
        if not saved_path and placeholder_choice in {'male', 'female'}:
            saved_path = f"img/placeholder-{placeholder_choice}.png"
        order_index = (
            db.session.query(db.func.max(Candidate.order_index))
            .filter_by(position_id=position.id)
            .scalar()
        )
        order_index = (order_index or 0) + 1
        candidate = Candidate(
            position=position,
            name=name,
            description=description,
            photo_url=saved_path or None,
            order_index=order_index,
        )
        db.session.add(candidate)
        db.session.commit()
        record_audit('candidate_created', f"Candidate '{candidate.name}' added to {position.name}", election_id=position.election_id)
        flash('Candidate added.', 'success')
        return redirect(next_url or url_for('admin.edit_election', election_id=position.election_id))
    return render_template('admin/election_form.html', position=position, candidate_form=True)


@admin_bp.route('/positions/<int:position_id>/update', methods=['POST'])
@login_required
def update_position(position_id):
    """Updates position metadata such as the description or slot count."""
    position = Position.query.get_or_404(position_id)
    next_url = request.form.get('next')
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    max_sel = request.form.get('candidate_slots')
    if not name:
        flash('Name is required.', 'danger')
        return redirect(next_url or url_for('admin.edit_election', election_id=position.election_id))
    if max_sel is not None:
        try:
            candidate_slots = max(1, int(max_sel))
        except ValueError:
            candidate_slots = 1
        position.candidate_slots = candidate_slots
    position.name = name
    position.description = description
    db.session.add(position)
    db.session.commit()
    # record that the position changed
    record_audit('position_updated', f"Position '{position.name}' updated", election_id=position.election_id)
    flash('Position updated.', 'success')
    return redirect(next_url or url_for('admin.edit_election', election_id=position.election_id))


@admin_bp.route('/elections/<int:election_id>/positions/reorder', methods=['POST'])
@login_required
def reorder_positions(election_id):
    """Reorders positions via drag-and-drop."""
    payload = request.get_json(silent=True) or {}
    order = payload.get('order', [])
    if not isinstance(order, list) or not order:
        return jsonify({"status": "error", "message": "Missing order list."}), 400
    positions = Position.query.filter(
        Position.election_id == election_id,
        Position.id.in_(order),
    ).all()
    if len(positions) != len(order):
        return jsonify({"status": "error", "message": "Invalid position list."}), 400
    by_id = {pos.id: pos for pos in positions}
    for idx, pos_id in enumerate(order):
        if pos_id in by_id:
            by_id[pos_id].order_index = idx
    db.session.commit()
    return jsonify({"status": "ok"})


@admin_bp.route('/positions/<int:position_id>/move', methods=['POST'])
@login_required
def move_position(position_id):
    """Moves a position up or down by swapping its order index."""
    position = Position.query.get_or_404(position_id)
    direction = request.form.get('direction')
    election_id = position.election_id
    if direction == 'up':
        neighbor = (
            Position.query.filter(
                Position.election_id == election_id,
                Position.order_index < position.order_index,
            )
            .order_by(Position.order_index.desc())
            .first()
        )
    else:
        neighbor = (
            Position.query.filter(
                Position.election_id == election_id,
                Position.order_index > position.order_index,
            )
            .order_by(Position.order_index.asc())
            .first()
        )
    if not neighbor:
        flash('Cannot move position further in that direction.', 'info')
        return redirect(url_for('admin.edit_election', election_id=election_id))
    position.order_index, neighbor.order_index = neighbor.order_index, position.order_index
    db.session.add(position)
    db.session.add(neighbor)
    db.session.commit()
    flash('Position order updated.', 'success')
    return redirect(url_for('admin.edit_election', election_id=election_id))


@admin_bp.route('/positions/<int:position_id>/candidates/reorder', methods=['POST'])
@login_required
def reorder_candidates(position_id):
    """Reorders candidates within a position via drag-and-drop."""
    payload = request.get_json(silent=True) or {}
    order = payload.get('order', [])
    if not isinstance(order, list) or not order:
        return jsonify({"status": "error", "message": "Missing order list."}), 400
    candidates = Candidate.query.filter(
        Candidate.position_id == position_id,
        Candidate.id.in_(order),
    ).all()
    if len(candidates) != len(order):
        return jsonify({"status": "error", "message": "Invalid candidate list."}), 400
    by_id = {cand.id: cand for cand in candidates}
    for idx, cand_id in enumerate(order):
        if cand_id in by_id:
            by_id[cand_id].order_index = idx
    db.session.commit()
    return jsonify({"status": "ok"})


@admin_bp.route('/candidates/<int:candidate_id>/update', methods=['POST'])
@login_required
def update_candidate(candidate_id):
    """Edits candidate info or replaces/removes their headshot."""
    candidate = Candidate.query.get_or_404(candidate_id)
    next_url = request.form.get('next')
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    remove_photo = request.form.get('remove_photo') == 'on'
    placeholder_choice = request.form.get('placeholder_choice', 'male').strip().lower()
    photo_file = request.files.get('photo')
    if not name:
        flash('Name is required.', 'danger')
        return redirect(next_url or url_for('admin.edit_election', election_id=candidate.position.election_id))

    if photo_file and photo_file.filename:
        # saving a new image swaps out the avatar
        saved_path = save_uploaded_image(photo_file)
        if saved_path:
            candidate.photo_url = saved_path
        else:
            flash('Unsupported image type. Use PNG, JPG, GIF, or WEBP.', 'warning')
    elif remove_photo:
        if placeholder_choice in {'male', 'female'}:
            candidate.photo_url = f"img/placeholder-{placeholder_choice}.png"
        else:
            candidate.photo_url = None

    candidate.name = name
    candidate.description = description
    db.session.add(candidate)
    db.session.commit()
    # also log candidate tweak so there's a trail
    record_audit('candidate_updated', f"Candidate '{candidate.name}' updated", election_id=candidate.position.election_id)
    flash('Candidate updated.', 'success')
    return redirect(next_url or url_for('admin.edit_election', election_id=candidate.position.election_id))


@admin_bp.route('/elections/<int:election_id>/invitations', methods=['GET', 'POST'])
@login_required
def manage_invitations(election_id):
    """Handles all invitation flows: queueing emails, managing unique keys, invitee CRM."""
    election = Election.query.get_or_404(election_id)
    active_tab = request.args.get('tab', 'invitations')
    new_keys = None
    # grabbing the full list upfront keeps totals/actions accurate for every tab render
    all_invites = VoterInvitation.query.filter_by(election_id=election.id).order_by(VoterInvitation.id.desc()).all()
    if request.method == 'POST':
        # bulk upload path
        raw_emails = request.form.get('emails', '')
        show_keys = request.form.get('show_keys') == 'on'
        invalid_rows = []
        pending_rows = []
        normalized = raw_emails.replace(';', '\n')
        for row in normalized.splitlines():
            name, email = _parse_invitee_row(row)
            if not email:
                if row.strip():
                    invalid_rows.append(row.strip())
                continue
            pending_rows.append((name, email.strip()))
        created = 0
        display_keys = []
        seen_local = set()
        for name, email in pending_rows:
            key = email.lower()
            if key in seen_local:
                continue
            seen_local.add(key)
            existing = VoterInvitation.query.filter(
                VoterInvitation.election_id == election.id,
                db.func.lower(VoterInvitation.email) == key,
            ).first()
            if existing:
                continue
            invitation = VoterInvitation(election_id=election.id, email=email, name=name)
            new_key = _generate_unique_key(election)
            invitation.set_key(new_key)
            invitation.last_generated_key = new_key
            db.session.add(invitation)
            created += 1
            if show_keys:
                display_keys.append({'email': email, 'name': name or 'N/A', 'key': new_key})
        db.session.commit()
        if created:
            record_audit('invitations_created', f'Queued {created} invitation(s) for {election.name}', election_id=election.id)
        flash(f'Queued {created} invitations. Send emails when ready.', 'success')
        if invalid_rows:
            flash(f"Skipped {len(invalid_rows)} row(s) that did not look like valid email entries.", 'warning')
        if show_keys and display_keys:
            new_keys = display_keys
            active_tab = 'invitations'
        else:
            return redirect(request.url)
    stats = _invitation_stats(election)
    # invitee_breakdown keeps the dashboard cards on the management tab tidy
    invitee_breakdown = {
        'total': len(all_invites),
        'used': sum(1 for inv in all_invites if inv.used),
        'pending': sum(1 for inv in all_invites if not inv.used),
    }
    invitational_actions = {
        'reminder_ready': sum(
            1 for inv in all_invites
            if inv.email and inv.sent_at and not inv.used and not inv.reminder_sent_at
        ),
    }
    return render_template(
        'admin/election_form.html',
        election=election,
        invitation_form=True,
        stats=stats,
        new_keys=new_keys,
        manual_key=None,
        invitations=all_invites,
        active_tab=active_tab,
        invitee_breakdown=invitee_breakdown,
        invitational_actions=invitational_actions,
    )


@admin_bp.route('/invitations/<int:invitation_id>/delete', methods=['POST'])
@login_required
def delete_invitation(invitation_id):
    """Drops an invitation entirely when an organizer wants to revoke a key."""
    invitation = VoterInvitation.query.get_or_404(invitation_id)
    election_id = invitation.election_id
    db.session.delete(invitation)
    db.session.commit()
    record_audit('invitation_deleted', f"Invitation {invitation.email or invitation.id} removed", election_id=election_id)
    flash('Invitation deleted. Generate a new key if needed.', 'info')
    next_tab = request.form.get('next_tab') or 'invitations'
    return redirect(url_for('admin.manage_invitations', election_id=election_id, tab=next_tab))


@admin_bp.route('/invitations/<int:invitation_id>/update', methods=['POST'])
@login_required
def update_invitation(invitation_id):
    """Edits invitee contact data without regenerating their history."""
    invitation = VoterInvitation.query.get_or_404(invitation_id)
    name = request.form.get('name', '').strip() or None
    email = request.form.get('email', '').strip() or None
    next_tab = request.form.get('next_tab') or 'invitees'
    if email:
        existing = VoterInvitation.query.filter(
            VoterInvitation.election_id == invitation.election_id,
            VoterInvitation.id != invitation.id,
            db.func.lower(VoterInvitation.email) == email.lower(),
        ).first()
        if existing:
            flash('Another invite already uses that email for this election.', 'warning')
            return redirect(url_for('admin.manage_invitations', election_id=invitation.election_id, tab=next_tab))
    invitation.name = name
    invitation.email = email
    db.session.add(invitation)
    db.session.commit()
    record_audit('invitation_updated', f'Invitation details updated for {invitation.email or invitation.name or invitation.id}',
                 election_id=invitation.election_id, invitation_id=invitation.id)
    flash('Invitee details updated.', 'success')
    return redirect(url_for('admin.manage_invitations', election_id=invitation.election_id, tab=next_tab))


@admin_bp.route('/elections/<int:election_id>/invitees/add', methods=['POST'])
@login_required
def add_invitee(election_id):
    """Allows admins to drop in a single invitee without running the bulk uploader."""
    election = Election.query.get_or_404(election_id)
    name = request.form.get('invitee_name', '').strip()
    email = request.form.get('invitee_email', '').strip()
    send_now = request.form.get('send_now') == 'on'
    next_tab = request.form.get('next_tab') or 'invitees'
    if not email:
        flash('Email is required to add an invitee.', 'danger')
        return redirect(url_for('admin.manage_invitations', election_id=election.id, tab=next_tab))
    # parseaddr keeps us safe from "Name <email>" style inputs
    _, parsed_email = parseaddr(email)
    if not parsed_email or '@' not in parsed_email:
        flash('Please provide a valid email address.', 'danger')
        return redirect(url_for('admin.manage_invitations', election_id=election.id, tab=next_tab))
    existing = VoterInvitation.query.filter(
        VoterInvitation.election_id == election.id,
        db.func.lower(VoterInvitation.email) == parsed_email.lower(),
    ).first()
    if existing:
        flash('An invitation for that email already exists.', 'warning')
        return redirect(url_for('admin.manage_invitations', election_id=election.id, tab=next_tab))

    invitation = VoterInvitation(election_id=election.id, name=name or None, email=parsed_email)
    new_key = _generate_unique_key(election)
    invitation.set_key(new_key)
    invitation.last_generated_key = new_key
    if send_now:
        # toggling "send now" lets admins satisfy last-minute voters quickly
        if _send_invite_email(invitation, election, new_key):
            invitation.sent_at = datetime.utcnow()
    db.session.add(invitation)
    db.session.commit()
    record_audit('invitation_created_manual', f'Manually added invitee {parsed_email}', election_id=election.id, invitation_id=invitation.id)
    if send_now:
        flash('Invitee added and email sent.', 'success')
    else:
        flash('Invitee added. Remember to send the email.', 'success')
    return redirect(url_for('admin.manage_invitations', election_id=election.id, tab=next_tab))


@admin_bp.route('/invitations/<int:invitation_id>/send', methods=['POST'])
@login_required
def send_single_invitation(invitation_id):
    """Resends or sends an individual invitation while rotating their key."""
    invitation = VoterInvitation.query.get_or_404(invitation_id)
    if not invitation.email:
        flash('This invite does not have an email address.', 'warning')
        return redirect(url_for('admin.manage_invitations', election_id=invitation.election_id, tab=request.form.get('next_tab', 'invitees')))
    election = invitation.election
    new_key = _generate_unique_key(election)
    invitation.set_key(new_key)
    invitation.last_generated_key = new_key
    if not _send_invite_email(invitation, election, new_key):
        flash('Unable to send the invitation email.', 'danger')
        return redirect(url_for('admin.manage_invitations', election_id=election.id, tab=request.form.get('next_tab', 'invitees')))
    invitation.sent_at = datetime.utcnow()
    invitation.reminder_sent_at = None
    db.session.add(invitation)
    db.session.commit()
    record_audit('invitation_sent_single', f'Resent invitation to {invitation.email}', election_id=election.id, invitation_id=invitation.id)
    flash('Invitation email sent.', 'success')
    return redirect(url_for('admin.manage_invitations', election_id=election.id, tab=request.form.get('next_tab', 'invitees')))


@admin_bp.route('/invitations/<int:invitation_id>/send_reminder', methods=['POST'])
@login_required
def send_single_reminder(invitation_id):
    """Pushes a reminder for one invitee instead of blasting the entire group."""
    invitation = VoterInvitation.query.get_or_404(invitation_id)
    next_tab = request.form.get('next_tab', 'invitees')
    if not invitation.email:
        flash('Cannot send a reminder without an email.', 'warning')
        return redirect(url_for('admin.manage_invitations', election_id=invitation.election_id, tab=next_tab))
    if invitation.used:
        flash('This voter already completed their ballot.', 'info')
        return redirect(url_for('admin.manage_invitations', election_id=invitation.election_id, tab=next_tab))
    election = invitation.election
    if not _send_reminder_email(invitation, election):
        flash('Unable to send reminder email.', 'danger')
        return redirect(url_for('admin.manage_invitations', election_id=election.id, tab=next_tab))
    invitation.reminder_sent_at = datetime.utcnow()
    db.session.add(invitation)
    db.session.commit()
    record_audit('reminder_sent_single', f'Reminder sent to {invitation.email}', election_id=election.id, invitation_id=invitation.id)
    flash('Reminder sent.', 'success')
    return redirect(url_for('admin.manage_invitations', election_id=election.id, tab=next_tab))


@admin_bp.route('/elections/<int:election_id>/send_invitations', methods=['POST'])
@login_required
def send_invitations(election_id):
    """Fires initial invitation emails to anyone who has not been reached yet."""
    election = Election.query.get_or_404(election_id)
    unsent = VoterInvitation.query.filter(
        VoterInvitation.election_id == election.id,
        VoterInvitation.sent_at.is_(None),
        VoterInvitation.email.isnot(None),
    ).all()
    if not unsent:
        flash('No pending invitations to send.', 'info')
        return redirect(url_for('admin.manage_invitations', election_id=election.id))

    sent_count = 0
    reserved: Set[str] = set()
    for invitation in unsent:
        # Generate a new key per invite so only hashes exist in the DB.
        new_key = _generate_unique_key(election, reserved)
        invitation.set_key(new_key)
        invitation.last_generated_key = new_key
        reserved.add(new_key)
        if not _send_invite_email(invitation, election, new_key):
            continue
        invitation.sent_at = datetime.utcnow()
        db.session.add(invitation)
        sent_count += 1
    db.session.commit()
    if sent_count:
        record_audit('invitations_sent', f'Sent {sent_count} invitation(s) for {election.name}', election_id=election.id)
    flash(f'Sent {sent_count} invitations.', 'success')
    return redirect(url_for('admin.manage_invitations', election_id=election.id))


@admin_bp.route('/elections/<int:election_id>/send_reminders', methods=['POST'])
@login_required
def send_reminders(election_id):
    """Queues reminder emails for voters who were emailed but still have not voted."""
    election = Election.query.get_or_404(election_id)
    pending = VoterInvitation.query.filter(
        VoterInvitation.election_id == election.id,
        VoterInvitation.sent_at.isnot(None),
        VoterInvitation.used.is_(False),
        VoterInvitation.reminder_sent_at.is_(None),
        VoterInvitation.email.isnot(None),
    ).all()
    if not pending:
        flash('No reminders to send.', 'info')
        return redirect(url_for('admin.manage_invitations', election_id=election.id))

    for invitation in pending:
        # Reminder emails intentionally do not reveal whether we know they voted.
        if not _send_reminder_email(invitation, election):
            continue
        invitation.reminder_sent_at = datetime.utcnow()
        db.session.add(invitation)
    db.session.commit()
    if pending:
        record_audit('reminders_sent', f'Sent {len(pending)} reminder(s) for {election.name}', election_id=election.id)
    flash(f'Sent {len(pending)} reminders.', 'success')
    return redirect(url_for('admin.manage_invitations', election_id=election.id))


def _invitation_stats(election: Election):
    """Small helper keeping template logic sane by returning basic totals."""
    total = len(election.invitations)
    sent = sum(1 for inv in election.invitations if inv.sent_at)
    used = sum(1 for inv in election.invitations if inv.used)
    reminder_sent = sum(1 for inv in election.invitations if inv.reminder_sent_at)
    return {'total': total, 'sent': sent, 'used': used, 'reminders': reminder_sent}


@admin_bp.route('/elections/<int:election_id>/results')
@login_required
def view_results(election_id):
    """Admin-facing results breakdown with turnout plus winners."""
    election = Election.query.get_or_404(election_id)
    total = len(election.invitations)
    voted = sum(1 for inv in election.invitations if inv.used)
    not_voted = total - voted
    position_results = election.summarize_results()
    public_results_url = None
    if election.results_public and election.results_slug:
        public_results_url = url_for('public.public_results', slug=election.results_slug, _external=True, _scheme="https")
    return render_template(
        'admin/dashboard.html',
        results_view=True,
        election=election,
        totals={'total': total, 'voted': voted, 'not_voted': not_voted},
        position_results=position_results,
        public_results_url=public_results_url,
    )


@admin_bp.route('/elections/<int:election_id>/results/publish', methods=['POST'])
@login_required
def publish_results(election_id):
    """Toggles whether the election's results are exposed publicly."""
    election = Election.query.get_or_404(election_id)
    action = request.form.get('action')
    if action == 'publish':
        if not election.results_slug:
            election.results_slug = _generate_results_slug(election.name)
        election.results_public = True
        flash('Public results link enabled.', 'success')
    else:
        election.results_public = False
        flash('Public results link disabled.', 'info')
    db.session.add(election)
    db.session.commit()
    record_audit('results_visibility_changed', f"Results visibility updated for {election.name}", election_id=election.id)
    return redirect(url_for('admin.view_results', election_id=election.id))


@admin_bp.route('/elections/<int:election_id>/results/send', methods=['POST'])
@login_required
def send_results_link(election_id):
    """Sends the public results link to all voters with an email on file."""
    election = Election.query.get_or_404(election_id)
    if not election.results_public or not election.results_slug:
        flash('Publish the results link before sending.', 'warning')
        return redirect(url_for('admin.view_results', election_id=election.id))

    recipients = VoterInvitation.query.filter(
        VoterInvitation.election_id == election.id,
        VoterInvitation.email.isnot(None),
    ).all()
    if not recipients:
        flash('No voter emails available to notify.', 'info')
        return redirect(url_for('admin.view_results', election_id=election.id))

    results_url = url_for('public.public_results', slug=election.results_slug, _external=True, _scheme="https")
    settings = SystemSettings.get_or_create()
    sent_count = 0
    for invitation in recipients:
        recipient_label = invitation.name or invitation.email or "Votilio voter"
        context = {
            "election_name": election.name,
            "election_code": election.access_code or "",
            "results_url": results_url,
            "recipient": recipient_label,
            "recipient_email": invitation.email,
        }
        subject = render_email_template(settings.results_subject, context)
        body = render_email_template(settings.results_body, context)
        try:
            send_email([invitation.email], subject, body)
            sent_count += 1
        except Exception:
            continue

    if sent_count:
        record_audit('results_link_sent', f'Sent results link to {sent_count} voter(s) for {election.name}', election_id=election.id)
    flash(f'Sent {sent_count} results email(s).', 'success')
    return redirect(url_for('admin.view_results', election_id=election.id))


def _parse_local_datetime(raw_value: str, label: str):
    """Safely parses datetime-local input, returning errors to bubble up."""
    if not raw_value:
        return None, None
    try:
        return datetime.fromisoformat(raw_value), None
    except ValueError:
        return None, f'{label} must be a valid local date and time.'


def _generate_unique_key(election: Election, reserved: Optional[Set[str]] = None) -> str:
    """Keeps looping until we find a 6-digit code not in use for the election."""
    reserved = reserved or set()
    while True:
        candidate_key = generate_6_digit_code()
        if candidate_key in reserved:
            continue
        collision = False
        with db.session.no_autoflush:
            for invitation in VoterInvitation.query.filter_by(election_id=election.id):
                if invitation.check_key(candidate_key):
                    collision = True
                    break
        if not collision:
            return candidate_key


def _parse_invitee_row(raw_entry: str):
    """Support flexible 'Name, email' rows without forcing admins into CSV uploads."""
    if not raw_entry:
        return None, None
    candidate = raw_entry.strip()
    if not candidate:
        return None, None
    # allow "Name, email" or "Name | email" variations by converting to RFC format
    if '<' not in candidate and '>' not in candidate:
        for sep in ('|', ',', ';'):
            if sep in candidate:
                name_part, email_part = candidate.split(sep, 1)
                if '@' in email_part:
                    candidate = f"{name_part.strip()} <{email_part.strip()}>"
                    break
    name, email = parseaddr(candidate)
    email = email or None
    name = name or None
    if email and '@' in email:
        return name, email
    return None, None


def _generate_results_slug(name: str) -> str:
    """Creates a human friendly slug for public result URLs while avoiding collisions."""
    base = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    base = base or secrets.token_urlsafe(4).lower()
    base = base[:50]  # leave room for suffix
    suffix = 1
    slug = base
    while Election.query.filter(Election.results_slug == slug).first():
        slug = f"{base}-{suffix}"
        slug = slug[:63]
        suffix += 1
    return slug


def _window_labels(election: Election):
    """Returns localized opening/closing labels so mails and UI stay consistent."""
    tz_label = active_timezone_label()
    opening = format_display_time(election.start_time, f"Not specified ({tz_label})", render_html=False)
    closing = format_display_time(election.end_time, f"Not specified ({tz_label})", render_html=False)
    return opening, closing


def _send_invite_email(invitation: VoterInvitation, election: Election, plain_key: str) -> bool:
    """Actually fires the invitation email, swallowing SMTP errors into a bool."""
    try:
        base_link = url_for('public.vote', _external=True, _scheme="https")
    except RuntimeError:
        base_link = ''
    settings = SystemSettings.get_or_create()
    opening_time, closing_time = _window_labels(election)
    recipient_label = invitation.name or invitation.email or "Votilio voter"
    context = {
        "election_name": election.name,
        "election_code": election.access_code or "",
        "voting_key": plain_key,
        "unique_identifier": invitation.id,
        "vote_url": base_link,
        "recipient": recipient_label,
        "recipient_email": invitation.email,
        "opening_time": opening_time,
        "closing_time": closing_time,
    }
    subject = render_email_template(settings.invite_subject, context)
    body = render_email_template(settings.invite_body, context)
    try:
        send_email([invitation.email], subject, body)
        return True
    except Exception:
        return False


def _send_reminder_email(invitation: VoterInvitation, election: Election) -> bool:
    """Sends reminder emails while gracefully failing if SMTP flakes out."""
    try:
        base_link = url_for('public.vote', _external=True, _scheme="https")
    except RuntimeError:
        base_link = ''
    settings = SystemSettings.get_or_create()
    opening_time, closing_time = _window_labels(election)
    recipient_label = invitation.name or invitation.email or "Votilio voter"
    context = {
        "election_name": election.name,
        "election_code": election.access_code or "",
        "voting_key": invitation.last_generated_key or "******",
        "unique_identifier": invitation.id,
        "vote_url": base_link,
        "recipient": recipient_label,
        "recipient_email": invitation.email,
        "opening_time": opening_time,
        "closing_time": closing_time,
    }
    subject = render_email_template(settings.reminder_subject, context)
    body = render_email_template(settings.reminder_body, context)
    try:
        send_email([invitation.email], subject, body)
        return True
    except Exception:
        return False
