from app import db
from datetime import datetime


class Payment(db.Model):
    __tablename__ = 'payments'

    id = db.Column(db.Integer, primary_key=True)
    payment_number = db.Column(db.String(30), unique=True, nullable=False)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    payment_method = db.Column(db.String(30), default='cash')
    # cash, mobile_money, bank_transfer, cheque
    reference_number = db.Column(db.String(100))
    reference_note   = db.Column(db.String(255))  # cross-check with physical books
    payment_date = db.Column(db.DateTime, default=datetime.utcnow)
    received_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    notes = db.Column(db.Text)
    status = db.Column(db.String(20), default='completed')  # completed, void
    voided_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    voided_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    received_by = db.relationship('User', foreign_keys=[received_by_id])
    voided_by = db.relationship('User', foreign_keys=[voided_by_id])

    @property
    def status_badge(self):
        return {'completed': 'bg-success', 'void': 'bg-secondary'}.get(self.status, 'bg-secondary')

    @property
    def method_icon(self):
        icons = {
            'cash': 'fa-money-bill-wave',
            'mobile_money': 'fa-mobile-alt',
            'bank_transfer': 'fa-university',
            'cheque': 'fa-file-alt'
        }
        return icons.get(self.payment_method, 'fa-credit-card')

    @property
    def method_badge(self):
        badges = {
            'cash': 'bg-success',
            'mobile_money': 'bg-info text-dark',
            'bank_transfer': 'bg-primary',
            'cheque': 'bg-warning text-dark'
        }
        return badges.get(self.payment_method, 'bg-secondary')

    def to_dict(self):
        return {
            'id': self.id,
            'payment_number': self.payment_number,
            'amount': self.amount,
            'payment_method': self.payment_method,
            'payment_date': self.payment_date.isoformat() if self.payment_date else None,
            'reference_number': self.reference_number
        }

    def __repr__(self):
        return f'<Payment {self.payment_number} - GHS {self.amount}>'
