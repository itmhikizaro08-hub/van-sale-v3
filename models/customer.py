from app import db
from datetime import datetime


class Customer(db.Model):
    __tablename__ = 'customers'

    id = db.Column(db.Integer, primary_key=True)
    customer_code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    name = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    address = db.Column(db.Text)
    location = db.Column(db.String(200))
    gps_latitude = db.Column(db.Float)
    gps_longitude = db.Column(db.Float)
    customer_type = db.Column(db.String(20), default='retail')  # retail, wholesale, distributor
    credit_limit = db.Column(db.Float, default=0.0)
    outstanding_balance = db.Column(db.Float, default=0.0)
    last_purchase_date = db.Column(db.DateTime)
    last_visit_date = db.Column(db.DateTime)
    assigned_route_id = db.Column(db.Integer, db.ForeignKey('routes.id'), nullable=True)
    assigned_van_id = db.Column(db.Integer, db.ForeignKey('vans.id'), nullable=True)
    sales_rep_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    status = db.Column(db.String(20), default='active')  # active, inactive, suspended
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    sales = db.relationship('Sale', foreign_keys='Sale.customer_id', lazy='dynamic')
    visits = db.relationship('CustomerVisit', backref='customer', lazy='dynamic')
    payments = db.relationship('Payment', backref='customer', lazy='dynamic')

    @property
    def status_badge(self):
        badges = {
            'active': 'bg-success',
            'inactive': 'bg-secondary',
            'suspended': 'bg-danger'
        }
        return badges.get(self.status, 'bg-secondary')

    @property
    def type_badge(self):
        badges = {
            'retail': 'bg-info text-dark',
            'wholesale': 'bg-primary',
            'distributor': 'bg-warning text-dark'
        }
        return badges.get(self.customer_type, 'bg-secondary')

    @property
    def credit_available(self):
        return max(0, self.credit_limit - self.outstanding_balance)

    @property
    def credit_utilization_pct(self):
        if self.credit_limit <= 0:
            return 0
        return min(100, round((self.outstanding_balance / self.credit_limit) * 100, 1))

    @property
    def wallet_balance(self):
        return self.wallet.balance if self.wallet else 0.0

    @property
    def lifetime_sales_value(self):
        from models.sale import Sale
        total = self.sales.filter(Sale.status == 'completed').with_entities(
            db.func.sum(Sale.total_amount)).scalar()
        return round(total or 0, 2)

    @property
    def tier(self):
        value = self.lifetime_sales_value
        if value >= 5000: return 'platinum'
        if value >= 2000: return 'gold'
        if value >= 500: return 'silver'
        return 'bronze'

    @property
    def tier_badge(self):
        return {
            'platinum': 'bg-primary',
            'gold': 'bg-warning text-dark',
            'silver': 'bg-info text-dark',
            'bronze': 'bg-secondary'
        }.get(self.tier, 'bg-secondary')

    def to_dict(self):
        return {
            'id': self.id,
            'customer_code': self.customer_code,
            'name': self.name,
            'phone': self.phone,
            'email': self.email,
            'address': self.address,
            'customer_type': self.customer_type,
            'credit_limit': self.credit_limit,
            'outstanding_balance': self.outstanding_balance,
            'status': self.status
        }

    def __repr__(self):
        return f'<Customer {self.customer_code} - {self.name}>'
