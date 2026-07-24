from app import db
from datetime import datetime


# ── SMS Log ────────────────────────────────────────────────────────────────────
class SMSLog(db.Model):
    __tablename__ = 'sms_logs'

    id = db.Column(db.Integer, primary_key=True)
    recipient_name = db.Column(db.String(150))
    phone_number = db.Column(db.String(20), nullable=False)
    message = db.Column(db.Text, nullable=False)
    sms_type = db.Column(db.String(50))
    # invoice_created, payment_received, overdue_reminder, visit_reminder, custom
    status = db.Column(db.String(20), default='pending')  # pending, sent, failed
    provider = db.Column(db.String(30))
    provider_response = db.Column(db.Text)
    sent_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def status_badge(self):
        return {'pending': 'bg-warning text-dark', 'sent': 'bg-success', 'failed': 'bg-danger'}.get(self.status, 'bg-secondary')
