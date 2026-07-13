"""
Tips / Markup Module
====================
- Sales Rep  : view only their own tips (read-only)
- Admin      : view, filter, edit, delete all tips; full report
- Manager    : view all tips (read-only)
- Supervisor : NO access
- Customer   : NEVER sees tips (invoices show final price only)

Business logic:
  official_price  = product.selling_price  (from the system)
  tip_amount      = rep markup per unit    (optional, added at sale time)
  unit_price      = official_price + tip   (what the customer pays)
  line_total      = unit_price × qty       (shown on invoice)
"""
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from sqlalchemy import func
from app import db
from models.sale import Sale, SaleItem
from models.user import User

tips_bp = Blueprint('tips', __name__)


def _require_tip_access():
    """Returns True if current user may access the tips module at all."""
    return current_user.role in ('admin', 'manager', 'sales_rep')


def _can_admin_tips():
    return current_user.role in ('admin', 'manager')


# ── My Tips (Sales Rep view) ──────────────────────────────────────────────────
@tips_bp.route('/my-tips')
@login_required
def my_tips():
    if current_user.role not in ('admin', 'manager', 'sales_rep'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    start = request.args.get('start', (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end   = request.args.get('end',   datetime.utcnow().strftime('%Y-%m-%d'))

    # Only own sales if rep; all sales if admin/manager
    q = db.session.query(SaleItem).join(Sale).filter(
        Sale.status == 'completed',
        Sale.sale_date >= start,
        Sale.sale_date <= end + ' 23:59:59',
        SaleItem.tip_amount > 0
    )
    if current_user.role == 'sales_rep':
        q = q.filter(Sale.sales_rep_id == current_user.id)

    items = q.order_by(Sale.sale_date.desc()).all()

    total_tip = round(sum(i.tip_line_total for i in items), 2)
    total_qty  = sum(i.quantity for i in items)
    total_sales_value = round(sum(i.line_total for i in items), 2)

    return render_template('tips/my_tips.html',
        items=items, total_tip=total_tip,
        total_qty=total_qty, total_sales_value=total_sales_value,
        start=start, end=end)


# ── Admin Tips Report ─────────────────────────────────────────────────────────
@tips_bp.route('/report')
@login_required
def report():
    if not _can_admin_tips():
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    start      = request.args.get('start', (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end        = request.args.get('end',   datetime.utcnow().strftime('%Y-%m-%d'))
    rep_id     = request.args.get('rep_id',     type=int)
    product_id = request.args.get('product_id', type=int)
    customer_id= request.args.get('customer_id',type=int)

    q = db.session.query(SaleItem).join(Sale).filter(
        Sale.status == 'completed',
        Sale.sale_date >= start,
        Sale.sale_date <= end + ' 23:59:59',
        SaleItem.tip_amount > 0
    )
    if rep_id:
        q = q.filter(Sale.sales_rep_id == rep_id)
    if product_id:
        q = q.filter(SaleItem.product_id == product_id)
    if customer_id:
        q = q.filter(Sale.customer_id == customer_id)

    items = q.order_by(Sale.sale_date.desc()).all()

    # Summary by rep
    by_rep = {}
    for i in items:
        rep = i.sale.sales_rep
        rid = rep.id if rep else 0
        if rid not in by_rep:
            by_rep[rid] = {'rep': rep, 'tip_total': 0, 'count': 0, 'sales_value': 0}
        by_rep[rid]['tip_total']    += i.tip_line_total
        by_rep[rid]['count']        += i.quantity
        by_rep[rid]['sales_value']  += i.line_total
    by_rep_list = sorted(by_rep.values(), key=lambda x: x['tip_total'], reverse=True)

    # Summary by product
    by_product = {}
    for i in items:
        pid = i.product_id
        if pid not in by_product:
            by_product[pid] = {'product': i.product, 'tip_total': 0, 'count': 0}
        by_product[pid]['tip_total'] += i.tip_line_total
        by_product[pid]['count']     += i.quantity
    by_product_list = sorted(by_product.values(), key=lambda x: x['tip_total'], reverse=True)[:10]

    # Daily / monthly tip summaries
    daily = {}
    monthly = {}
    for i in items:
        d = i.sale.sale_date
        if not d:
            continue
        day_key = d.strftime('%Y-%m-%d')
        month_key = d.strftime('%Y-%m')
        daily.setdefault(day_key, {'date': day_key, 'tip_total': 0, 'count': 0})
        daily[day_key]['tip_total'] += i.tip_line_total
        daily[day_key]['count']     += i.quantity
        monthly.setdefault(month_key, {'month': month_key, 'tip_total': 0, 'count': 0})
        monthly[month_key]['tip_total'] += i.tip_line_total
        monthly[month_key]['count']     += i.quantity
    daily_summary   = sorted(daily.values(),   key=lambda x: x['date'],  reverse=True)
    monthly_summary = sorted(monthly.values(), key=lambda x: x['month'], reverse=True)

    total_tip   = round(sum(i.tip_line_total for i in items), 2)

    # Company sales / grand total across ALL completed sales in the period
    # (not just lines with a tip) — the true invoice-level picture.
    period_sales_q = Sale.query.filter(
        Sale.status == 'completed',
        Sale.sale_date >= start,
        Sale.sale_date <= end + ' 23:59:59'
    )
    if rep_id:
        period_sales_q = period_sales_q.filter(Sale.sales_rep_id == rep_id)
    period_sales = period_sales_q.all()
    company_sales_total   = round(sum(s.company_sales_total or 0 for s in period_sales), 2)
    grand_total_collected = round(sum(s.total_amount or 0 for s in period_sales), 2)

    reps        = User.query.filter(User.role == 'sales_rep', User.is_active == True).all()
    from models.product import Product
    from models.customer import Customer
    products    = Product.query.filter_by(status='active').order_by(Product.product_name).all()
    customers   = Customer.query.filter_by(status='active').order_by(Customer.name).all()

    return render_template('tips/report.html',
        items=items, total_tip=total_tip,
        by_rep=by_rep_list, by_product=by_product_list,
        daily_summary=daily_summary, monthly_summary=monthly_summary,
        company_sales_total=company_sales_total, grand_total_collected=grand_total_collected,
        reps=reps, products=products, customers=customers,
        start=start, end=end,
        sel_rep=rep_id, sel_product=product_id, sel_customer=customer_id)


# ── Admin: Edit a tip amount on a SaleItem ─────────────────────────────────────
@tips_bp.route('/edit/<int:item_id>', methods=['POST'])
@login_required
def edit_tip(item_id):
    if current_user.role != 'admin':
        return jsonify({'error': 'Admin only'}), 403

    item = SaleItem.query.get_or_404(item_id)
    data = request.get_json()
    new_tip = float(data.get('tip_amount', 0))

    if new_tip < 0:
        return jsonify({'error': 'Tip cannot be negative'}), 400

    # Recalculate unit_price and line_total
    item.tip_amount  = round(new_tip, 2)
    item.unit_price  = round(item.official_price + new_tip, 2)
    item.calculate_total()

    # Recalculate the parent sale totals
    item.sale.recalculate()

    from models.audit import PricingAuditLog
    db.session.add(PricingAuditLog(
        user_id=current_user.id,
        sale_id=item.sale_id,
        invoice_number=item.sale.invoice_number,
        product_id=item.product_id,
        company_selling_price=item.official_price,
        selling_price_entered=item.unit_price,
        tip_calculated=item.tip_amount,
        quantity=item.quantity,
        total_amount=item.line_total,
        action='tip_edit'
    ))
    db.session.commit()

    return jsonify({
        'success': True,
        'tip_amount':  item.tip_amount,
        'unit_price':  item.unit_price,
        'line_total':  item.line_total,
        'sale_total':  item.sale.total_amount
    })


# ── Admin: Delete (zero-out) a tip ──────────────────────────────────────────
@tips_bp.route('/delete/<int:item_id>', methods=['POST'])
@login_required
def delete_tip(item_id):
    if current_user.role != 'admin':
        return jsonify({'error': 'Admin only'}), 403

    item = SaleItem.query.get_or_404(item_id)
    item.tip_amount = 0.0
    item.unit_price = item.official_price
    item.calculate_total()
    item.sale.recalculate()

    from models.audit import PricingAuditLog
    db.session.add(PricingAuditLog(
        user_id=current_user.id,
        sale_id=item.sale_id,
        invoice_number=item.sale.invoice_number,
        product_id=item.product_id,
        company_selling_price=item.official_price,
        selling_price_entered=item.unit_price,
        tip_calculated=0.0,
        quantity=item.quantity,
        total_amount=item.line_total,
        action='tip_delete'
    ))
    db.session.commit()

    return jsonify({'success': True, 'message': f'Tip removed from {item.product.product_name if item.product else "item"}'})


# ── API: Tips summary for dashboards ─────────────────────────────────────────
@tips_bp.route('/api/summary')
@login_required
def api_summary():
    if not _require_tip_access():
        return jsonify({'error': 'Access denied'}), 403

    today = datetime.utcnow().date()
    month_start = today.replace(day=1).isoformat()

    q = db.session.query(func.sum(SaleItem.tip_amount * SaleItem.quantity)).join(Sale).filter(
        Sale.status == 'completed',
        SaleItem.tip_amount > 0
    )

    if current_user.role == 'sales_rep':
        q = q.filter(Sale.sales_rep_id == current_user.id)

    total_all_time = q.scalar() or 0
    total_this_month = (q.filter(Sale.sale_date >= month_start).scalar() or 0)
    total_today = (q.filter(Sale.sale_date >= today.isoformat()).scalar() or 0)

    return jsonify({
        'total_all_time':   round(float(total_all_time), 2),
        'total_this_month': round(float(total_this_month), 2),
        'total_today':      round(float(total_today), 2)
    })
