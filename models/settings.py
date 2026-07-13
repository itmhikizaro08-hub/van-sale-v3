"""Singleton app/company settings."""
from datetime import datetime
from app import db


class Settings(db.Model):
    __tablename__ = 'settings'

    id = db.Column(db.Integer, primary_key=True)

    # Company profile
    company_name = db.Column(db.String(150))
    company_phone = db.Column(db.String(30))
    company_email = db.Column(db.String(120))
    company_address = db.Column(db.String(255))
    company_logo = db.Column(db.String(255))  # relative path under uploads/

    # System settings
    default_reorder_level = db.Column(db.Integer, default=10)
    invoice_prefix = db.Column(db.String(10), default='INV-')
    default_payment_terms = db.Column(db.String(100))
    sms_enabled = db.Column(db.Boolean, default=True)

    # SMS provider config — set through Settings so a non-technical admin
    # never has to edit environment files or restart the server. Falls back
    # to the SMS_PROVIDER/ARKESEL_*/HUBTEL_* env vars if left blank here.
    sms_provider = db.Column(db.String(20), default='arkesel')
    arkesel_api_key = db.Column(db.String(255))
    arkesel_sender_name = db.Column(db.String(20), default='VanSales')
    hubtel_client_id = db.Column(db.String(255))
    hubtel_client_secret = db.Column(db.String(255))
    at_username = db.Column(db.String(100), default='sandbox')
    at_api_key = db.Column(db.String(255))

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def get(cls):
        """Get the singleton settings row, seeding it from app config on first use."""
        s = cls.query.get(1)
        if not s:
            from flask import current_app
            s = cls(
                id=1,
                company_name=current_app.config['COMPANY_NAME'],
                company_phone=current_app.config['COMPANY_PHONE'],
                company_email=current_app.config['COMPANY_EMAIL'],
                company_address=current_app.config['COMPANY_ADDRESS'],
            )
            db.session.add(s)
            db.session.commit()
        return s


class SettingsAuditLog(db.Model):
    """Who changed what in Settings, and when — company/system/permissions."""
    __tablename__ = 'settings_audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    category = db.Column(db.String(20), nullable=False)  # company, system, permissions
    summary = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id])
