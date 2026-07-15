"""
AI Insights
===========
Three data-driven features, all computed from data already in this database —
no external AI API, no ongoing cost:

- Reorder Suggestions: flags products likely to run out soon based on actual
  recent sales velocity, not just the static reorder_level threshold (which
  misses fast-movers still above their reorder level and over-flags slow
  movers that are technically "low" but won't run out for months).
- Sales Forecast: a simple linear trend projected forward from recent daily
  sales totals (least-squares regression — no ML framework needed for a
  trend line).
- Anomalies: surfaces patterns worth a manager's attention — discounts that
  exceeded a rep's role-based cap, cash declarations that didn't match what
  was counted, and unusually high payment-void rates.
"""
from flask import Blueprint, render_template, flash, redirect, url_for
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from sqlalchemy import func
from app import db
from models.sale import Sale, SaleItem
from models.product import Product

insights_bp = Blueprint('insights', __name__)


def _require_access():
    if not current_user.can_access('insights'):
        flash('Access denied.', 'danger')
        return False
    return True


@insights_bp.route('/')
@login_required
def index():
    if not _require_access():
        return redirect(url_for('dashboard.index'))
    return render_template('insights/index.html')


# ── Smart Reorder Suggestions ─────────────────────────────────────────────────
LOOKBACK_DAYS = 30
LEAD_TIME_DAYS = 14


@insights_bp.route('/reorder')
@login_required
def reorder():
    if not _require_access():
        return redirect(url_for('dashboard.index'))

    cutoff = datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)
    products = Product.query.filter_by(status='active').all()

    velocity_rows = db.session.query(
        SaleItem.product_id, func.sum(SaleItem.quantity)
    ).join(Sale).filter(
        Sale.status == 'completed', Sale.sale_date >= cutoff
    ).group_by(SaleItem.product_id).all()
    velocity_by_product = {pid: qty for pid, qty in velocity_rows}

    suggestions = []
    no_movement = []
    for p in products:
        sold = velocity_by_product.get(p.id, 0)
        daily_velocity = sold / LOOKBACK_DAYS
        if daily_velocity <= 0:
            if p.stock_quantity <= p.reorder_level:
                no_movement.append(p)
            continue
        days_left = round(p.stock_quantity / daily_velocity, 1)
        if days_left <= LEAD_TIME_DAYS:
            suggested_qty = max(0, round(daily_velocity * LEAD_TIME_DAYS - p.stock_quantity))
            suggestions.append({
                'product': p, 'daily_velocity': round(daily_velocity, 2),
                'days_left': days_left, 'suggested_qty': suggested_qty,
            })
    suggestions.sort(key=lambda x: x['days_left'])

    return render_template('insights/reorder.html', suggestions=suggestions,
        no_movement=no_movement, lookback_days=LOOKBACK_DAYS, lead_time_days=LEAD_TIME_DAYS)


# ── Sales Forecast ────────────────────────────────────────────────────────────
FORECAST_LOOKBACK_DAYS = 60
FORECAST_DAYS = 14


def _linear_regression(xs, ys):
    n = len(xs)
    if n < 2:
        return 0.0, (ys[0] if ys else 0.0)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return 0.0, mean_y
    slope = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n)) / denom
    intercept = mean_y - slope * mean_x
    return slope, intercept


@insights_bp.route('/forecast')
@login_required
def forecast():
    if not _require_access():
        return redirect(url_for('dashboard.index'))

    today = datetime.utcnow().date()
    start_date = today - timedelta(days=FORECAST_LOOKBACK_DAYS - 1)

    rows = db.session.query(
        func.date(Sale.sale_date), func.sum(Sale.total_amount)
    ).filter(
        Sale.status == 'completed', Sale.sale_date >= start_date
    ).group_by(func.date(Sale.sale_date)).all()
    by_day = {str(d): float(total or 0) for d, total in rows}

    history_labels, history_values, xs, ys = [], [], [], []
    for i in range(FORECAST_LOOKBACK_DAYS):
        d = start_date + timedelta(days=i)
        val = round(by_day.get(str(d), 0), 2)
        history_labels.append(d.strftime('%d %b'))
        history_values.append(val)
        xs.append(i)
        ys.append(val)

    slope, intercept = _linear_regression(xs, ys)

    forecast_labels, forecast_values = [], []
    for i in range(FORECAST_DAYS):
        idx = FORECAST_LOOKBACK_DAYS + i
        d = today + timedelta(days=i + 1)
        val = max(0, round(slope * idx + intercept, 2))
        forecast_labels.append(d.strftime('%d %b'))
        forecast_values.append(val)

    projected_total = round(sum(forecast_values), 2)
    recent_avg = round(sum(history_values[-14:]) / min(14, len(history_values)), 2) if history_values else 0
    trend = 'up' if slope > 0.5 else ('down' if slope < -0.5 else 'flat')

    return render_template('insights/forecast.html',
        history_labels=history_labels, history_values=history_values,
        forecast_labels=forecast_labels, forecast_values=forecast_values,
        projected_total=projected_total, recent_avg=recent_avg, trend=trend,
        forecast_days=FORECAST_DAYS)


