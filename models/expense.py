from app import db
from datetime import datetime

PAYMENT_METHODS = [
    ('cash', 'Cash'),
    ('mobile_money', 'Mobile Money'),
    ('bank_transfer', 'Bank Transfer'),
    ('cheque', 'Cheque'),
]


# ── ExpenseCategory ──────────────────────────────────────────────────────────
# Categories used to be a hardcoded Python list baked into routes/expenses.py,
# which forced every expense into a fixed set. Expense.category stays a plain
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
    payment_method = db.Column(db.String(20), default='cash')  # cash | mobile_money | bank_transfer | cheque
    expense_date = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected, void
    receipt_image = db.Column(db.String(255))
    reference_note = db.Column(db.String(255))  # free-form notes (cross-check with physical books, context, etc.)

    approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    approval_note = db.Column(db.Text)      # optional note left when approving
    rejection_reason = db.Column(db.Text)   # required when rejecting

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    updated_at = db.Column(db.DateTime, nullable=True)

    approved_by = db.relationship('User', foreign_keys=[approved_by_id])
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    updated_by = db.relationship('User', foreign_keys=[updated_by_id])
    audit_logs = db.relationship('ExpenseAuditLog', backref='expense', order_by='ExpenseAuditLog.created_at',
                                  cascade='all, delete-orphan')

    @property
    def category_icon(self):
        """Fallback icon for the original hardcoded categories (rows that
        predate ExpenseCategory). Callers that already loaded the category
        table should prefer that lookup so custom categories get their own
        icon instead of always falling back to fa-receipt here."""
        icons = {
            'fuel': 'fa-gas-pump', 'vehicle_repair': 'fa-wrench', 'vehicle_maintenance': 'fa-oil-can',
            'salary': 'fa-users', 'office': 'fa-building', 'transport': 'fa-truck',
            'food': 'fa-utensils', 'miscellaneous': 'fa-receipt'
        }
        return icons.get(self.category, 'fa-receipt')

    @property
    def status_badge(self):
        return {'pending': 'bg-warning text-dark', 'approved': 'bg-success',
                'rejected': 'bg-danger', 'void': 'bg-secondary'}.get(self.status, 'bg-secondary')

    @property
    def payment_method_label(self):
        return dict(PAYMENT_METHODS).get(self.payment_method, (self.payment_method or '').replace('_', ' ').title())

    @property
    def receipt_is_pdf(self):
        return bool(self.receipt_image) and self.receipt_image.lower().endswith('.pdf')


# ── ExpenseAuditLog ───────────────────────────────────────────────────────────
# One row per state-changing action on an expense (create/edit/approve/
# reject/void), so "who did what, when" is fully reconstructable without
# relying on mutable columns like approved_by_id alone (which get
# overwritten and can't show a prior approver if an expense is reopened).
class ExpenseAuditLog(db.Model):
    __tablename__ = 'expense_audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    expense_id = db.Column(db.Integer, db.ForeignKey('expenses.id'), nullable=False)
    action = db.Column(db.String(20), nullable=False)  # created | edited | approved | rejected | voided
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    actor = db.relationship('User', foreign_keys=[actor_id])

    @property
    def action_label(self):
        return {'created': 'Created', 'edited': 'Edited', 'approved': 'Approved',
                'rejected': 'Rejected', 'voided': 'Voided'}.get(self.action, self.action.title())

    @property
    def action_icon(self):
        return {'created': 'fa-plus', 'edited': 'fa-pen', 'approved': 'fa-check-circle',
                'rejected': 'fa-times-circle', 'voided': 'fa-ban'}.get(self.action, 'fa-circle')

    @property
    def action_color(self):
        return {'created': 'primary', 'edited': 'info', 'approved': 'success',
                'rejected': 'danger', 'voided': 'secondary'}.get(self.action, 'secondary')
