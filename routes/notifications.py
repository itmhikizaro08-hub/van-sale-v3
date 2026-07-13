from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from app import db
from models.notification import Notification, NotificationRead

notifications_bp = Blueprint('notifications', __name__)


@notifications_bp.route('/')
@login_required
def index():
    if not current_user.can_access('notifications'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    start = request.args.get('start', (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end   = request.args.get('end',   datetime.utcnow().strftime('%Y-%m-%d'))

    notifications = Notification.query.filter(
        Notification.created_at >= start,
        Notification.created_at <= end + ' 23:59:59'
    ).order_by(Notification.created_at.desc()).all()

    read_ids = {r.notification_id for r in
                NotificationRead.query.filter_by(user_id=current_user.id).all()}

    unread_count = sum(1 for n in notifications if n.id not in read_ids)
    resolved_count = sum(1 for n in notifications if n.is_read)

    return render_template('notifications/index.html', notifications=notifications,
        read_ids=read_ids, start=start, end=end,
        total_count=len(notifications), unread_count=unread_count, resolved_count=resolved_count)


@notifications_bp.route('/<int:notif_id>/read', methods=['POST'])
@login_required
def mark_read(notif_id):
    if not current_user.can_access('notifications'):
        return jsonify({'error': 'Permission denied'}), 403

    Notification.query.get_or_404(notif_id)
    already = NotificationRead.query.filter_by(
        notification_id=notif_id, user_id=current_user.id).first()
    if not already:
        db.session.add(NotificationRead(notification_id=notif_id, user_id=current_user.id))
        db.session.commit()
    return jsonify({'success': True})


@notifications_bp.route('/mark-all-read', methods=['POST'])
@login_required
def mark_all_read():
    if not current_user.can_access('notifications'):
        return jsonify({'error': 'Permission denied'}), 403

    already_read = {r.notification_id for r in
                     NotificationRead.query.filter_by(user_id=current_user.id).all()}
    unread_ids = [n.id for n in Notification.query.with_entities(Notification.id).all()
                  if n.id not in already_read]
    for nid in unread_ids:
        db.session.add(NotificationRead(notification_id=nid, user_id=current_user.id))
    db.session.commit()
    return jsonify({'success': True, 'marked': len(unread_ids)})


@notifications_bp.route('/<int:notif_id>/resolve', methods=['POST'])
@login_required
def resolve(notif_id):
    if not current_user.can_approve_module('notifications'):
        return jsonify({'error': 'Permission denied'}), 403

    n = Notification.query.get_or_404(notif_id)
    n.is_read = True
    db.session.commit()
    return jsonify({'success': True})


@notifications_bp.route('/generate', methods=['POST'])
@login_required
def generate():
    """Refresh system notifications."""
    if not current_user.can_access('notifications'):
        return jsonify({'error': 'Permission denied'}), 403

    from services.notification_service import check_all_notifications
    count = check_all_notifications()
    return jsonify({'generated': count})
