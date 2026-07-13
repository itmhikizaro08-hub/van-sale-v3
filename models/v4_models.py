"""
Van Sales V4 — Sprint 1 Models
ReturnOrder, CreditNote, DebitNote,
PaymentAllocation, CustomerWallet, WalletTransaction, PaymentReversal

(LoadingSheet/LoadingSheetItem moved to models/van_management.py)
"""
from app import db
from datetime import datetime


# ── Multi-item Return Orders ──────────────────────────────────────────────────
class ReturnOrder(db.Model):
    __tablename__ = 'return_orders'
    id                  = db.Column(db.Integer, primary_key=True)
    return_number       = db.Column(db.String(30), unique=True, nullable=False, index=True)
    sale_id             = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=True)
    customer_id         = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)
    received_by_rep_id  = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    van_id              = db.Column(db.Integer, db.ForeignKey('vans.id'), nullable=True)
    return_destination  = db.Column(db.String(20), default='warehouse')  # warehouse | van_stock | scrap
    status              = db.Column(db.String(20), default='pending')    # pending | approved | partial | rejected
    refund_method       = db.Column(db.String(20), default='credit')     # credit | cash
    total_refund_amount = db.Column(db.Float, default=0.0)
    notes               = db.Column(db.Text)
    reference_note      = db.Column(db.String(255))
    approved_by_id      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    approved_at         = db.Column(db.DateTime, nullable=True)
    created_by_id       = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at          = db.Column(db.DateTime, default=datetime.utcnow)

    customer          = db.relationship('Customer', foreign_keys=[customer_id])
    sale              = db.relationship('Sale',     foreign_keys=[sale_id])
    received_by_rep   = db.relationship('User',    foreign_keys=[received_by_rep_id])
    van               = db.relationship('Van',     foreign_keys=[van_id])
    approved_by       = db.relationship('User',    foreign_keys=[approved_by_id])
    created_by        = db.relationship('User',    foreign_keys=[created_by_id])
    items             = db.relationship('ReturnOrderItem', backref='return_order',
                                         lazy='joined', cascade='all, delete-orphan')

    @property
    def status_badge(self):
        return {'pending': 'bg-warning text-dark', 'approved': 'bg-success',
                'partial': 'bg-info text-dark', 'rejected': 'bg-danger'}.get(self.status, 'bg-secondary')

    @property
    def destination_badge(self):
        return {'van_stock': 'bg-primary', 'warehouse': 'bg-info text-dark',
                'scrap': 'bg-danger'}.get(self.return_destination, 'bg-secondary')

    @property
    def total_quantity(self):
        return sum(i.quantity for i in self.items)

    def recalculate(self):
        self.total_refund_amount = round(sum(i.line_total for i in self.items), 2)


class ReturnOrderItem(db.Model):
    __tablename__ = 'return_order_items'
    id              = db.Column(db.Integer, primary_key=True)
    return_order_id = db.Column(db.Integer, db.ForeignKey('return_orders.id'), nullable=False)
    product_id      = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    sale_item_id    = db.Column(db.Integer, db.ForeignKey('sale_items.id'), nullable=True)
    quantity        = db.Column(db.Integer, nullable=False, default=1)
    unit_price      = db.Column(db.Float, nullable=False, default=0.0)
    line_total      = db.Column(db.Float, default=0.0)
    reason          = db.Column(db.String(30), default='sales_return')
    line_status     = db.Column(db.String(20), default='pending')  # pending | approved | rejected

    product   = db.relationship('Product',  foreign_keys=[product_id])
    sale_item = db.relationship('SaleItem', foreign_keys=[sale_item_id])

    @property
    def reason_badge(self):
        return {'sales_return': 'bg-info text-dark', 'damaged': 'bg-danger',
                'expired': 'bg-dark', 'wrong_item': 'bg-warning text-dark'}.get(self.reason, 'bg-secondary')

    @property
    def line_status_badge(self):
        return {'pending': 'bg-warning text-dark', 'approved': 'bg-success',
                'rejected': 'bg-danger'}.get(self.line_status, 'bg-secondary')

    def calculate_total(self):
        self.line_total = round(self.unit_price * self.quantity, 2)


# ── Credit / Debit Notes ──────────────────────────────────────────────────────
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


# ── Payment Allocation / Customer Wallet ──────────────────────────────────────
class PaymentAllocation(db.Model):
    __tablename__ = 'payment_allocations'
    id         = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('payments.id'), nullable=False)
    sale_id    = db.Column(db.Integer, db.ForeignKey('sales.id'),    nullable=False)
    amount     = db.Column(db.Float, nullable=False, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    payment = db.relationship('Payment', foreign_keys=[payment_id], backref='allocations')
    sale    = db.relationship('Sale',    foreign_keys=[sale_id])


class CustomerWallet(db.Model):
    __tablename__ = 'customer_wallets'
    id          = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), unique=True, nullable=False)
    balance     = db.Column(db.Float, default=0.0)
    updated_at  = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer = db.relationship('Customer', foreign_keys=[customer_id],
                                backref=db.backref('wallet', uselist=False))


class WalletTransaction(db.Model):
    __tablename__ = 'wallet_transactions'
    id               = db.Column(db.Integer, primary_key=True)
    wallet_id        = db.Column(db.Integer, db.ForeignKey('customer_wallets.id'), nullable=False)
    transaction_type = db.Column(db.String(20), nullable=False)  # credit | debit
    amount           = db.Column(db.Float, nullable=False)
    source_type      = db.Column(db.String(30))
    source_id        = db.Column(db.Integer)
    notes            = db.Column(db.Text)
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)

    wallet = db.relationship('CustomerWallet', foreign_keys=[wallet_id], backref='transactions')


class PaymentReversal(db.Model):
    __tablename__ = 'payment_reversals'
    id             = db.Column(db.Integer, primary_key=True)
    payment_id     = db.Column(db.Integer, db.ForeignKey('payments.id'), nullable=False)
    reason         = db.Column(db.Text, nullable=False)
    reversed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    status         = db.Column(db.String(20), default='pending')  # pending | approved | rejected
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

    payment     = db.relationship('Payment', foreign_keys=[payment_id], backref='reversal')
    reversed_by = db.relationship('User',    foreign_keys=[reversed_by_id])
    approved_by = db.relationship('User',    foreign_keys=[approved_by_id])

    @property
    def status_badge(self):
        return {'pending': 'bg-warning text-dark', 'approved': 'bg-danger',
                'rejected': 'bg-secondary'}.get(self.status, 'bg-secondary')
