from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app, jsonify, render_template, request, session, url_for

from app import db, limiter
from app.admin import admin_bp
from app.admin.helpers import done, fail
from app.imports import is_valid_email
from app.mailer import Message, build_mailer, load_config, text_to_html
from app.models import AdminUser, AuditLog, SystemSettings
from app.utils import (login_required, record_audit, render_email_template, super_admin_required)

COMMON_TIMEZONES = [
    "UTC", "GMT+4", "Europe/London", "Europe/Berlin", "Europe/Paris", "Africa/Nairobi", "Asia/Dubai", "Asia/Kolkata",
    "Asia/Singapore", "Asia/Tokyo", "Australia/Sydney", "America/Toronto", "America/New_York", "America/Chicago",
    "America/Denver", "America/Los_Angeles", "America/Sao_Paulo",
]
SAMPLE_CONTEXT = {
    "election_name": "Student Council 2026", "voting_key": "123456", "election_code": "council-2026",
    "vote_url": "https://vote.example.com/", "recipient": "Alex", "recipient_email": "alex@example.com",
    "opening_time": "2026-05-01 09:00 (UTC)", "closing_time": "2026-05-03 17:00 (UTC)",
    "results_url": "https://vote.example.com/results/council-2026",
}
PLACEHOLDERS = list(SAMPLE_CONTEXT.keys())


def _env_locks():
    cfg = current_app.config
    return {"provider": bool(cfg.get("EMAIL_PROVIDER")), "resend_key": bool(cfg.get("RESEND_API_KEY"))}


# ---- email -------------------------------------------------------------------

@admin_bp.route('/settings/email', methods=['GET', 'POST'])
@login_required
@super_admin_required
def system_settings():
    settings = SystemSettings.get_or_create(current_app)
    url = url_for('admin.system_settings')
    if request.method == 'POST':
        f = request.form
        provider = f.get('email_provider', settings.email_provider)
        if provider not in ('smtp', 'resend'):
            return fail('Choose SMTP or Resend.', url)
        security = f.get('smtp_security', settings.smtp_security)
        if security not in ('none', 'starttls', 'ssl'):
            return fail('SMTP security must be none, starttls or ssl.', url)
        try:
            port = int(f.get('smtp_port') or settings.smtp_port)
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            return fail('SMTP port must be a number between 1 and 65535.', url)
        for label, subject, body in (
            ('Invitation', f.get('invite_subject', ''), f.get('invite_body', '')),
            ('Reminder', f.get('reminder_subject', ''), f.get('reminder_body', '')),
            ('Results', f.get('results_subject', ''), f.get('results_body', '')),
        ):
            try:
                render_email_template(subject, SAMPLE_CONTEXT)
                render_email_template(body, SAMPLE_CONTEXT)
            except Exception as exc:
                return fail(f'{label} template error: {exc}', url)

        settings.email_provider = provider
        settings.mail_sender = f.get('mail_sender', '').strip() or settings.mail_sender
        settings.smtp_host = f.get('smtp_host', '').strip()
        settings.smtp_port, settings.smtp_security = port, security
        settings.smtp_user = f.get('smtp_user', '').strip() or None
        if f.get('smtp_password'):
            settings.smtp_password_plain = f.get('smtp_password')
        elif not settings.smtp_user:
            settings.smtp_password = None
        if f.get('resend_api_key', '').strip():
            settings.resend_api_key_plain = f.get('resend_api_key').strip()
        elif f.get('clear_resend_key') == '1':
            settings.resend_api_key = None
        settings.invite_subject = f.get('invite_subject', '').strip() or settings.invite_subject
        settings.invite_body = f.get('invite_body', '').strip() or settings.invite_body
        settings.reminder_subject = f.get('reminder_subject', '').strip() or settings.reminder_subject
        settings.reminder_body = f.get('reminder_body', '').strip() or settings.reminder_body
        settings.results_subject = f.get('results_subject', '').strip() or settings.results_subject
        settings.results_body = f.get('results_body', '').strip() or settings.results_body
        db.session.commit()
        record_audit('settings_updated', f'Email settings updated (provider: {settings.email_provider})')
        return done('Email settings saved.', url)

    cfg = load_config(settings)
    return render_template(
        'admin/settings_email.html', settings=settings, section='email', placeholders=PLACEHOLDERS,
        locks=_env_locks(), effective_provider=cfg.provider,
        has_resend_key=bool(cfg.resend_api_key), has_smtp_password=bool(settings.smtp_password),
    )


@admin_bp.route('/settings/email/test', methods=['POST'])
@login_required
@super_admin_required
@limiter.limit("10 per minute")
def test_email():
    data = request.get_json(silent=True) or {}
    to = (data.get('to') or '').strip()
    if not is_valid_email(to):
        return jsonify(ok=False, error='Enter a valid recipient address.'), 400
    keys = ('provider', 'mail_sender', 'smtp_host', 'smtp_port', 'smtp_security', 'smtp_user', 'smtp_password',
            'resend_api_key')
    overrides = {k: data[k] for k in keys if k in data and data[k] not in (None, '')}
    if 'smtp_user' in data and data['smtp_user'] == '':
        overrides['smtp_user'] = ''
    try:
        config = load_config(overrides=overrides)
    except (TypeError, ValueError):
        return jsonify(ok=False, error='Check the SMTP port.'), 400
    body = ("This is a test message from Votilio.\n\nIf you can read this, your email provider "
            f"({config.provider.upper()}) is configured correctly.")
    result = build_mailer(config).send(Message(to, 'Votilio test email', body, text_to_html(body)))
    record_audit('email_test', f'Test email to {to} via {config.provider}: {"ok" if result.ok else "failed"}')
    return jsonify(ok=result.ok, error=result.error, provider=config.provider)


