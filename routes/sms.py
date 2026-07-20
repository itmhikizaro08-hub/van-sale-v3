from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from app import db
from models.notification import SMSLog
from models.customer import Customer
from services.sms_service import send_sms, send_overdue_reminders

sms_bp = Blueprint('sms', __name__)


@sms_bp.route('/')
@login_required
def index():
    if not current_user.can_access('sms'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    logs = SMSLog.query.order_by(SMSLog.created_at.desc()).limit(200).all()
    stats = {
        'total': SMSLog.query.count(),
        'sent': SMSLog.query.filter_by(status='sent').count(),
        'failed': SMSLog.query.filter_by(status='failed').count(),
        'pending': SMSLog.query.filter_by(status='pending').count(),
        'disabled': SMSLog.query.filter_by(status='disabled').count(),
    }
    return render_template('sms/index.html', logs=logs, stats=stats)


@sms_bp.route('/retry/<int:log_id>', methods=['POST'])
@login_required
def retry(log_id):
    if not current_user.can_write('sms'):
        return jsonify({'error': 'Permission denied'}), 403
    log = SMSLog.query.get_or_404(log_id)
    if log.status not in ('failed', 'disabled'):
        return jsonify({'error': 'Only failed or disabled messages can be retried.'}), 400
    result = send_sms(log.phone_number, log.message, sms_type=log.sms_type,
                       recipient_name=log.recipient_name)
    return jsonify({'success': True, 'sent': result,
                     'message': 'Message resent successfully.' if result else 'Retry failed — check the error details.'})


@sms_bp.route('/send', methods=['GET', 'POST'])
@login_required
def send():
    if not current_user.can_write('sms'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('sms.index'))
    customers = Customer.query.filter_by(status='active').order_by(Customer.name).all()
    if request.method == 'POST':
        phone = request.form.get('phone')
        message = request.form.get('message')
        if phone and message:
            result = send_sms(phone, message, sms_type='custom',
                              recipient_name=request.form.get('recipient_name'))
            if result:
                flash('SMS sent successfully!', 'success')
            else:
                flash('Failed to send SMS. Check API configuration.', 'danger')
        return redirect(url_for('sms.index'))
    return render_template('sms/send.html', customers=customers)


@sms_bp.route('/bulk', methods=['GET'])
@login_required
def bulk_form():
    if not current_user.can_write('sms'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('sms.index'))
    customers = Customer.query.filter_by(status='active').filter(
        Customer.phone.isnot(None), Customer.phone != ''
    ).order_by(Customer.name).all()
    return render_template('sms/bulk.html', customers=customers)


@sms_bp.route('/bulk', methods=['POST'])
@login_required
def bulk():
    """Send SMS to multiple customers."""
    if not current_user.can_write('sms'):
        return jsonify({'error': 'Permission denied'}), 403
    data = request.get_json()
    message = (data.get('message') or '').strip()
    customer_ids = data.get('customer_ids', [])
    if not message:
        return jsonify({'error': 'Message is required.'}), 400
    if not customer_ids:
        return jsonify({'error': 'Select at least one customer.'}), 400
    sent, failed = 0, 0
    for cid in customer_ids:
        customer = Customer.query.get(cid)
        if customer and customer.phone:
            if send_sms(customer.phone, message, sms_type='custom', recipient_name=customer.name):
                sent += 1
            else:
                failed += 1
    return jsonify({'success': True, 'sent': sent, 'failed': failed,
                     'message': f'Sent {sent} message(s){f", {failed} failed" if failed else ""}.'})


@sms_bp.route('/overdue-reminders', methods=['POST'])
@login_required
def overdue_reminders():
    if not current_user.can_write('sms'):
        return jsonify({'error': 'Permission denied'}), 403
    count = send_overdue_reminders()
    return jsonify({'success': True, 'sent': count,
                     'message': f'Sent {count} overdue reminder(s).' if count
                                else 'No customers with an outstanding balance — nothing to send.'})
