from app import db
from datetime import datetime


class Category(db.Model):
    __tablename__ = 'categories'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    products = db.relationship('Product', backref='category_obj', lazy='dynamic')

    def __repr__(self):
        return f'<Category {self.name}>'


class Product(db.Model):
    __tablename__ = 'products'

    id = db.Column(db.Integer, primary_key=True)
    product_code = db.Column(db.String(30), unique=True, nullable=False, index=True)
    product_name = db.Column(db.String(200), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'))
    brand = db.Column(db.String(100))
    description = db.Column(db.Text)
    barcode = db.Column(db.String(50), unique=True)
    unit = db.Column(db.String(20), default='pcs')  # pcs, box, carton, kg, litre
    # How many individual pieces make up one stocked `unit` (e.g. 12 for a
    # carton of 12 sachets). Default 1 means the unit itself is the smallest
    # sellable piece — no behavior change for products that don't need this.
    pieces_per_unit = db.Column(db.Integer, default=1)
    cost_price = db.Column(db.Float, default=0.0)
    selling_price = db.Column(db.Float, default=0.0)
    wholesale_price = db.Column(db.Float, default=0.0)
    reorder_level = db.Column(db.Integer, default=10)
    # Float, not Integer — selling a few pieces out of a multi-piece unit
    # leaves a fractional amount of that unit in stock (e.g. 8.75 cartons).
    stock_quantity = db.Column(db.Float, default=0)
    image = db.Column(db.String(255))
    status = db.Column(db.String(20), default='active')  # active, inactive, discontinued
    tax_rate = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    sale_items = db.relationship('SaleItem', foreign_keys='SaleItem.product_id', lazy='dynamic')
    inventory_movements = db.relationship('InventoryMovement', foreign_keys='InventoryMovement.product_id', lazy='dynamic')

    @property
    def is_low_stock(self):
        return self.stock_quantity <= self.reorder_level

    @property
    def profit_margin(self):
        if self.cost_price > 0:
            return round(((self.selling_price - self.cost_price) / self.cost_price) * 100, 2)
        return 0

    @property
    def last_price_change(self):
        return self.price_history[0] if self.price_history else None

    @property
    def status_badge(self):
        badges = {
            'active': 'bg-success',
            'inactive': 'bg-secondary',
            'discontinued': 'bg-danger'
        }
        return badges.get(self.status, 'bg-secondary')

    @property
    def stock_badge(self):
        if self.stock_quantity == 0:
            return 'bg-danger'
        elif self.is_low_stock:
            return 'bg-warning text-dark'
        return 'bg-success'

    def to_dict(self):
        return {
            'id': self.id,
            'product_code': self.product_code,
            'product_name': self.product_name,
            'brand': self.brand,
            'cost_price': self.cost_price,
            'selling_price': self.selling_price,
            'stock_quantity': self.stock_quantity,
            'unit': self.unit,
            'pieces_per_unit': self.pieces_per_unit or 1,
            'status': self.status,
            'is_low_stock': self.is_low_stock
        }

    def __repr__(self):
        return f'<Product {self.product_code} - {self.product_name}>'
