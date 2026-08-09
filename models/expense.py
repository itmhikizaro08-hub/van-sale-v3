from app import db
from datetime import datetime


# ── ExpenseCategory ──────────────────────────────────────────────────────────
# Categories used to be a hardcoded Python list (fuel, vehicle_repair, salary,
# office, miscellaneous) baked into routes/expenses.py, which forced every
# expense into a fixed, vehicle-skewed set. Expense.category stays a plain
# string column (not a FK) for backward compatibility with existing rows —
# this table is just the admin-editable menu of allowed values, not a
# referential constraint, so retiring a category never orphans history.
class ExpenseCategory(db.Model):
    __tablename__ = 'expense_categories'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    label = db.Column(db.String(100), nullable=False)
    icon = db.Column(db.String(50), default='fa-receipt')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ── Expense ────────────────────────────────────────────────────────────────────
class Expense(db.Model):
    __tablename__ = 'expenses'

    id = db.Column(db.Integer, primary_key=True)
    expense_number = db.Column(db.String(30), unique=True, nullable=False)
    category = db.Column(db.String(50), nullable=False)  # ExpenseCategory.key, not a FK — see above
    description = db.Column(db.Text)
    amount = db.Column(db.Float, nullable=False)
    van_id = db.Column(db.Integer, db.ForeignKey('vans.id'), nullable=True)
    expense_date = db.Column(db.DateTime, default=datetime.utcnow)
    approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected, void
    receipt_image = db.Column(db.String(255))
    reference_note = db.Column(db.String(255))  # cross-check with physical books
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    van = db.relationship('Van', foreign_keys=[van_id])
    approved_by = db.relationship('User', foreign_keys=[approved_by_id])
    created_by = db.relationship('User', foreign_keys=[created_by_id])

    @property
    def category_icon(self):
        """Fallback icon for the original 5 hardcoded categories (rows that
        predate ExpenseCategory). Callers that already loaded the category
        table should prefer that lookup so custom categories get their own
        icon instead of always falling back to fa-receipt here."""
        icons = {
            'fuel': 'fa-gas-pump', 'vehicle_repair': 'fa-wrench',
            'salary': 'fa-users', 'office': 'fa-building', 'miscellaneous': 'fa-receipt'
        }
        return icons.get(self.category, 'fa-receipt')

    @property
    def status_badge(self):
        return {'pending': 'bg-warning text-dark', 'approved': 'bg-success',
                'rejected': 'bg-danger', 'void': 'bg-secondary'}.get(self.status, 'bg-secondary')
