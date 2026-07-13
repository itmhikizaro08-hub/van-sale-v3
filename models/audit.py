"""
Pricing Audit Trail
====================
One row per invoice line at the moment it's sold, capturing exactly what the
company price was, what the rep actually charged, and the resulting tip.
Immutable — never edited after creation, even if the underlying sale/tip is
later adjusted (tip edits get their own audit row, so history stays intact).
"""
from app import db
from datetime import datetime


class PricingAuditLog(db.Model):
    __tablename__ = 'pricing_audit_logs'

    id                     = db.Column(db.Integer, primary_key=True)
    user_id                = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    sale_id                = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=True)
    invoice_number         = db.Column(db.String(30), nullable=False, index=True)
    product_id             = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    company_selling_price  = db.Column(db.Float, nullable=False)
    selling_price_entered  = db.Column(db.Float, nullable=False)
    tip_calculated         = db.Column(db.Float, nullable=False, default=0.0)
    quantity                = db.Column(db.Integer, nullable=False)
    total_amount            = db.Column(db.Float, nullable=False)
    action                   = db.Column(db.String(20), default='sale')  # sale, tip_edit, tip_delete
    created_at               = db.Column(db.DateTime, default=datetime.utcnow)

    user    = db.relationship('User', foreign_keys=[user_id])
    sale    = db.relationship('Sale', foreign_keys=[sale_id])
    product = db.relationship('Product', foreign_keys=[product_id])

    def __repr__(self):
        return f'<PricingAuditLog {self.invoice_number} tip={self.tip_calculated}>'
