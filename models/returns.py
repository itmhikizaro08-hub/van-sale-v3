"""
Multi-item Return Orders
========================
See models/notes.py for CreditNote/DebitNote, and models/supplier_return.py
for supplier-side (outbound) returns — this file covers customer-side
(inbound) returns only.
"""
from app import db
from datetime import datetime


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
