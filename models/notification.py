from app import db
from datetime import datetime


# ── Inventory Movement ─────────────────────────────────────────────────────────
class InventoryMovement(db.Model):
    __tablename__ = 'inventory_movements'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    movement_type = db.Column(db.String(30), nullable=False)
    # stock_in, stock_out, transfer_in, transfer_out, adjustment, damaged, expired, sale, return
    quantity = db.Column(db.Integer, nullable=False)
    quantity_before = db.Column(db.Integer, default=0)
    quantity_after = db.Column(db.Integer, default=0)
    van_id = db.Column(db.Integer, db.ForeignKey('vans.id'), nullable=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=True)
    reference_id = db.Column(db.Integer)  # sale_id, return_id, etc.
    reference_type = db.Column(db.String(30))
    reference_note = db.Column(db.String(255))  # cross-check with physical books
    notes = db.Column(db.Text)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    created_by = db.relationship('User', foreign_keys=[created_by_id])
    supplier = db.relationship('Supplier', foreign_keys=[supplier_id])
    product = db.relationship('Product', foreign_keys=[product_id])

    @property
    def type_badge(self):
        badges = {
            'stock_in': 'bg-success', 'transfer_in': 'bg-info text-dark',
            'return': 'bg-warning text-dark', 'stock_out': 'bg-danger',
            'transfer_out': 'bg-secondary', 'sale': 'bg-primary',
            'adjustment': 'bg-light text-dark', 'damaged': 'bg-danger',
            'expired': 'bg-dark'
        }
        return badges.get(self.movement_type, 'bg-secondary')

    def __repr__(self):
        return f'<InventoryMovement {self.movement_type} qty={self.quantity}>'


# ── Van Stock ──────────────────────────────────────────────────────────────────
class VanStock(db.Model):
    """Stock in a sales rep's van custody.
    sales_rep_id tracks which rep is responsible (Sprint B).
    """
    __tablename__ = 'van_stocks'

    id           = db.Column(db.Integer, primary_key=True)
    van_id       = db.Column(db.Integer, db.ForeignKey('vans.id'),     nullable=False)
    sales_rep_id = db.Column(db.Integer, db.ForeignKey('users.id'),    nullable=True)
    product_id   = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity     = db.Column(db.Integer, default=0)
    updated_at   = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    van       = db.relationship('Van',     foreign_keys=[van_id])
    sales_rep = db.relationship('User',    foreign_keys=[sales_rep_id])
    product   = db.relationship('Product', foreign_keys=[product_id])

    __table_args__ = (
        db.UniqueConstraint('van_id', 'sales_rep_id', 'product_id', name='uq_van_rep_product'),
    )

    @property
    def stock_value(self):
        return round(self.quantity * (self.product.cost_price if self.product else 0), 2)


# ── Return ─────────────────────────────────────────────────────────────────────
class Return(db.Model):
    __tablename__ = 'returns'

    id = db.Column(db.Integer, primary_key=True)
    return_number = db.Column(db.String(30), unique=True, nullable=False)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(200))
    return_type = db.Column(db.String(30), default='sales_return')
    # sales_return, damaged, expired
    refund_amount = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected
    approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    notes = db.Column(db.Text)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    customer = db.relationship('Customer', foreign_keys=[customer_id])
    product = db.relationship('Product', foreign_keys=[product_id])
    approved_by = db.relationship('User', foreign_keys=[approved_by_id])
    created_by = db.relationship('User', foreign_keys=[created_by_id])

    @property
    def status_badge(self):
        return {'pending': 'bg-warning text-dark', 'approved': 'bg-success', 'rejected': 'bg-danger'}.get(self.status, 'bg-secondary')


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


# ── Expense ────────────────────────────────────────────────────────────────────
class Expense(db.Model):
    __tablename__ = 'expenses'

    id = db.Column(db.Integer, primary_key=True)
    expense_number = db.Column(db.String(30), unique=True, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    # fuel, vehicle_repair, salary, office, miscellaneous
    description = db.Column(db.Text)
    amount = db.Column(db.Float, nullable=False)
    van_id = db.Column(db.Integer, db.ForeignKey('vans.id'), nullable=True)
    expense_date = db.Column(db.DateTime, default=datetime.utcnow)
    approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected
    receipt_image = db.Column(db.String(255))
    reference_note = db.Column(db.String(255))  # cross-check with physical books
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    van = db.relationship('Van', foreign_keys=[van_id])
    approved_by = db.relationship('User', foreign_keys=[approved_by_id])
    created_by = db.relationship('User', foreign_keys=[created_by_id])

    @property
    def category_icon(self):
        icons = {
            'fuel': 'fa-gas-pump', 'vehicle_repair': 'fa-wrench',
            'salary': 'fa-users', 'office': 'fa-building', 'miscellaneous': 'fa-receipt'
        }
        return icons.get(self.category, 'fa-receipt')

    @property
    def status_badge(self):
        return {'pending': 'bg-warning text-dark', 'approved': 'bg-success', 'rejected': 'bg-danger'}.get(self.status, 'bg-secondary')


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