# ---- general ------------------------------------------------------------------

@admin_bp.route('/settings/general', methods=['GET', 'POST'])
@login_required
@super_admin_required
def general_settings():
    settings = SystemSettings.get_or_create(current_app)
    url = url_for('admin.general_settings')
    if request.method == 'POST':
        name = request.form.get('timezone_name', '').strip() or settings.timezone_name
        from app.utils import _zoneinfo_for
        if _zoneinfo_for(name) is None:
            return fail('Use a zone like Asia/Dubai or an offset like GMT+4.', url)
        settings.timezone_name = name
        db.session.commit()
        record_audit('settings_updated', f'Display timezone set to {name}')
        return done('Timezone saved.', url)
    return render_template('admin/settings_general.html', settings=settings, section='general',
                           timezone_options=COMMON_TIMEZONES)


# ---- admins -------------------------------------------------------------------

def _admins_url():
    return url_for('admin.manage_admins')


def _other_supers(admin):
    return AdminUser.query.filter(AdminUser.is_super_admin.is_(True), AdminUser.id != admin.id).count()


@admin_bp.route('/settings/admins')
@login_required
@super_admin_required
def manage_admins():
    admins = AdminUser.query.order_by(AdminUser.username).all()
    return render_template('admin/settings_admins.html', admins=admins, section='admins')


@admin_bp.route('/settings/admins/create', methods=['POST'])
@login_required
@super_admin_required
def create_admin_user():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    if not username or len(password) < 8:
        return fail('Username is required and the password needs at least 8 characters.', _admins_url())
    if AdminUser.query.filter_by(username=username).first():
        return fail('That username is taken.', _admins_url(), 409)
    admin = AdminUser(username=username[:64], is_super_admin=request.form.get('is_super_admin') == 'on')
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()
    record_audit('admin_created', f'New admin {username} created')
    return done('Admin created.', _admins_url())


@admin_bp.route('/settings/admins/<int:admin_id>/password', methods=['POST'])
@login_required
@super_admin_required
def reset_admin_password(admin_id):
    password = request.form.get('password', '')
    if len(password) < 8:
        return fail('The password needs at least 8 characters.', _admins_url())
    admin = AdminUser.query.get_or_404(admin_id)
    admin.set_password(password)
    db.session.commit()
    record_audit('admin_password_reset', f'Password reset for {admin.username}')
    return done('Password updated.', _admins_url())


@admin_bp.route('/settings/admins/<int:admin_id>/update', methods=['POST'])
@login_required
@super_admin_required
def update_admin(admin_id):
    admin = AdminUser.query.get_or_404(admin_id)
    username = request.form.get('username', '').strip()
    is_super = request.form.get('is_super_admin') == 'on'
    if not username:
        return fail('Username is required.', _admins_url())
    if AdminUser.query.filter(AdminUser.username == username, AdminUser.id != admin.id).first():
        return fail('That username is taken.', _admins_url(), 409)
    if admin.is_super_admin and not is_super and _other_supers(admin) == 0:
        return fail('There must be at least one super admin.', _admins_url(), 409)
    admin.username, admin.is_super_admin = username[:64], is_super
    db.session.commit()
    record_audit('admin_updated', f'Admin {admin.username} updated')
    return done('Admin updated.', _admins_url())


@admin_bp.route('/settings/admins/<int:admin_id>/delete', methods=['POST'])
@login_required
@super_admin_required
def delete_admin(admin_id):
    admin = AdminUser.query.get_or_404(admin_id)
    if admin.id == session.get('admin_id'):
        return fail('You cannot delete your own account.', _admins_url(), 409)
    if admin.is_super_admin and _other_supers(admin) == 0:
        return fail('There must be at least one super admin.', _admins_url(), 409)
    AuditLog.query.filter_by(admin_id=admin.id).update({"admin_id": None})
    db.session.delete(admin)
    db.session.commit()
    record_audit('admin_deleted', f'Admin {admin.username} deleted')
    return done('Admin deleted.', _admins_url(), 'info')


# ---- audit log ----------------------------------------------------------------

@admin_bp.route('/settings/logs')
@login_required
def audit_logs():
    q = request.args.get('q', '').strip()[:100]
    query = AuditLog.query
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(db.or_(db.func.lower(AuditLog.message).like(like),
                                    db.func.lower(AuditLog.event_type).like(like)))
    logs = query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(300).all()
    return render_template('admin/settings_logs.html', logs=logs, q=q, section='logs')


@admin_bp.route('/settings/logs/clear', methods=['POST'])
@login_required
@super_admin_required
def clear_audit_logs():
    AuditLog.query.delete()
    db.session.commit()
    record_audit('logs_cleared', 'Audit log cleared by a super admin')
    return done('Audit log cleared.', url_for('admin.audit_logs'), 'info')
