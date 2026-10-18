from flask import flash, redirect, render_template, request, session, url_for

from app import limiter
from app.admin import admin_bp
from app.models import AdminUser
from app.utils import login_required, record_audit


def _safe_next(target):
    if target and target.startswith("/admin") and not target.startswith("//"):
        return target
    return None


@admin_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute; 60 per hour", methods=["POST"])
def login():
    if session.get('admin_id'):
        return redirect(url_for('admin.dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        admin = AdminUser.query.filter_by(username=username).first()
        if admin and admin.check_password(password):
            session.clear()
            session.permanent = True
            session['admin_id'] = admin.id
            session['is_super_admin'] = admin.is_super_admin
            session['admin_name'] = admin.username
            record_audit('admin_login', f'Admin {admin.username} logged in', admin_id=admin.id)
            return redirect(_safe_next(request.args.get('next')) or url_for('admin.dashboard'))
        flash('Incorrect username or password.', 'danger')
    return render_template('admin/login.html', username=request.form.get('username', ''))


@admin_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    admin_id = session.get('admin_id')
    session.clear()
    if admin_id:
        record_audit('admin_logout', 'Admin logged out', admin_id=admin_id)
    return redirect(url_for('admin.login'))
