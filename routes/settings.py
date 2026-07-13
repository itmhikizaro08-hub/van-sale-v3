"""Settings blueprint — company profile, system settings, role permissions."""
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app import db
from models.settings import Settings, SettingsAuditLog
from models.user import ROLE_PERMISSIONS, RolePermission, load_role_permissions
from services.uploads import save_upload

settings_bp = Blueprint('settings', __name__)

ROLE_LABELS = {
    'admin':             'Administrator',
    'manager':           'Manager',
    'supervisor':        'Supervisor',
    'sales_rep':         'Sales Representative',
    'warehouse_manager': 'Warehouse Manager',
    'cashier':           'Cashier',
}

FIELD_LABELS = {
    'company_name': 'Company Name', 'company_phone': 'Phone', 'company_email': 'Email',
    'company_address': 'Address', 'company_logo': 'Logo',
    'default_reorder_level': 'Default Reorder Level', 'invoice_prefix': 'Invoice Prefix',
    'default_payment_terms': 'Default Payment Terms', 'sms_enabled': 'SMS Notifications',
}

# Roles editable through the permissions tab — admin is intentionally excluded
# so nobody can accidentally lock every admin out of Settings.
EDITABLE_ROLES = [r for r in ROLE_PERMISSIONS if r != 'admin']
MODULES = list(ROLE_PERMISSIONS['admin'].keys())


def _log_change(category, summary):
    if summary:
        db.session.add(SettingsAuditLog(user_id=current_user.id, category=category, summary=summary))


def _diff_fields(obj, updates):
    """Apply updates to obj's attributes, returning a human-readable list of
    'Field: old → new' for anything that actually changed."""
    changes = []
    for field, new_value in updates.items():
        old_value = getattr(obj, field)
        if old_value != new_value:
            label = FIELD_LABELS.get(field, field)
            old_disp = old_value if old_value not in (None, '') else '(empty)'
            new_disp = new_value if new_value not in (None, '') else '(empty)'
            changes.append(f'{label}: {old_disp} → {new_disp}')
            setattr(obj, field, new_value)
    return changes


@settings_bp.route('/')
@login_required
def index():
    if not current_user.can_access('settings'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    selected_role = request.args.get('role', 'manager')
    if selected_role not in EDITABLE_ROLES:
        selected_role = EDITABLE_ROLES[0]

    perms = {p.module: p for p in RolePermission.query.filter_by(role=selected_role).all()}

    audit_logs = []
    if current_user.is_admin:
        audit_logs = SettingsAuditLog.query.order_by(SettingsAuditLog.created_at.desc()).limit(50).all()

    return render_template('settings/index.html',
        settings=Settings.get(), tab=request.args.get('tab', 'company'),
        editable_roles=EDITABLE_ROLES, role_labels=ROLE_LABELS,
        selected_role=selected_role, modules=MODULES, perms=perms,
        audit_logs=audit_logs)


@settings_bp.route('/company', methods=['POST'])
@login_required
def update_company():
    if not current_user.can_write('settings'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('settings.index'))

    s = Settings.get()
    updates = {
        'company_name': request.form.get('company_name', s.company_name),
        'company_phone': request.form.get('company_phone', s.company_phone),
        'company_email': request.form.get('company_email', s.company_email),
        'company_address': request.form.get('company_address', s.company_address),
    }

    logo_file = request.files.get('logo')
    if logo_file and logo_file.filename:
        logo_path = save_upload(logo_file, 'logos')
        if logo_path:
            updates['company_logo'] = logo_path
        else:
            flash('Logo not updated — use a PNG, JPG, GIF, or WEBP image.', 'warning')

    changes = _diff_fields(s, updates)
    db.session.commit()

    if changes:
        _log_change('company', '; '.join(changes))
        db.session.commit()
        flash('Company profile updated!', 'success')
    else:
        flash('No changes to save.', 'info')
    return redirect(url_for('settings.index', tab='company'))


@settings_bp.route('/system', methods=['POST'])
@login_required
def update_system():
    if not current_user.can_write('settings'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('settings.index'))

    s = Settings.get()
    reorder_level = max(0, int(request.form.get('default_reorder_level') or 10))
    updates = {
        'default_reorder_level': reorder_level,
        'invoice_prefix': (request.form.get('invoice_prefix') or 'INV-').strip(),
        'default_payment_terms': request.form.get('default_payment_terms'),
        'sms_enabled': request.form.get('sms_enabled') == 'on',
    }

    changes = _diff_fields(s, updates)
    db.session.commit()

    if changes:
        _log_change('system', '; '.join(changes))
        db.session.commit()
        flash('System settings updated!', 'success')
    else:
        flash('No changes to save.', 'info')
    return redirect(url_for('settings.index', tab='system'))


@settings_bp.route('/permissions', methods=['POST'])
@login_required
def update_permissions():
    if not current_user.is_admin:
        flash('Permission denied.', 'danger')
        return redirect(url_for('settings.index'))

    role = request.form.get('role')
    if role not in EDITABLE_ROLES:
        flash('That role cannot be edited here.', 'danger')
        return redirect(url_for('settings.index', tab='permissions'))

    existing = {p.module: p for p in RolePermission.query.filter_by(role=role).all()}
    changes = []
    for module in MODULES:
        scope = request.form.get(f'scope_{module}', 'none')
        can_write = request.form.get(f'write_{module}') == 'on'
        can_approve = request.form.get(f'approve_{module}') == 'on'
        row = existing.get(module)

        old = (row.scope, row.can_write, row.can_approve) if row else ('none', False, False)
        new = (scope, can_write, can_approve)
        if old != new:
            changes.append(f'{module}: {old[0]}/{"w" if old[1] else "-"}{"a" if old[2] else "-"} '
                            f'→ {new[0]}/{"w" if new[1] else "-"}{"a" if new[2] else "-"}')

        if row:
            row.scope, row.can_write, row.can_approve = scope, can_write, can_approve
        else:
            db.session.add(RolePermission(role=role, module=module, scope=scope,
                                           can_write=can_write, can_approve=can_approve))
    db.session.commit()
    load_role_permissions()

    if changes:
        _log_change('permissions', f'{ROLE_LABELS.get(role, role)} — ' + '; '.join(changes))
        db.session.commit()
        flash(f'Permissions updated for {ROLE_LABELS.get(role, role)}.', 'success')
    else:
        flash('No changes to save.', 'info')
    return redirect(url_for('settings.index', tab='permissions', role=role))
