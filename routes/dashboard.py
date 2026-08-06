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


def _net_company_sales(query):
    """Sum of company_sales_total for the sales matched by `query`, minus
    the tip-excluded value of anything approved-returned from them. A
    returned item was never really "sold" for company-revenue purposes, so
    it must not keep inflating sales figures after the customer brings it
    back — same principle as the tip exclusion these figures already apply.
    Matches returns to their original sale line by product_id (same
    approach as Sale.return_status), since ReturnOrderItem.sale_item_id
    isn't reliably wired through from the return-creation form."""
    from models.returns import ReturnOrder
    sales = query.all()
    sale_ids = [s.id for s in sales]
    returned_by_sale = {}
    if sale_ids:
        for order in ReturnOrder.query.filter(ReturnOrder.sale_id.in_(sale_ids)).all():
            by_product = returned_by_sale.setdefault(order.sale_id, {})
            for item in order.items:
                if item.line_status == 'approved':
                    by_product[item.product_id] = by_product.get(item.product_id, 0) + item.quantity
    total = 0.0
    for s in sales:
        by_product = returned_by_sale.get(s.id)
        returned_value = 0.0
        if by_product:
            official_by_product = {i.product_id: (i.official_price or 0) for i in s.items}
            returned_value = sum(official_by_product.get(pid, 0) * qty for pid, qty in by_product.items())
        total += max(0, (s.company_sales_total or 0) - returned_value)
    return round(total, 2)


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
    # Scheduled-order SMS reminders are due-date-sensitive (a rep needs to
    # know TODAY, not whenever someone next opens the Notifications page) —
    # the dashboard is the one page everyone hits every time they log in, so
    # check here too. Isolated in its own try/except so a bad row (or an SMS
    # provider outage) can never take the dashboard down with it.
    from services.notification_service import check_due_scheduled_orders
    try:
        check_due_scheduled_orders()
    except Exception:
        db.session.rollback()

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
        # company_sales_total (official_price × qty), not total_amount — a
        # rep's tip markup on top of the official price belongs to the rep,
        # not the company, so it must never inflate the company's sales
        # figures (same convention as reports/profit_loss.py's gross_revenue).
        # Net of approved returns too — see _net_company_sales().
        ctx['total_sales_today'] = _net_company_sales(Sale.query.filter(
            Sale.status == 'completed', func.date(Sale.sale_date) == today))
        ctx['total_sales_yesterday'] = _net_company_sales(Sale.query.filter(
            Sale.status == 'completed', func.date(Sale.sale_date) == yesterday))
        ctx['total_sales_month'] = _net_company_sales(Sale.query.filter(
            Sale.status == 'completed', Sale.sale_date >= month_start))
        ctx['total_outstanding'] = db.session.query(func.sum(Customer.outstanding_balance)).scalar() or 0
        ctx['active_customers'] = Customer.query.filter_by(status='active').count()
        ctx['low_stock_count'] = Product.query.filter(
            Product.stock_quantity <= Product.reorder_level, Product.status == 'active'
        ).count()

        ctx['trend_labels'], ctx['trend_values'] = _daily_series(
            Sale.sale_date, Sale.company_sales_total, [Sale.status == 'completed'], end_date=today)

        ctx['recent_sales'] = Sale.query.filter_by(status='completed').order_by(
            Sale.sale_date.desc()).limit(8).all()

    elif current_user.role == 'sales_rep':
        # company_sales_total, not total_amount — see admin/manager branch
        # above; a rep's own tip earnings are shown separately in the Tips
        # module, not folded into their "sales" figures here. Net of
        # approved returns too — see _net_company_sales().
        ctx['my_sales_today'] = _net_company_sales(Sale.query.filter(
            Sale.sales_rep_id == current_user.id, Sale.status == 'completed',
            func.date(Sale.sale_date) == today))
        ctx['my_sales_month'] = _net_company_sales(Sale.query.filter(
            Sale.sales_rep_id == current_user.id, Sale.status == 'completed',
            Sale.sale_date >= month_start))
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
            Sale.sale_date, Sale.company_sales_total,
            [Sale.sales_rep_id == current_user.id, Sale.status == 'completed'], end_date=today)
        ctx['recent_sales'] = Sale.query.filter_by(
            sales_rep_id=current_user.id, status='completed'
        ).order_by(Sale.sale_date.desc()).limit(6).all()
        ctx['my_cash_balance'] = rep_cash_balance(current_user.id)['balance']

    elif current_user.role == 'supervisor':
        # company_sales_total, not total_amount — see admin/manager branch
        # above. Net of approved returns too — see _net_company_sales().
        ctx['team_sales_today'] = _net_company_sales(Sale.query.filter(
            Sale.status == 'completed', func.date(Sale.sale_date) == today))
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
            Sale.sale_date, Sale.company_sales_total, [Sale.status == 'completed'], end_date=today)
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
