"""
Van Management — Loading Sheets & Stock Offload
=================================================
Loading (warehouse → van): a warehouse manager/admin issues a LoadingSheet,
moving product from warehouse Product.stock_quantity into a rep's VanStock
custody. See routes/vans.py `loading_new()`.

Offload (van → warehouse): a rep declares stock they're returning; nothing
changes until a warehouse manager/admin confirms with an actual counted
quantity. Only the received quantity moves back from VanStock into warehouse
stock — any shortfall stays on the rep's books as their stock liability (see
reports.rep_liability, which reads VanStock directly). See routes/vans.py
`offload_submit()` / `offload_confirm()`.

VanStock itself (the actual custody ledger both of these mutate) lives in
models/notification.py — it's shared far beyond these two features (sales
deduction, returns restocking, inventory/dashboard/report reads), so it isn't
moved here.
"""
from app import db
from datetime import datetime


# ── Loading Sheets ──────────────────────────────────────────────────────────
class LoadingSheet(db.Model):
    __tablename__ = 'loading_sheets'
    id             = db.Column(db.Integer, primary_key=True)
    sheet_number   = db.Column(db.String(30), unique=True, nullable=False, index=True)
    van_id         = db.Column(db.Integer, db.ForeignKey('vans.id'), nullable=False)
    sales_rep_id   = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    loading_date   = db.Column(db.Date, default=datetime.utcnow().date)
    status         = db.Column(db.String(20), default='issued')  # issued, acknowledged, returned
    notes          = db.Column(db.Text)
    reference_note = db.Column(db.String(255))
    issued_by_id   = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

    van        = db.relationship('Van',  foreign_keys=[van_id])
    sales_rep  = db.relationship('User', foreign_keys=[sales_rep_id])
    issued_by  = db.relationship('User', foreign_keys=[issued_by_id])
    items      = db.relationship('LoadingSheetItem', backref='sheet', lazy='joined',
                                  cascade='all, delete-orphan')

    @property
    def status_badge(self):
        return {'issued': 'bg-info text-dark', 'acknowledged': 'bg-success',
                'returned': 'bg-secondary'}.get(self.status, 'bg-secondary')

    @property
    def total_value(self):
        return round(sum(
            item.quantity * (item.product.cost_price if item.product else 0)
            for item in self.items
        ), 2)


class LoadingSheetItem(db.Model):
    __tablename__ = 'loading_sheet_items'
    id         = db.Column(db.Integer, primary_key=True)
    sheet_id   = db.Column(db.Integer, db.ForeignKey('loading_sheets.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity   = db.Column(db.Integer, nullable=False, default=0)
    product    = db.relationship('Product', foreign_keys=[product_id])


# ── Stock Offload ────────────────────────────────────────────────────────────
class StockOffload(db.Model):
    __tablename__ = 'stock_offloads'

    id = db.Column(db.Integer, primary_key=True)
    offload_number = db.Column(db.String(30), unique=True, nullable=False, index=True)
    sales_rep_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    van_id = db.Column(db.Integer, db.ForeignKey('vans.id'), nullable=True)
    status = db.Column(db.String(20), default='pending')  # pending, confirmed, discrepancy
    notes = db.Column(db.Text)
    confirmed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    confirmed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sales_rep = db.relationship('User', foreign_keys=[sales_rep_id])
    van = db.relationship('Van', foreign_keys=[van_id])
    confirmed_by = db.relationship('User', foreign_keys=[confirmed_by_id])
    items = db.relationship('StockOffloadItem', backref='offload',
                             lazy='joined', cascade='all, delete-orphan')

    @property
    def status_badge(self):
        return {'pending': 'bg-warning text-dark', 'confirmed': 'bg-success',
                'discrepancy': 'bg-danger'}.get(self.status, 'bg-secondary')

    @property
    def total_declared_qty(self):
        return sum(i.quantity_declared for i in self.items)

    def __repr__(self):
        return f'<StockOffload {self.offload_number}>'


class StockOffloadItem(db.Model):
    __tablename__ = 'stock_offload_items'

    id = db.Column(db.Integer, primary_key=True)
    offload_id = db.Column(db.Integer, db.ForeignKey('stock_offloads.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    # Float, not Integer — a rep can now hold a fractional amount of van
    # stock after selling by the piece, and must be able to offload exactly
    # that amount back to the warehouse rather than being stuck rounding down.
    quantity_declared = db.Column(db.Float, nullable=False, default=0)
    quantity_received = db.Column(db.Float, nullable=True)

    product = db.relationship('Product', foreign_keys=[product_id])
