from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from app import db
from models.sale import Sale
from models.customer import Customer
from models.product import Product
from models.payment import Payment
from models.inventory import VanStock
from models.cash_declaration import CashDeclaration
from models.van_management import StockOffload
from services.cash_decl import rep_cash_balance
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from datetime import datetime, timedelta

dashboard_bp = Blueprint('dashboard', __name__)


def _daily_series(date_col, amount_col, filters, days=7, end_date=None):
    """Last `days` days of a daily SUM(amount_col) ending on `end_date`
    (defaults to real today), oldest first, as (labels, values) — feeds the
    trend chart on each dashboard without a separate AJAX round trip."""
    end_date = end_date or datetime.utcnow().date()
    start = end_date - timedelta(days=days - 1)
    rows = db.session.query(func.date(date_col).label('day'), func.sum(amount_col)).filter(
        *filters, date_col >= start
    ).group_by('day').all()
    by_day = {str(day): float(total or 0) for day, total in rows}
    labels, values = [], []
    for i in range(days):
        d = start + timedelta(days=i)
        labels.append(d.strftime('%a'))
        values.append(round(by_day.get(str(d), 0), 2))
    return labels, values


@dashboard_bp.route('/')
@login_required
def index():
    real_today = datetime.utcnow().date()
    date_param = request.args.get('date')
    today = real_today
    if date_param:
        try:
            today = datetime.strptime(date_param, '%Y-%m-%d').date()
        except ValueError:
            today = real_today
        # A dashboard for a date that hasn't happened yet is meaningless —
        # clamp to today rather than silently showing an all-zero page.
        if today > real_today:
            today = real_today

    yesterday = today - timedelta(days=1)
    month_start = today.replace(day=1)
    ctx = {'dashboard_date': today, 'is_today': today == real_today, 'real_today': real_today}

    if current_user.role in ('admin', 'manager'):
        ctx['total_sales_today'] = db.session.query(func.sum(Sale.total_amount)).filter(
            Sale.status == 'completed', func.date(Sale.sale_date) == today
        ).scalar() or 0
        ctx['total_sales_yesterday'] = db.session.query(func.sum(Sale.total_amount)).filter(
            Sale.status == 'completed', func.date(Sale.sale_date) == yesterday
        ).scalar() or 0
        ctx['total_sales_month'] = db.session.query(func.sum(Sale.total_amount)).filter(
            Sale.status == 'completed', Sale.sale_date >= month_start
        ).scalar() or 0
        ctx['total_outstanding'] = db.session.query(func.sum(Customer.outstanding_balance)).scalar() or 0
        ctx['active_customers'] = Customer.query.filter_by(status='active').count()
        ctx['low_stock_count'] = Product.query.filter(
            Product.stock_quantity <= Product.reorder_level, Product.status == 'active'
        ).count()

        ctx['trend_labels'], ctx['trend_values'] = _daily_series(
            Sale.sale_date, Sale.total_amount, [Sale.status == 'completed'], end_date=today)

        ctx['recent_sales'] = Sale.query.filter_by(status='completed').order_by(
            Sale.sale_date.desc()).limit(8).all()

    elif current_user.role == 'sales_rep':
        ctx['my_sales_today'] = db.session.query(func.sum(Sale.total_amount)).filter(
            Sale.sales_rep_id == current_user.id, Sale.status == 'completed',
            func.date(Sale.sale_date) == today
        ).scalar() or 0
        ctx['my_sales_month'] = db.session.query(func.sum(Sale.total_amount)).filter(
            Sale.sales_rep_id == current_user.id, Sale.status == 'completed',
            Sale.sale_date >= month_start
        ).scalar() or 0
        ctx['my_collections_today'] = db.session.query(func.sum(Payment.amount)).filter(
            Payment.received_by_id == current_user.id, func.date(Payment.payment_date) == today,
            Payment.status != 'void'
        ).scalar() or 0
        ctx['my_invoice_count'] = Sale.query.filter_by(
            sales_rep_id=current_user.id, status='completed'
        ).filter(func.date(Sale.sale_date) == today).count()
        van_stock = VanStock.query.options(joinedload(VanStock.product)).filter_by(
            sales_rep_id=current_user.id).filter(VanStock.quantity > 0).all()
        ctx['my_van_stock'] = van_stock
        ctx['my_van_stock_value'] = round(sum(
            (s.quantity * (s.product.cost_price if s.product else 0)) for s in van_stock), 2)
        ctx['trend_labels'], ctx['trend_values'] = _daily_series(
            Sale.sale_date, Sale.total_amount,
            [Sale.sales_rep_id == current_user.id, Sale.status == 'completed'], end_date=today)
        ctx['recent_sales'] = Sale.query.filter_by(
            sales_rep_id=current_user.id, status='completed'
        ).order_by(Sale.sale_date.desc()).limit(6).all()
        ctx['my_cash_balance'] = rep_cash_balance(current_user.id)['balance']

    elif current_user.role == 'supervisor':
        ctx['team_sales_today'] = db.session.query(func.sum(Sale.total_amount)).filter(
            Sale.status == 'completed', func.date(Sale.sale_date) == today
        ).scalar() or 0
        ctx['team_invoices_today'] = Sale.query.filter(
            Sale.status == 'completed', func.date(Sale.sale_date) == today
        ).count()
        ctx['active_customers'] = Customer.query.filter_by(status='active').count()
        ctx['total_outstanding'] = db.session.query(func.sum(Customer.outstanding_balance)).scalar() or 0
        ctx['low_stock_count'] = Product.query.filter(
            Product.stock_quantity <= Product.reorder_level, Product.status == 'active'
        ).count()
        from models.van import CustomerVisit
        ctx['visits_today'] = CustomerVisit.query.filter(
            func.date(CustomerVisit.visit_date) == today
        ).count()
        ctx['trend_labels'], ctx['trend_values'] = _daily_series(
            Sale.sale_date, Sale.total_amount, [Sale.status == 'completed'], end_date=today)
        ctx['recent_sales'] = Sale.query.filter_by(status='completed').order_by(
            Sale.sale_date.desc()).limit(8).all()

    elif current_user.role == 'warehouse_manager':
        ctx['total_products'] = Product.query.filter_by(status='active').count()
        ctx['low_stock'] = Product.query.filter(
            Product.stock_quantity <= Product.reorder_level, Product.status == 'active'
        ).all()
        ctx['out_of_stock'] = Product.query.filter(
            Product.stock_quantity == 0, Product.status == 'active').count()
        ctx['van_allocations'] = db.session.query(
            func.count(VanStock.id)).filter(VanStock.quantity > 0).scalar() or 0
        ctx['pending_offloads'] = StockOffload.query.filter_by(status='pending').count()

    elif current_user.role == 'cashier':
        ctx['collections_today'] = db.session.query(func.sum(Payment.amount)).filter(
            func.date(Payment.payment_date) == today, Payment.status != 'void'
        ).scalar() or 0
        ctx['payment_count'] = Payment.query.filter(
            func.date(Payment.payment_date) == today, Payment.status != 'void').count()
        ctx['trend_labels'], ctx['trend_values'] = _daily_series(
            Payment.payment_date, Payment.amount, [Payment.status != 'void'], end_date=today)
        ctx['total_outstanding'] = db.session.query(
            func.sum(Customer.outstanding_balance)).scalar() or 0
        ctx['pending_declarations'] = CashDeclaration.query.filter_by(status='pending').count()
        ctx['recent_payments'] = Payment.query.filter(
            func.date(Payment.payment_date) == today, Payment.status != 'void'
        ).order_by(Payment.payment_date.desc()).limit(8).all()

    return render_template(current_user.dashboard_template, **ctx)
