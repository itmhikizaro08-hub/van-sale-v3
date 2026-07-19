"""
Supplier Returns — goods sent back to a supplier (damaged, expired, wrong
item, or quality issue). Mirrors ReturnOrder/ReturnOrderItem in
models/v4_models.py, but runs in the opposite direction: approving a line
here DECREASES warehouse stock (goods are leaving) and DECREASES what we
owe the supplier (we get credit for what we're returning), instead of
increasing them the way a customer return does.
"""
from app import db
from datetime import datetime

REASONS = ['damaged', 'expired', 'wrong_item', 'quality_issue', 'other']


class SupplierReturn(db.Model):
    __tablename__ = 'supplier_returns'
    id              = db.Column(db.Integer, primary_key=True)
    return_number   = db.Column(db.String(30), unique=True, nullable=False, index=True)
    supplier_id     = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=False)
    status          = db.Column(db.String(20), default='pending')  # pending | approved | partial | rejected
    total_value     = db.Column(db.Float, default=0.0)
    notes           = db.Column(db.Text)
    reference_note  = db.Column(db.String(255))
    approved_by_id  = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    approved_at     = db.Column(db.DateTime, nullable=True)
    created_by_id   = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)

    supplier     = db.relationship('Supplier', foreign_keys=[supplier_id])
    approved_by  = db.relationship('User',     foreign_keys=[approved_by_id])
    created_by   = db.relationship('User',     foreign_keys=[created_by_id])
    items        = db.relationship('SupplierReturnItem', backref='supplier_return',
                                    lazy='joined', cascade='all, delete-orphan')

    @property
    def status_badge(self):
        return {'pending': 'bg-warning text-dark', 'approved': 'bg-success',
                'partial': 'bg-info text-dark', 'rejected': 'bg-danger'}.get(self.status, 'bg-secondary')

    @property
    def total_quantity(self):
        return sum(i.quantity for i in self.items)

    def recalculate(self):
        self.total_value = round(sum(i.line_total for i in self.items), 2)


class SupplierReturnItem(db.Model):
    __tablename__ = 'supplier_return_items'
    id                  = db.Column(db.Integer, primary_key=True)
    supplier_return_id  = db.Column(db.Integer, db.ForeignKey('supplier_returns.id'), nullable=False)
    product_id          = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity            = db.Column(db.Float, nullable=False, default=1)
    unit_cost           = db.Column(db.Float, nullable=False, default=0.0)
    line_total          = db.Column(db.Float, default=0.0)
    reason              = db.Column(db.String(30), default='other')
    line_status         = db.Column(db.String(20), default='pending')  # pending | approved | rejected

    product = db.relationship('Product', foreign_keys=[product_id])

    @property
    def reason_badge(self):
        return {'damaged': 'bg-danger', 'expired': 'bg-dark', 'wrong_item': 'bg-warning text-dark',
                'quality_issue': 'bg-danger', 'other': 'bg-secondary'}.get(self.reason, 'bg-secondary')

    @property
    def line_status_badge(self):
        return {'pending': 'bg-warning text-dark', 'approved': 'bg-success',
                'rejected': 'bg-danger'}.get(self.line_status, 'bg-secondary')

    def calculate_total(self):
        self.line_total = round(self.unit_cost * self.quantity, 2)
