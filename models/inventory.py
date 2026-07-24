"""
Inventory — Stock Movement Ledger & Van Custody
=================================================
InventoryMovement is the append-only log of every stock change (stock_in,
stock_out, transfer_in/out, adjustment, damaged, expired, sale, return).
VanStock is the current-state ledger of what each rep's van actually holds
right now — read/written far beyond any one feature (sales deduction,
returns restocking, loading/offload, inventory/dashboard/report reads), so
it lives here alongside the movement log rather than under any single
feature's own file.
"""
from app import db
from datetime import datetime


# ── Inventory Movement ─────────────────────────────────────────────────────────
class InventoryMovement(db.Model):
    __tablename__ = 'inventory_movements'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    movement_type = db.Column(db.String(30), nullable=False)
    # stock_in, stock_out, transfer_in, transfer_out, adjustment, damaged, expired, sale, return
    # Float, not Integer — a 'sale' movement can now record a fractional
    # quantity when items are sold by the piece (Product.pieces_per_unit).
    quantity = db.Column(db.Float, nullable=False)
    quantity_before = db.Column(db.Float, default=0)
    quantity_after = db.Column(db.Float, default=0)
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
    # Float, not Integer — a rep's van can end up with a fractional amount of
    # a multi-piece unit once some pieces have been sold off it.
    quantity     = db.Column(db.Float, default=0)
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

    @property
    def is_low_stock(self):
        """Matches Product.is_low_stock's threshold (reorder_level) rather
        than a hardcoded number — a van holding 8 units of a product whose
        reorder_level is 20 is just as much a restocking risk as one
        holding 8 units of something whose threshold is 5."""
        return self.product is not None and self.quantity <= self.product.reorder_level
