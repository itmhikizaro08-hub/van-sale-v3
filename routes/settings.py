"""Settings blueprint — company profile, system settings, role permissions."""
import os
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from app import db
from models.settings import Settings, SettingsAuditLog
from models.user import ROLE_PERMISSIONS, RolePermission, load_role_permissions
from services.uploads import save_upload, regenerate_pwa_icons

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
    'sms_provider': 'SMS Provider', 'arkesel_api_key': 'Arkesel API Key',
    'arkesel_sender_name': 'Arkesel Sender Name', 'hubtel_client_id': 'Hubtel Client ID',
    'hubtel_client_secret': 'Hubtel Client Secret',
    'at_username': "Africa's Talking Username", 'at_api_key': "Africa's Talking API Key",
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
            regenerate_pwa_icons(os.path.join(current_app.config['UPLOAD_FOLDER'], logo_path))
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
    try:
        reorder_level = max(0, int(request.form.get('default_reorder_level') or 10))
    except ValueError:
        flash('Default reorder level must be a whole number.', 'danger')
        return redirect(url_for('settings.index', tab='system'))
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


@settings_bp.route('/sms', methods=['POST'])
@login_required
def update_sms():
    if not current_user.can_write('settings'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('settings.index'))

    s = Settings.get()
    # Secret fields render blank in the form for security (see the "leave
    # blank to keep it" placeholder) — an empty submission must preserve the
    # existing value, not wipe it, since the browser always sends the field.
    new_arkesel_key = request.form.get('arkesel_api_key', '').strip()
    new_hubtel_secret = request.form.get('hubtel_client_secret', '').strip()
    new_at_key = request.form.get('at_api_key', '').strip()
    updates = {
        'sms_provider': request.form.get('sms_provider', s.sms_provider),
        'arkesel_api_key': new_arkesel_key or s.arkesel_api_key,
        'arkesel_sender_name': (request.form.get('arkesel_sender_name') or 'VanSales').strip(),
        'hubtel_client_id': request.form.get('hubtel_client_id', s.hubtel_client_id),
        'hubtel_client_secret': new_hubtel_secret or s.hubtel_client_secret,
        'at_username': (request.form.get('at_username') or 'sandbox').strip(),
        'at_api_key': new_at_key or s.at_api_key,
    }

    # Secret fields never go into the audit trail in plaintext — just note
    # that they changed, so a key rotation is traceable without leaking it.
    secret_fields = {'arkesel_api_key', 'hubtel_client_secret', 'at_api_key'}
    changes = []
    for field, new_value in updates.items():
        old_value = getattr(s, field)
        if old_value != new_value:
            if field in secret_fields:
                changes.append(f'{FIELD_LABELS.get(field, field)}: (changed)')
            else:
                label = FIELD_LABELS.get(field, field)
                changes.append(f'{label}: {old_value or "(empty)"} → {new_value or "(empty)"}')
            setattr(s, field, new_value)

    db.session.commit()

    if changes:
        _log_change('system', 'SMS config — ' + '; '.join(changes))
        db.session.commit()
        flash('SMS settings updated!', 'success')
    else:
        flash('No changes to save.', 'info')
    return redirect(url_for('settings.index', tab='system'))


@settings_bp.route('/sms/test', methods=['POST'])
@login_required
def test_sms():
    if not current_user.can_write('settings'):
        return {'error': 'Permission denied'}, 403

    data = request.get_json(silent=True) or {}
    phone = (data.get('phone') or '').strip()
    if not phone:
        return {'error': 'Enter a phone number to test with.'}, 400

    from services.sms_service import send_sms
    success = send_sms(phone, 'Test message from Van Sales V3 — your SMS setup is working!',
                        sms_type='custom', recipient_name='Test')

    from models.sms import SMSLog
    last = SMSLog.query.filter_by(phone_number=phone).order_by(SMSLog.id.desc()).first()
    detail = last.provider_response if last else ''

    if success:
        return {'success': True, 'message': f'Test SMS sent to {phone}.'}
    return {'error': f'Failed to send: {detail}'}, 400


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
