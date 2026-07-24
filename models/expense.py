from app import db
from datetime import datetime


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
