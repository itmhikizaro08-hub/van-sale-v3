"""
Credit / Debit Notes
====================
See models/returns.py for the ReturnOrder a credit note is usually issued
against.
"""
from app import db
from datetime import datetime


class CreditNote(db.Model):
    __tablename__ = 'credit_notes'
    id              = db.Column(db.Integer, primary_key=True)
    note_number     = db.Column(db.String(30), unique=True, nullable=False, index=True)
    customer_id     = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)
    sale_id         = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=True)
    return_order_id = db.Column(db.Integer, db.ForeignKey('return_orders.id'), nullable=True)
    amount          = db.Column(db.Float, nullable=False, default=0.0)
    reason          = db.Column(db.Text)
    status          = db.Column(db.String(20), default='issued')  # issued | applied | void
    reference_note  = db.Column(db.String(255))
    created_by_id   = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)

    customer     = db.relationship('Customer',    foreign_keys=[customer_id])
    sale         = db.relationship('Sale',        foreign_keys=[sale_id])
    return_order = db.relationship('ReturnOrder', foreign_keys=[return_order_id])
    created_by   = db.relationship('User',        foreign_keys=[created_by_id])

    @property
    def status_badge(self):
        return {'issued': 'bg-info text-dark', 'applied': 'bg-success',
                'void': 'bg-secondary'}.get(self.status, 'bg-secondary')


class DebitNote(db.Model):
    __tablename__ = 'debit_notes'
    id             = db.Column(db.Integer, primary_key=True)
    note_number    = db.Column(db.String(30), unique=True, nullable=False, index=True)
    customer_id    = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)
    sale_id        = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=True)
    amount         = db.Column(db.Float, nullable=False, default=0.0)
    reason         = db.Column(db.Text)
    status         = db.Column(db.String(20), default='issued')  # issued | void
    reference_note = db.Column(db.String(255))
    created_by_id  = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

    customer   = db.relationship('Customer', foreign_keys=[customer_id])
    sale       = db.relationship('Sale',     foreign_keys=[sale_id])
    created_by = db.relationship('User',     foreign_keys=[created_by_id])

    @property
    def status_badge(self):
        return {'issued': 'bg-warning text-dark', 'void': 'bg-secondary'}.get(self.status, 'bg-secondary')
