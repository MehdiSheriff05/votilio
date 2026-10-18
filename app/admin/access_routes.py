from flask import render_template, request, url_for

from app import db
from app.access import current_admin
from app.admin import admin_bp
from app.admin.helpers import done, election_stats, fail
from app.models import AdminGroup, AdminUser, Election
from app.utils import login_required, record_audit, super_admin_required


# ---- who can manage one election ------------------------------------------------

@admin_bp.route('/elections/<int:election_id>/access')
@login_required
@super_admin_required
def election_access(election_id):
    election = Election.query.get_or_404(election_id)
    supers = AdminUser.query.filter_by(is_super_admin=True).order_by(AdminUser.username).all()
    candidates = [a for a in AdminUser.query.order_by(AdminUser.username).all()
                  if not a.is_super_admin and a not in election.admins]
    groups = [g for g in AdminGroup.query.order_by(AdminGroup.name).all() if g not in election.groups]
    return render_template('admin/access.html', election=election, section='access', stats=election_stats(election),
                           supers=supers, addable_admins=candidates, addable_groups=groups)


def _access_url(election_id):
    return url_for('admin.election_access', election_id=election_id)


@admin_bp.route('/elections/<int:election_id>/access/add', methods=['POST'])
@login_required
@super_admin_required
def add_election_access(election_id):
    election = Election.query.get_or_404(election_id)
    url = _access_url(election.id)
    kind, raw = request.form.get('kind'), request.form.get('id', '')
    if not raw.isdigit():
        return fail('Choose someone to add.', url)
    if kind == 'admin':
        admin = db.session.get(AdminUser, int(raw))
        if not admin or admin.is_super_admin:
            return fail('That admin was not found.', url, 404)
        if admin not in election.admins:
            election.admins.append(admin)
        label = admin.username
    elif kind == 'group':
        group = db.session.get(AdminGroup, int(raw))
        if not group:
            return fail('That group was not found.', url, 404)
        if group not in election.groups:
            election.groups.append(group)
        label = f'group {group.name}'
    else:
        return fail('Unknown type.', url)
    db.session.commit()
    record_audit('election_access_added', f'{label} can now manage {election.name}', election_id=election.id)
    return done(f'{label} can now manage this election.', url)


@admin_bp.route('/elections/<int:election_id>/access/remove', methods=['POST'])
@login_required
@super_admin_required
def remove_election_access(election_id):
    election = Election.query.get_or_404(election_id)
    url = _access_url(election.id)
    kind, raw = request.form.get('kind'), request.form.get('id', '')
    if not raw.isdigit():
        return fail('Choose who to remove.', url)
    if kind == 'admin':
        admin = db.session.get(AdminUser, int(raw))
        if admin in election.admins:
            election.admins.remove(admin)
        label = admin.username if admin else 'Admin'
    elif kind == 'group':
        group = db.session.get(AdminGroup, int(raw))
        if group in election.groups:
            election.groups.remove(group)
        label = f'group {group.name}' if group else 'Group'
    else:
        return fail('Unknown type.', url)
    db.session.commit()
    record_audit('election_access_removed', f'{label} no longer manages {election.name}', election_id=election.id)
    return done(f'{label} removed from this election.', url, 'info')


# ---- groups ----------------------------------------------------------------------

def _groups_url():
    return url_for('admin.manage_groups')


@admin_bp.route('/settings/groups')
@login_required
@super_admin_required
def manage_groups():
    groups = AdminGroup.query.order_by(AdminGroup.name).all()
    admins = AdminUser.query.filter_by(is_super_admin=False).order_by(AdminUser.username).all()
    elections = Election.query.order_by(Election.name).all()
    return render_template('admin/settings_groups.html', groups=groups, admins=admins, elections=elections, section='groups')


def _members(form):
    ids = [int(i) for i in form.getlist('members') if i.isdigit()]
    return AdminUser.query.filter(AdminUser.id.in_(ids or [-1]), AdminUser.is_super_admin.is_(False)).all()


def _election_list(form):
    ids = [int(i) for i in form.getlist('elections') if i.isdigit()]
    return Election.query.filter(Election.id.in_(ids or [-1])).all()


@admin_bp.route('/settings/groups/create', methods=['POST'])
@login_required
@super_admin_required
def create_group():
    name = request.form.get('name', '').strip()[:80]
    if not name:
        return fail('Give the group a name.', _groups_url())
    if AdminGroup.query.filter(db.func.lower(AdminGroup.name) == name.lower()).first():
        return fail('A group with that name already exists.', _groups_url(), 409)
    group = AdminGroup(name=name, members=_members(request.form), elections=_election_list(request.form))
    db.session.add(group)
    db.session.commit()
    record_audit('group_created', f'Group {name} created')
    return done('Group created.', _groups_url())


@admin_bp.route('/settings/groups/<int:group_id>/update', methods=['POST'])
@login_required
@super_admin_required
def update_group(group_id):
    group = AdminGroup.query.get_or_404(group_id)
    name = request.form.get('name', '').strip()[:80]
    if not name:
        return fail('Give the group a name.', _groups_url())
    clash = AdminGroup.query.filter(db.func.lower(AdminGroup.name) == name.lower(), AdminGroup.id != group.id).first()
    if clash:
        return fail('A group with that name already exists.', _groups_url(), 409)
    group.name = name
    group.members = _members(request.form)
    group.elections = _election_list(request.form)
    db.session.commit()
    record_audit('group_updated', f'Group {name} updated')
    return done('Group saved.', _groups_url())


@admin_bp.route('/settings/groups/<int:group_id>/delete', methods=['POST'])
@login_required
@super_admin_required
def delete_group(group_id):
    group = AdminGroup.query.get_or_404(group_id)
    name = group.name
    db.session.delete(group)
    db.session.commit()
    record_audit('group_deleted', f'Group {name} deleted')
    return done('Group deleted.', _groups_url(), 'info')
