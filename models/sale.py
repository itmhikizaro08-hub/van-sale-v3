from app import db
from datetime import datetime


class Sale(db.Model):
    __tablename__ = "sales"

    id               = db.Column(db.Integer, primary_key=True)
    invoice_number   = db.Column(db.String(30), unique=True, nullable=False, index=True)
    customer_id      = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False)
    van_id           = db.Column(db.Integer, db.ForeignKey("vans.id"), nullable=True)
    sales_rep_id     = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    sale_date        = db.Column(db.DateTime, default=datetime.utcnow)
    due_date         = db.Column(db.DateTime)
    subtotal         = db.Column(db.Float, default=0.0)
    discount_amount  = db.Column(db.Float, default=0.0)
    discount_percent = db.Column(db.Float, default=0.0)
    tax_amount       = db.Column(db.Float, default=0.0)
    tax_percent      = db.Column(db.Float, default=0.0)
    total_amount     = db.Column(db.Float, default=0.0)
    company_sales_total = db.Column(db.Float, default=0.0)
    total_tips_amount   = db.Column(db.Float, default=0.0)
    amount_paid      = db.Column(db.Float, default=0.0)
    balance_due      = db.Column(db.Float, default=0.0)
    payment_method   = db.Column(db.String(30), default="cash")
    status           = db.Column(db.String(20), default="draft")
    payment_status   = db.Column(db.String(20), default="unpaid")
    notes            = db.Column(db.Text)
    reference_note   = db.Column(db.String(255))
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at       = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    items     = db.relationship("SaleItem", backref="sale", lazy="joined", cascade="all, delete-orphan")
    payments  = db.relationship("Payment",  backref="sale", lazy="dynamic")
    sales_rep = db.relationship("User",     foreign_keys=[sales_rep_id])
    van       = db.relationship("Van",      foreign_keys=[van_id])
    customer  = db.relationship("Customer", foreign_keys=[customer_id])

    @property
    def status_badge(self):
        return {"draft": "bg-secondary", "completed": "bg-success",
                "cancelled": "bg-danger"}.get(self.status, "bg-secondary")

    @property
    def payment_badge(self):
        return {"unpaid": "bg-danger", "partial": "bg-warning text-dark",
                "paid": "bg-success"}.get(self.payment_status, "bg-secondary")

    @property
    def total_tips(self):
        return round(sum((i.tip_amount or 0) * i.quantity for i in self.items), 2)

    @property
    def has_tips(self):
        return any((i.tip_amount or 0) > 0 for i in self.items)

    def recalculate(self):
        self.subtotal = round(sum(item.line_total for item in self.items), 2)
        self.company_sales_total = round(sum((item.official_price or 0) * item.quantity for item in self.items), 2)
        self.total_tips_amount = round(sum((item.tip_amount or 0) * item.quantity for item in self.items), 2)
        disc = self.subtotal * (self.discount_percent / 100) if self.discount_percent else self.discount_amount
        self.discount_amount = round(disc, 2)
        taxable = self.subtotal - self.discount_amount
        self.tax_amount = round(taxable * (self.tax_percent / 100), 2)
        self.total_amount = round(taxable + self.tax_amount, 2)
        self.balance_due = round(self.total_amount - self.amount_paid, 2)
        if self.balance_due <= 0: self.payment_status = "paid"
        elif self.amount_paid > 0: self.payment_status = "partial"
        else: self.payment_status = "unpaid"

    def to_dict(self):
        return {"id": self.id, "invoice_number": self.invoice_number,
                "total_amount": self.total_amount, "balance_due": self.balance_due,
                "payment_status": self.payment_status, "status": self.status}


class SaleItem(db.Model):
    __tablename__ = "sale_items"

    id               = db.Column(db.Integer, primary_key=True)
    sale_id          = db.Column(db.Integer, db.ForeignKey("sales.id"),    nullable=False)
    product_id       = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    # Float, not Integer — selling by the piece (see Product.pieces_per_unit)
    # records a fractional number of the stocked unit, e.g. 0.25 of a
    # 12-piece carton when only 3 pieces were sold.
    quantity         = db.Column(db.Float, nullable=False, default=1)
    official_price   = db.Column(db.Float, nullable=False, default=0.0)
    tip_amount       = db.Column(db.Float, nullable=False, default=0.0)
    unit_price       = db.Column(db.Float, nullable=False, default=0.0)
    discount_percent = db.Column(db.Float, default=0.0)
    line_total       = db.Column(db.Float, default=0.0)

    product = db.relationship("Product", foreign_keys=[product_id])

    @property
    def tip_line_total(self):
        return round((self.tip_amount or 0) * self.quantity, 2)

    def calculate_total(self):
        disc = self.unit_price * (self.discount_percent / 100)
        self.line_total = round((self.unit_price - disc) * self.quantity, 2)
