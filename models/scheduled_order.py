from app import db
from datetime import datetime, date


class ScheduledOrder(db.Model):
    """A customer's advance order for delivery on a future due_date. Not a
    real financial transaction — the assigned rep converts it into an actual
    Sale when they deliver. sms_sent_at guards the due-date SMS reminder so
    it only ever goes out once per order, no matter how many times the
    due-date check runs."""
    __tablename__ = 'scheduled_orders'

    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(20), unique=True, nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)
    rep_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    due_date = db.Column(db.Date, nullable=False)
    notes = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')  # pending, fulfilled, cancelled
    sms_sent_at = db.Column(db.DateTime)
    fulfilled_sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'))
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    customer = db.relationship('Customer')
    rep = db.relationship('User', foreign_keys=[rep_id])
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    fulfilled_sale = db.relationship('Sale')
    items = db.relationship('ScheduledOrderItem', cascade='all, delete-orphan')

    @property
    def status_badge(self):
        return {'pending': 'bg-warning text-dark', 'fulfilled': 'bg-success',
                'cancelled': 'bg-secondary'}.get(self.status, 'bg-secondary')

    @property
    def is_overdue(self):
        return self.status == 'pending' and self.due_date < date.today()


class ScheduledOrderItem(db.Model):
    __tablename__ = 'scheduled_order_items'

    id = db.Column(db.Integer, primary_key=True)
    scheduled_order_id = db.Column(db.Integer, db.ForeignKey('scheduled_orders.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    # Reference price at scheduling time — informational only, not binding.
    # The real Sale created at fulfillment uses whatever price is current then.
    ref_price = db.Column(db.Float)

    product = db.relationship('Product')
