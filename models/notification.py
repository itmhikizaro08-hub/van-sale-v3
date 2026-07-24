from app import db
from datetime import datetime


# ── Notification ───────────────────────────────────────────────────────────────
class Notification(db.Model):
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    notification_type = db.Column(db.String(50))
    # low_stock, outstanding_account, missed_visit, license_expiry, maintenance_due, info, warning, danger
    icon = db.Column(db.String(50), default='fa-bell')
    # Whether management has resolved the underlying issue — gates whether
    # notification_service re-raises a duplicate alert. NOT per-user "seen"
    # state; that's tracked separately in NotificationRead so one person
    # reading an alert doesn't make it disappear for everyone else.
    is_read = db.Column(db.Boolean, default=False)
    link = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def type_class(self):
        return {
            'low_stock': 'warning', 'outstanding_account': 'danger',
            'missed_visit': 'info', 'license_expiry': 'warning',
            'maintenance_due': 'danger', 'info': 'info',
            'warning': 'warning', 'danger': 'danger'
        }.get(self.notification_type, 'info')


class NotificationRead(db.Model):
    """Per-user 'I've seen this' state — independent of Notification.is_read
    (which tracks whether management resolved the underlying issue)."""
    __tablename__ = 'notification_reads'

    id = db.Column(db.Integer, primary_key=True)
    notification_id = db.Column(db.Integer, db.ForeignKey('notifications.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    read_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('notification_id', 'user_id', name='uq_notification_user'),)
