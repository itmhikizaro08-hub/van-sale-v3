from app import db
from datetime import datetime


# ── Supplier ───────────────────────────────────────────────────────────────────
class Supplier(db.Model):
    __tablename__ = 'suppliers'

    id = db.Column(db.Integer, primary_key=True)
    supplier_code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(150), nullable=False)
    contact_person = db.Column(db.String(150))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    address = db.Column(db.Text)
    payment_terms = db.Column(db.String(100))
    outstanding_balance = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(20), default='active')
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def status_badge(self):
        return {'active': 'bg-success', 'inactive': 'bg-secondary'}.get(self.status, 'bg-secondary')


# ── Supplier Payment ─────────────────────────────────────────────────────────────
class SupplierPayment(db.Model):
    """Money we pay TO a supplier — the mirror of Payment (money customers pay us)."""
    __tablename__ = 'supplier_payments'

    id = db.Column(db.Integer, primary_key=True)
    payment_number = db.Column(db.String(30), unique=True, nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    payment_method = db.Column(db.String(30), default='cash')
    reference_number = db.Column(db.String(100))
    reference_note = db.Column(db.String(255))  # cross-check with physical books
    payment_date = db.Column(db.DateTime, default=datetime.utcnow)
    paid_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    notes = db.Column(db.Text)
    status = db.Column(db.String(20), default='approved')  # pending, approved, rejected
    approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    supplier = db.relationship('Supplier', foreign_keys=[supplier_id])
    paid_by = db.relationship('User', foreign_keys=[paid_by_id])
    approved_by = db.relationship('User', foreign_keys=[approved_by_id])

    @property
    def method_badge(self):
        badges = {
            'cash': 'bg-success', 'mobile_money': 'bg-info text-dark',
            'bank_transfer': 'bg-primary', 'cheque': 'bg-warning text-dark'
        }
        return badges.get(self.payment_method, 'bg-secondary')

    @property
    def status_badge(self):
        return {'pending': 'bg-warning text-dark', 'approved': 'bg-success', 'rejected': 'bg-danger'}.get(self.status, 'bg-secondary')

    def __repr__(self):
        return f'<SupplierPayment {self.payment_number} - GHS {self.amount}>'