# ── Anomaly Detection ──────────────────────────────────────────────────────────
@insights_bp.route('/anomalies')
@login_required
def anomalies():
    if not _require_access():
        return redirect(url_for('dashboard.index'))

    from models.user import User
    from models.cash_declaration import CashDeclaration
    from models.payment import Payment

    findings = []

    # 1. Discounts that exceeded the rep's role-based cap. create() now blocks
    # this going forward — this surfaces anything that got in before that
    # fix, or that predates it in the data.
    reps = User.query.filter(User.role.in_(['sales_rep', 'supervisor', 'manager', 'admin']), User.is_active == True).all()
    for rep in reps:
        cap = rep.max_discount()
        over_cap_sales = Sale.query.filter(
            Sale.sales_rep_id == rep.id, Sale.status == 'completed', Sale.discount_percent > cap
        ).all()
        for s in over_cap_sales:
            findings.append({
                'severity': 'high', 'type': 'Discount cap exceeded',
                'description': f'{rep.full_name} applied a {s.discount_percent:.0f}% discount on {s.invoice_number}, above their {cap:.0f}% limit.',
                'date': s.sale_date, 'link': url_for('invoices.view', sale_id=s.id),
            })
        over_cap_items = SaleItem.query.join(Sale).filter(
            Sale.sales_rep_id == rep.id, Sale.status == 'completed', SaleItem.discount_percent > cap
        ).all()
        for item in over_cap_items:
            findings.append({
                'severity': 'high', 'type': 'Discount cap exceeded',
                'description': f'{rep.full_name} applied a {item.discount_percent:.0f}% item discount on '
                                f'{item.sale.invoice_number} ({item.product.product_name if item.product else "unknown item"}), above their {cap:.0f}% limit.',
                'date': item.sale.sale_date, 'link': url_for('invoices.view', sale_id=item.sale_id),
            })

    # 2. Cash declarations that didn't match what was actually counted.
    discrepancies = CashDeclaration.query.filter(
        CashDeclaration.status == 'discrepancy'
    ).order_by(CashDeclaration.created_at.desc()).limit(100).all()
    for d in discrepancies:
        severity = 'high' if abs(d.discrepancy_amount or 0) >= 50 else 'medium'
        findings.append({
            'severity': severity, 'type': 'Cash declaration mismatch',
            'description': f'{d.sales_rep.full_name if d.sales_rep else "Unknown rep"} declared GHS {d.declared_amount:.2f} '
                            f'but GHS {d.counted_amount:.2f} was counted ({d.discrepancy_amount:+.2f} GHS) — {d.declaration_number}.',
            'date': d.created_at, 'link': url_for('cash_decl.index'),
        })

    # 3. Unusually high payment-void rate for a rep/cashier (only flagged with
    # a big enough sample size to mean something, not one voided payment
    # out of two).
    receivers = User.query.filter(User.role.in_(['sales_rep', 'cashier']), User.is_active == True).all()
    for u in receivers:
        total = Payment.query.filter_by(received_by_id=u.id).count()
        if total < 5:
            continue
        voided = Payment.query.filter_by(received_by_id=u.id, status='void').count()
        rate = voided / total
        if rate > 0.2:
            findings.append({
                'severity': 'medium', 'type': 'High void rate',
                'description': f'{u.full_name} has voided {voided} of {total} payments ({rate*100:.0f}%) — worth reviewing.',
                'date': None, 'link': url_for('payments.index'),
            })

    findings.sort(key=lambda f: (f['severity'] != 'high', f['date'] is None, f['date'] or datetime.min), reverse=False)

    return render_template('insights/anomalies.html', findings=findings)
