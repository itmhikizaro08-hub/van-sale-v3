from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from app import db
from models.product import Product
from models.customer import Customer
from models.sale import Sale
from sqlalchemy import func

api_bp = Blueprint('api', __name__)


@api_bp.route('/products/search')
@login_required
def products_search():
    if not current_user.can_access('products'):
        return jsonify([]), 403
    q = request.args.get('q', '')
    products = Product.query.filter(
        (Product.product_name.ilike(f'%{q}%') | Product.product_code.ilike(f'%{q}%') | Product.barcode.ilike(f'%{q}%')),
        Product.status == 'active'
    ).limit(15).all()

    # Sales reps sell out of their own van custody, not the warehouse —
    # show/enforce their van stock instead of company-wide stock_quantity.
    van_qty = {}
    if current_user.role == 'sales_rep':
        from models.notification import VanStock
        rows = db.session.query(VanStock.product_id, func.sum(VanStock.quantity)).filter(
            VanStock.sales_rep_id == current_user.id
        ).group_by(VanStock.product_id).all()
        van_qty = {pid: int(qty or 0) for pid, qty in rows}

    results = []
    for p in products:
        d = p.to_dict()
        if not current_user.see_cost_prices():
            d.pop('cost_price', None)
        if current_user.role == 'sales_rep':
            d['stock_quantity'] = van_qty.get(p.id, 0)
        results.append(d)
    return jsonify(results)


@api_bp.route('/customers/search')
@login_required
def customers_search():
    if not current_user.can_access('customers'):
        return jsonify([]), 403
    q = request.args.get('q', '')
    query = Customer.query.filter(
        (Customer.name.ilike(f'%{q}%') | Customer.customer_code.ilike(f'%{q}%') | Customer.phone.ilike(f'%{q}%')),
        Customer.status == 'active'
    )
    # A rep scoped to 'own' customers must not be able to look up every
    # other rep's customers through this autocomplete, same as customers.py.
    if current_user.scope('customers') == 'own':
        query = query.filter_by(sales_rep_id=current_user.id)
    customers = query.limit(15).all()
    return jsonify([c.to_dict() for c in customers])


@api_bp.route('/stats/summary')
@login_required
def stats_summary():
    from datetime import datetime
    today = datetime.utcnow().date()
    today_sales = db.session.query(func.sum(Sale.total_amount)).filter(
        func.date(Sale.sale_date) == today, Sale.status == 'completed'
    ).scalar() or 0
    outstanding = db.session.query(func.sum(Customer.outstanding_balance)).scalar() or 0
    return jsonify({
        'today_sales': float(today_sales),
        'outstanding': float(outstanding),
        'customers': Customer.query.filter_by(status='active').count(),
        'low_stock': Product.query.filter(Product.stock_quantity <= Product.reorder_level, Product.status == 'active').count()
    })
