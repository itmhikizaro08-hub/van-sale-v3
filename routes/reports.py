from flask import Blueprint, render_template, request, make_response, flash, redirect, url_for
from flask_login import login_required, current_user
from datetime import datetime, timedelta, date
from sqlalchemy import func
from app import db
from models.sale import Sale, SaleItem
from models.customer import Customer
from models.product import Product
from models.payment import Payment

reports_bp = Blueprint('reports', __name__)


def _date_range():
    start = request.args.get('start', (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end   = request.args.get('end',   datetime.utcnow().strftime('%Y-%m-%d'))
    return start, end


# ── Reports home ──────────────────────────────────────────────────────────────
@reports_bp.route('/')
@login_required
def index():
    return render_template('reports/index.html')


# ── Profit & Loss ─────────────────────────────────────────────────────────────
@reports_bp.route('/profit-loss')
@login_required
def profit_loss():
    # Requires cost-price visibility, not just general reports access — the
    # whole point of this report is margin, which is meaningless without cost.
    if not current_user.can_access('reports') or not current_user.see_cost_prices():
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    from models.notification import Expense
    start, end = _date_range()
    end_bound = end + ' 23:59:59'

    sales = Sale.query.filter(
        Sale.status == 'completed',
        Sale.sale_date >= start, Sale.sale_date <= end_bound
    ).all()

    gross_revenue = round(sum(s.total_amount for s in sales), 2)

    # COGS: quantity sold × each product's CURRENT cost price. There's no
    # historical cost snapshot per sale item (unlike official_price for
    # tips), so this is an approximation that drifts if cost prices have
    # changed since the sale — acceptable for a trend report, not for audit.
    cogs = 0.0
    for s in sales:
        for item in s.items:
            cogs += item.quantity * (item.product.cost_price if item.product else 0)
    cogs = round(cogs, 2)

    # Credit notes reduce what was actually collected, same convention as
    # sales_report()'s net_total.
    total_credits = 0.0
    try:
        from models.v4_models import CreditNote
        credit_notes = CreditNote.query.filter(
            CreditNote.status == 'applied',
            CreditNote.created_at >= start, CreditNote.created_at <= end_bound
        ).all()
        total_credits = round(sum(cn.amount for cn in credit_notes), 2)
    except Exception:
        pass

    net_revenue = round(gross_revenue - total_credits, 2)
    gross_profit = round(net_revenue - cogs, 2)
    gross_margin_pct = round(gross_profit / net_revenue * 100, 1) if net_revenue > 0 else 0

    expenses = Expense.query.filter(
        Expense.status == 'approved',
        Expense.expense_date >= start, Expense.expense_date <= end_bound
    ).all()
    total_expenses = round(sum(e.amount for e in expenses), 2)
    expenses_by_category = {}
    for e in expenses:
        expenses_by_category[e.category] = round(expenses_by_category.get(e.category, 0) + e.amount, 2)
    expenses_by_category = sorted(expenses_by_category.items(), key=lambda x: x[1], reverse=True)

    net_profit = round(gross_profit - total_expenses, 2)
    net_margin_pct = round(net_profit / net_revenue * 100, 1) if net_revenue > 0 else 0

    return render_template('reports/profit_loss.html', start=start, end=end,
        gross_revenue=gross_revenue, total_credits=total_credits, net_revenue=net_revenue,
        cogs=cogs, gross_profit=gross_profit, gross_margin_pct=gross_margin_pct,
        expenses_by_category=expenses_by_category, total_expenses=total_expenses,
        net_profit=net_profit, net_margin_pct=net_margin_pct)


# ── Sales Report ──────────────────────────────────────────────────────────────
@reports_bp.route('/sales')
@login_required
def sales_report():
    if not current_user.can_access('reports'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    start, end = _date_range()
    q = Sale.query.filter(
        Sale.status == 'completed',
        Sale.sale_date >= start,
        Sale.sale_date <= end + ' 23:59:59'
    )
    if current_user.scope('sales') == 'own':
        q = q.filter(Sale.sales_rep_id == current_user.id)
    sales = q.order_by(Sale.sale_date.desc()).all()

    # Attach credit note totals
    try:
        from models.v4_models import CreditNote
        for s in sales:
            cns = CreditNote.query.filter_by(sale_id=s.id, status='applied').all()
            s.credit_note_total = sum(cn.amount for cn in cns)
            s.net_total = s.total_amount - s.credit_note_total
    except Exception:
        for s in sales:
            s.credit_note_total = 0
            s.net_total = s.total_amount

    total            = round(sum(s.total_amount for s in sales), 2)
    total_paid       = round(sum(s.amount_paid for s in sales), 2)
    total_outstanding= round(sum(s.balance_due for s in sales), 2)
    total_credits    = round(sum(s.credit_note_total for s in sales), 2)
    net_total        = round(total - total_credits, 2)

    return render_template('reports/sales.html',
        sales=sales, total=total, total_paid=total_paid,
        total_outstanding=total_outstanding, total_credits=total_credits,
        net_total=net_total, start=start, end=end)


# ── Sales Excel Export ────────────────────────────────────────────────────────
@reports_bp.route('/sales/excel')
@login_required
def sales_excel():
    if not current_user.can_access('reports'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    import pandas as pd, io
    start, end = _date_range()
    q = Sale.query.filter(
        Sale.status == 'completed',
        Sale.sale_date >= start,
        Sale.sale_date <= end + ' 23:59:59'
    )
    # Same 'own' scope filter as sales_report() — without it a rep could
    # bypass their own-sales restriction just by hitting the Excel export.
    if current_user.scope('sales') == 'own':
        q = q.filter(Sale.sales_rep_id == current_user.id)
    sales = q.all()
    data = [{
        'Invoice':    s.invoice_number,
        'Customer':   s.customer.name if s.customer else '',
        'Date':       s.sale_date.strftime('%Y-%m-%d') if s.sale_date else '',
        'Van':        s.van.van_number if s.van else 'Warehouse',
        'Rep':        s.sales_rep.full_name if s.sales_rep else '',
        'Total':      s.total_amount,
        'Paid':       s.amount_paid,
        'Balance':    s.balance_due,
        'Status':     s.payment_status,
        'Ref Note':   s.reference_note or ''
    } for s in sales]
    df = pd.DataFrame(data)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        df.to_excel(w, index=False, sheet_name='Sales')
    buf.seek(0)
    response = make_response(buf.read())
    response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    response.headers['Content-Disposition'] = f'attachment; filename=sales_{start}_{end}.xlsx'
    return response


# ── Customer Report ───────────────────────────────────────────────────────────
@reports_bp.route('/customers')
@login_required
def customers_report():
    if not current_user.can_access('customers'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    q = Customer.query
    if current_user.scope('customers') == 'own':
        q = q.filter_by(sales_rep_id=current_user.id)
    customers = q.order_by(Customer.outstanding_balance.desc()).all()
    for c in customers:
        c.total_sales = db.session.query(func.sum(Sale.total_amount)).filter(
            Sale.customer_id == c.id, Sale.status == 'completed'
        ).scalar() or 0
        c.total_payments = db.session.query(func.sum(Payment.amount)).filter(
            Payment.customer_id == c.id, Payment.status != 'void'
        ).scalar() or 0
    return render_template('reports/customers.html', customers=customers)


# ── Inventory Report ──────────────────────────────────────────────────────────
@reports_bp.route('/inventory')
@login_required
def inventory_report():
    if not current_user.can_access('inventory'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    from models.notification import VanStock
    products = Product.query.filter_by(status='active').order_by(Product.product_name).all()
    warehouse_value = round(sum(p.stock_quantity * p.cost_price for p in products), 2)
    field_stocks = db.session.query(
        VanStock.product_id, func.sum(VanStock.quantity).label('fq')
    ).group_by(VanStock.product_id).all()
    field_map = {r.product_id: int(r.fq or 0) for r in field_stocks}
    for p in products:
        p.field_qty   = field_map.get(p.id, 0)
        p.total_value = round((p.stock_quantity + p.field_qty) * p.cost_price, 2)
    field_value = round(sum(field_map.get(p.id, 0) * p.cost_price for p in products), 2)
    total_value = round(sum(p.total_value for p in products), 2)
    return render_template('reports/inventory.html',
        products=products, warehouse_value=warehouse_value,
        field_value=field_value, total_value=total_value)


# ── Inventory Excel Export ────────────────────────────────────────────────────
@reports_bp.route('/inventory/excel')
@login_required
def inventory_excel():
    if not current_user.can_access('inventory'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    import pandas as pd, io
    from models.notification import VanStock
    products = Product.query.filter_by(status='active').all()
    field_stocks = db.session.query(
        VanStock.product_id, func.sum(VanStock.quantity).label('fq')
    ).group_by(VanStock.product_id).all()
    field_map = {r.product_id: int(r.fq or 0) for r in field_stocks}
    data = [{
        'Code':      p.product_code,
        'Name':      p.product_name,
        'Warehouse': p.stock_quantity,
        'Field':     field_map.get(p.id, 0),
        'Total':     p.stock_quantity + field_map.get(p.id, 0),
        'Cost':      p.cost_price,
        'Sell':      p.selling_price,
        'Value':     round((p.stock_quantity + field_map.get(p.id, 0)) * p.cost_price, 2)
    } for p in products]
    df = pd.DataFrame(data)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        df.to_excel(w, index=False, sheet_name='Inventory')
    buf.seek(0)
    response = make_response(buf.read())
    response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    response.headers['Content-Disposition'] = 'attachment; filename=inventory.xlsx'
    return response


# ── Debt Ageing ───────────────────────────────────────────────────────────────
@reports_bp.route('/debt-ageing')
@login_required
def debt_ageing():
    if not current_user.can_access('customers'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    q = Customer.query.filter(Customer.outstanding_balance > 0)
    if current_user.scope('customers') == 'own':
        q = q.filter_by(sales_rep_id=current_user.id)
    today = date.today()
    customers = q.all()
    buckets = {'0_30': [], '31_60': [], '61_90': [], '90_plus': []}
    for c in customers:
        oldest = Sale.query.filter_by(customer_id=c.id, status='completed').filter(
            Sale.balance_due > 0
        ).order_by(Sale.sale_date.asc()).first()
        days = (today - oldest.sale_date.date()).days if oldest and oldest.sale_date else 0
        row = {'customer': c, 'balance': c.outstanding_balance,
               'oldest_invoice': oldest.invoice_number if oldest else '—', 'days': days}
        if days <= 30:   buckets['0_30'].append(row)
        elif days <= 60: buckets['31_60'].append(row)
        elif days <= 90: buckets['61_90'].append(row)
        else:            buckets['90_plus'].append(row)
    totals = {k: round(sum(r['balance'] for r in v), 2) for k, v in buckets.items()}
    grand_total = round(sum(totals.values()), 2)
    return render_template('reports/debt_ageing.html',
        buckets=buckets, totals=totals, grand_total=grand_total)


# ── Debt Ageing Excel ─────────────────────────────────────────────────────────
@reports_bp.route('/debt-ageing/excel')
@login_required
def debt_ageing_excel():
    if not current_user.can_access('customers'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    import pandas as pd, io
    q = Customer.query.filter(Customer.outstanding_balance > 0)
    if current_user.scope('customers') == 'own':
        q = q.filter_by(sales_rep_id=current_user.id)
    today = date.today()
    customers = q.all()
    data = []
    for c in customers:
        oldest = Sale.query.filter_by(customer_id=c.id, status='completed').filter(
            Sale.balance_due > 0).order_by(Sale.sale_date.asc()).first()
        days = (today - oldest.sale_date.date()).days if oldest and oldest.sale_date else 0
        bucket = '0-30 days' if days <= 30 else '31-60 days' if days <= 60 else '61-90 days' if days <= 90 else '90+ days'
        data.append({'Customer': c.name, 'Code': c.customer_code, 'Phone': c.phone or '',
                     'Outstanding': c.outstanding_balance, 'Days': days, 'Bucket': bucket})
    df = pd.DataFrame(data).sort_values('Outstanding', ascending=False) if data else pd.DataFrame()
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        df.to_excel(w, index=False, sheet_name='Debt Ageing')
    buf.seek(0)
    response = make_response(buf.read())
    response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    response.headers['Content-Disposition'] = 'attachment; filename=debt_ageing.xlsx'
    return response


# ── Rep Stock Liability ───────────────────────────────────────────────────────
@reports_bp.route('/rep-liability')
@login_required
def rep_liability():
    if not current_user.can_access('van_stock'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    from models.notification import VanStock
    from models.user import User
    reps = User.query.filter(
        User.role.in_(['sales_rep', 'supervisor']), User.is_active == True
    ).all()
    if current_user.scope('van_stock') == 'own':
        reps = [r for r in reps if r.id == current_user.id]
    liabilities = []
    for rep in reps:
        rows = VanStock.query.filter_by(sales_rep_id=rep.id).filter(VanStock.quantity > 0).all()
        if not rows: continue
        total_value = round(sum(r.quantity * (r.product.cost_price if r.product else 0) for r in rows), 2)
        total_qty   = sum(r.quantity for r in rows)
        vans_held   = sorted(set(r.van.van_number for r in rows if r.van))
        liabilities.append({'rep': rep, 'items': rows, 'total_value': total_value,
                            'total_qty': total_qty, 'vans': vans_held})
    total_value = round(sum(r['total_value'] for r in liabilities), 2)
    return render_template('reports/rep_liability.html',
        liabilities=liabilities, total_value=total_value)


# ── Sales Rep Statement ─────────────────────────────────────────────────────────
@reports_bp.route('/rep-statement')
@login_required
def rep_statement():
    if not current_user.can_access('reports'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    from models.user import User
    from models.notification import VanStock
    from models.cash_declaration import CashDeclaration
    from models.van_management import StockOffload, StockOffloadItem
    from services.cash_decl import rep_cash_summary_range

    start, end = _date_range()
    end_bound = end + ' 23:59:59'

    reps = User.query.filter(User.role.in_(['sales_rep', 'supervisor']), User.is_active == True) \
        .order_by(User.full_name).all()

    if current_user.scope('reports') == 'own':
        rep_id = current_user.id
    else:
        rep_id = request.args.get('rep_id', type=int) or (reps[0].id if reps else None)

    rep = User.query.get(rep_id) if rep_id else None
    if not rep:
        return render_template('reports/rep_statement.html', reps=reps, rep=None,
            own_scope=(current_user.scope('reports') == 'own'), start=start, end=end)

    # ── Sales ──────────────────────────────────────────────────────────────────
    sales = Sale.query.filter(
        Sale.sales_rep_id == rep.id, Sale.status == 'completed',
        Sale.sale_date >= start, Sale.sale_date <= end_bound
    ).all()
    sales_count = len(sales)
    sales_total = round(sum(s.total_amount or 0 for s in sales), 2)
    company_sales_total = round(sum(s.company_sales_total or 0 for s in sales), 2)
    tips_total = round(sum(s.total_tips_amount or 0 for s in sales), 2)

    # ── Cash ───────────────────────────────────────────────────────────────────
    cash = rep_cash_summary_range(rep.id, start, end)

    # ── Stock offloaded this period ─────────────────────────────────────────────
    offloads = StockOffload.query.filter(
        StockOffload.sales_rep_id == rep.id,
        StockOffload.created_at >= start, StockOffload.created_at <= end_bound
    ).all()
    offload_count = len(offloads)
    offload_value = 0.0
    for o in offloads:
        for item in o.items:
            qty = item.quantity_received if item.quantity_received is not None else 0
            offload_value += qty * (item.product.cost_price if item.product else 0)
    offload_value = round(offload_value, 2)

    # ── Current van stock liability (point-in-time, not date-ranged) ────────────
    liability_rows = VanStock.query.filter_by(sales_rep_id=rep.id).filter(VanStock.quantity > 0).all()
    liability_value = round(sum(r.quantity * (r.product.cost_price if r.product else 0) for r in liability_rows), 2)
    liability_qty = sum(r.quantity for r in liability_rows)

    return render_template('reports/rep_statement.html', reps=reps, rep=rep,
        own_scope=(current_user.scope('reports') == 'own'), start=start, end=end,
        sales_count=sales_count, sales_total=sales_total,
        company_sales_total=company_sales_total, tips_total=tips_total,
        cash=cash, offload_count=offload_count, offload_value=offload_value,
        liability_value=liability_value, liability_qty=liability_qty)


# ── Returns Analysis ──────────────────────────────────────────────────────────
@reports_bp.route('/returns-analysis')
@login_required
def returns_analysis():
    if not current_user.can_access('returns'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    start, end = _date_range()
    try:
        from models.v4_models import ReturnOrder
        orders = ReturnOrder.query.filter(
            ReturnOrder.created_at >= start,
            ReturnOrder.created_at <= end + ' 23:59:59'
        ).all()
    except Exception:
        orders = []
    reason_map, product_map, rep_map = {}, {}, {}
    for order in orders:
        for item in order.items:
            reason_map[item.reason] = reason_map.get(item.reason, 0) + item.line_total
            pname = item.product.product_name if item.product else 'Unknown'
            product_map[pname] = product_map.get(pname, 0) + item.quantity
            if order.received_by_rep_id and order.received_by_rep:
                rname = order.received_by_rep.full_name
                rep_map[rname] = rep_map.get(rname, 0) + item.line_total
    by_reason  = sorted(reason_map.items(), key=lambda x: x[1], reverse=True)
    by_product = sorted(product_map.items(), key=lambda x: x[1], reverse=True)[:10]
    by_rep     = sorted(rep_map.items(), key=lambda x: x[1], reverse=True)
    total_refund = round(sum(o.total_refund_amount for o in orders if o.status in ('approved', 'partial')), 2)
    return render_template('reports/returns_analysis.html',
        orders=orders, by_reason=by_reason, by_product=by_product,
        by_rep=by_rep, total_refund=total_refund, start=start, end=end)


# ── Van Performance ───────────────────────────────────────────────────────────
@reports_bp.route('/van-performance')
@login_required
def van_performance():
    if not current_user.can_access('vans'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    from models.van import Van
    start, end = _date_range()
    vans = Van.query.all()
    for van in vans:
        van.total_sales = db.session.query(func.sum(Sale.total_amount)).filter(
            Sale.van_id == van.id, Sale.status == 'completed',
            Sale.sale_date >= start, Sale.sale_date <= end + ' 23:59:59'
        ).scalar() or 0
        van.sale_count = Sale.query.filter(
            Sale.van_id == van.id, Sale.status == 'completed',
            Sale.sale_date >= start, Sale.sale_date <= end + ' 23:59:59'
        ).count()
    return render_template('reports/van_performance.html', vans=vans, start=start, end=end)
