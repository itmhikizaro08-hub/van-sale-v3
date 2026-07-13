"""
Pricing Management — Price Change Audit Trail
Tracks every change to a product's Company Selling Price (Product.selling_price)
and Cost Price. Insert-only, never updated or deleted.
"""
from app import db
from datetime import datetime


class PriceHistory(db.Model):
    __tablename__ = 'price_history'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)

    old_company_price = db.Column(db.Float)
    new_company_price = db.Column(db.Float)
    old_cost_price = db.Column(db.Float)
    new_cost_price = db.Column(db.Float)

    reason = db.Column(db.Text)
    changed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    product = db.relationship(
        'Product', foreign_keys=[product_id],
        backref=db.backref('price_history', order_by='PriceHistory.created_at.desc()')
    )
    changed_by = db.relationship('User', foreign_keys=[changed_by_id])

    @property
    def company_price_delta(self):
        if self.old_company_price is None or self.new_company_price is None:
            return None
        return round(self.new_company_price - self.old_company_price, 2)

    def __repr__(self):
        return f'<PriceHistory product={self.product_id} {self.old_company_price}->{self.new_company_price}>'
