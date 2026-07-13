from app import db
from datetime import datetime


class Van(db.Model):
    __tablename__ = 'vans'

    id = db.Column(db.Integer, primary_key=True)
    van_number = db.Column(db.String(20), unique=True, nullable=False)
    registration_number = db.Column(db.String(30), unique=True)
    make = db.Column(db.String(50))
    model = db.Column(db.String(50))
    year = db.Column(db.Integer)
    driver_id = db.Column(db.Integer, db.ForeignKey('drivers.id'), nullable=True)
    route_id = db.Column(db.Integer, db.ForeignKey('routes.id'), nullable=True)
    status = db.Column(db.String(20), default='active')  # active, inactive, maintenance
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    driver = db.relationship('Driver', backref='van', uselist=False)
    sales = db.relationship('Sale', backref='van_obj', lazy='dynamic')

    @property
    def status_badge(self):
        return {'active': 'bg-success', 'inactive': 'bg-secondary', 'maintenance': 'bg-warning text-dark'}.get(self.status, 'bg-secondary')

    def __repr__(self):
        return f'<Van {self.van_number}>'


class Driver(db.Model):
    __tablename__ = 'drivers'

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.String(20), unique=True)
    name = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    license_number = db.Column(db.String(50))
    license_expiry = db.Column(db.Date)
    license_class = db.Column(db.String(10))
    address = db.Column(db.Text)
    status = db.Column(db.String(20), default='active')  # active, inactive, suspended
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def license_expiry_soon(self):
        if self.license_expiry:
            from datetime import date, timedelta
            return self.license_expiry <= (date.today() + timedelta(days=30))
        return False

    @property
    def license_expired(self):
        if self.license_expiry:
            from datetime import date
            return self.license_expiry < date.today()
        return False

    @property
    def status_badge(self):
        return {'active': 'bg-success', 'inactive': 'bg-secondary', 'suspended': 'bg-danger'}.get(self.status, 'bg-secondary')

    def __repr__(self):
        return f'<Driver {self.name}>'


class Route(db.Model):
    __tablename__ = 'routes'

    id = db.Column(db.Integer, primary_key=True)
    route_code = db.Column(db.String(20), unique=True, nullable=False)
    route_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    area = db.Column(db.String(100))
    status = db.Column(db.String(20), default='active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    customers = db.relationship('Customer', backref='route', lazy='dynamic')
    visits = db.relationship('CustomerVisit', backref='route', lazy='dynamic')
    vans = db.relationship('Van', backref='route', lazy='dynamic')

    def __repr__(self):
        return f'<Route {self.route_code} - {self.route_name}>'


class CustomerVisit(db.Model):
    __tablename__ = 'customer_visits'

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)
    route_id = db.Column(db.Integer, db.ForeignKey('routes.id'), nullable=True)
    sales_rep_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    visit_date = db.Column(db.DateTime, default=datetime.utcnow)
    check_in_time = db.Column(db.DateTime)
    check_out_time = db.Column(db.DateTime)
    gps_latitude = db.Column(db.Float)
    gps_longitude = db.Column(db.Float)
    status = db.Column(db.String(20), default='planned')  # planned, completed, missed
    outcome = db.Column(db.String(50))  # sale_made, no_sale, not_home, refused
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sales_rep = db.relationship('User', foreign_keys=[sales_rep_id])

    @property
    def duration_minutes(self):
        if self.check_in_time and self.check_out_time:
            diff = self.check_out_time - self.check_in_time
            return int(diff.total_seconds() / 60)
        return None

    @property
    def status_badge(self):
        return {
            'planned': 'bg-info text-dark',
            'completed': 'bg-success',
            'missed': 'bg-danger'
        }.get(self.status, 'bg-secondary')

    def __repr__(self):
        return f'<Visit customer={self.customer_id} date={self.visit_date}>'
