"""
Cash Declaration — Rep-to-Cashier Cash Handover
================================================
A sales rep collects cash from customers throughout the day. Periodically
(typically end of day) they declare a lump sum, broken down by note/coin
denomination, and hand it to a cashier. Whatever cash they've collected but
not yet declared is their outstanding liability (see services/cash_decl.py).

When a cashier physically counts the handed-over cash, they record what they
actually counted; a mismatch against the declared amount is flagged as a
discrepancy for investigation, separate from the rep's running liability.
"""
from app import db
from datetime import datetime

# Ghana Cedi notes and commonly-used coins
DENOMINATIONS = [200, 100, 50, 20, 10, 5, 2, 1, 0.5, 0.2, 0.1]


class CashDeclaration(db.Model):
    __tablename__ = 'cash_declarations'

    id = db.Column(db.Integer, primary_key=True)
    declaration_number = db.Column(db.String(30), unique=True, nullable=False, index=True)
    sales_rep_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    declared_amount = db.Column(db.Float, nullable=False, default=0.0)
    counted_amount = db.Column(db.Float, nullable=True)
    discrepancy_amount = db.Column(db.Float, nullable=True)
    status = db.Column(db.String(20), default='pending')  # pending, verified, discrepancy
    notes = db.Column(db.Text)
    verified_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    verified_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sales_rep = db.relationship('User', foreign_keys=[sales_rep_id])
    verified_by = db.relationship('User', foreign_keys=[verified_by_id])
    lines = db.relationship('CashDeclarationLine', backref='declaration',
                             lazy='joined', cascade='all, delete-orphan')

    @property
    def status_badge(self):
        return {'pending': 'bg-warning text-dark', 'verified': 'bg-success',
                'discrepancy': 'bg-danger'}.get(self.status, 'bg-secondary')

    def __repr__(self):
        return f'<CashDeclaration {self.declaration_number} GHS {self.declared_amount}>'


class CashDeclarationLine(db.Model):
    __tablename__ = 'cash_declaration_lines'

    id = db.Column(db.Integer, primary_key=True)
    declaration_id = db.Column(db.Integer, db.ForeignKey('cash_declarations.id'), nullable=False)
    denomination = db.Column(db.Float, nullable=False)
    count = db.Column(db.Integer, nullable=False, default=0)
    subtotal = db.Column(db.Float, nullable=False, default=0.0)
