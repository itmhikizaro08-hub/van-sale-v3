from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from app import db
from models.sale import Sale
from models.expense import Expense
from models.payment import Payment
from models.supplier import Supplier
from models.customer import Customer
from models.cash_declaration import CashDeclaration
from sqlalchemy import func

finance_bp = Blueprint('finance', __name__)


def _date_range():
    start = request.args.get('start', (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end = request.args.get('end', datetime.utcnow().strftime('%Y-%m-%d'))
    return start, end


@finance_bp.route('/')
@login_required
def index():
    if not current_user.can_access('finance'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    start, end = _date_range()
    end_bound = end + ' 23:59:59'

    # ── Revenue & COGS (same convention as reports.profit_loss: company
    # revenue is official_price x qty, not what a customer paid including a
    # rep's tip markup; credit notes reduce what was actually collected) ──
    sales = Sale.query.filter(
        Sale.status == 'completed',
        Sale.sale_date >= start, Sale.sale_date <= end_bound
    ).all()
    gross_revenue = round(sum(s.company_sales_total or 0 for s in sales), 2)

    from models.notes import CreditNote
    credit_notes = CreditNote.query.filter(
        CreditNote.status == 'applied',
        CreditNote.created_at >= start, CreditNote.created_at <= end_bound
    ).all()
    total_credits = round(sum(cn.amount for cn in credit_notes), 2)
    net_revenue = round(gross_revenue - total_credits, 2)

    cogs = 0.0
    for s in sales:
        for item in s.items:
            cogs += item.quantity * (item.product.cost_price if item.product else 0)
    cogs = round(cogs, 2)

    # ── Expenses ──────────────────────────────────────────────────────────
    expenses = Expense.query.filter(
        Expense.status == 'approved',
        Expense.expense_date >= start, Expense.expense_date <= end_bound
    ).all()
    total_expenses = round(sum(e.amount for e in expenses), 2)
    expenses_by_category = {}
    for e in expenses:
        expenses_by_category[e.category] = expenses_by_category.get(e.category, 0) + e.amount
    expenses_by_category = sorted(
        [(k, round(v, 2)) for k, v in expenses_by_category.items()], key=lambda x: -x[1]
    )

    net_profit = round(net_revenue - cogs - total_expenses, 2)

    # ── Collections by payment method (money actually received this period,
    # excluding voided payments) ────────────────────────────────────────
    payments = Payment.query.filter(
        Payment.status != 'void',
        Payment.payment_date >= start, Payment.payment_date <= end_bound
    ).all()
    total_collected = round(sum(p.amount for p in payments), 2)
    by_method = {}
    for p in payments:
        by_method[p.payment_method] = by_method.get(p.payment_method, 0) + p.amount
    by_method = sorted([(k, round(v, 2)) for k, v in by_method.items()], key=lambda x: -x[1])

    # ── Cash position: cash a rep has collected but not yet handed to a
    # cashier (pending declarations) vs cash already verified by a cashier ──
    pending_cash = round(db.session.query(func.sum(CashDeclaration.declared_amount)).filter(
        CashDeclaration.status == 'pending'
    ).scalar() or 0, 2)
    verified_cash = round(db.session.query(func.sum(CashDeclaration.counted_amount)).filter(
        CashDeclaration.status == 'verified',
        CashDeclaration.verified_at >= start, CashDeclaration.verified_at <= end_bound
    ).scalar() or 0, 2)

    # ── Receivables & payables (whole-book position, not period-scoped —
    # a customer's outstanding balance isn't bounded by the date filter) ──
    total_receivables = round(db.session.query(func.sum(Customer.outstanding_balance)).scalar() or 0, 2)
    total_payables = round(db.session.query(func.sum(Supplier.outstanding_balance)).filter(
        Supplier.status == 'active'
    ).scalar() or 0, 2)

    # ── 6-month revenue vs expenses trend ────────────────────────────────
    trend_labels, trend_revenue, trend_expenses = _monthly_trend()

    return render_template('finance/index.html',
        start=start, end=end,
        gross_revenue=gross_revenue, total_credits=total_credits, net_revenue=net_revenue,
        cogs=cogs, total_expenses=total_expenses, expenses_by_category=expenses_by_category,
        net_profit=net_profit, total_collected=total_collected, by_method=by_method,
        pending_cash=pending_cash, verified_cash=verified_cash,
        total_receivables=total_receivables, total_payables=total_payables,
        trend_labels=trend_labels, trend_revenue=trend_revenue, trend_expenses=trend_expenses,
    )


def _monthly_trend(months=6):
    """Last `months` calendar months of net revenue vs approved expenses,
    oldest first — gives the dashboard a shape over time instead of just a
    single period snapshot."""
    today = datetime.utcnow().date()
    month_starts = []
    y, m = today.year, today.month
    for _ in range(months):
        month_starts.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    month_starts.reverse()

    labels, revenue_vals, expense_vals = [], [], []
    for y, m in month_starts:
        m_start = datetime(y, m, 1)
        m_end = datetime(y + 1, 1, 1) if m == 12 else datetime(y, m + 1, 1)

        rev = db.session.query(func.sum(Sale.company_sales_total)).filter(
            Sale.status == 'completed', Sale.sale_date >= m_start, Sale.sale_date < m_end
        ).scalar() or 0
        exp = db.session.query(func.sum(Expense.amount)).filter(
            Expense.status == 'approved', Expense.expense_date >= m_start, Expense.expense_date < m_end
        ).scalar() or 0

        labels.append(m_start.strftime('%b %Y'))
        revenue_vals.append(round(rev, 2))
        expense_vals.append(round(exp, 2))

    return labels, revenue_vals, expense_vals
