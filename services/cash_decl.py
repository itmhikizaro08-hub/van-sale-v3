"""Rep cash liability calculation — collected minus declared, running balance.

Collected/Declared reset to the current calendar month for the headline
figures (so reps and cashiers see "this month's" activity, not a
years-long running total). The Balance never resets — money a rep still
owes doesn't disappear just because the month rolled over.
"""
from datetime import datetime, timedelta
from app import db
from sqlalchemy import func
from models.payment import Payment
from models.cash_declaration import CashDeclaration


def _month_start(dt=None):
    dt = dt or datetime.utcnow()
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def rep_cash_balance(rep_id):
    month_start = _month_start()

    collected_month = db.session.query(func.sum(Payment.amount)).filter(
        Payment.received_by_id == rep_id, Payment.payment_method == 'cash',
        Payment.payment_date >= month_start, Payment.status != 'void'
    ).scalar() or 0
    declared_month = db.session.query(func.sum(CashDeclaration.declared_amount)).filter(
        CashDeclaration.sales_rep_id == rep_id,
        CashDeclaration.created_at >= month_start
    ).scalar() or 0

    collected_all = db.session.query(func.sum(Payment.amount)).filter(
        Payment.received_by_id == rep_id, Payment.payment_method == 'cash',
        Payment.status != 'void'
    ).scalar() or 0
    declared_all = db.session.query(func.sum(CashDeclaration.declared_amount)).filter(
        CashDeclaration.sales_rep_id == rep_id
    ).scalar() or 0

    return {
        'collected': round(collected_month, 2),
        'declared': round(declared_month, 2),
        'balance': round(collected_all - declared_all, 2)
    }


def rep_cash_summary_range(rep_id, start, end):
    """Collected/Declared/Verified for an arbitrary date range (statement periods,
    not tied to a calendar month like rep_cash_balance())."""
    end_bound = end + ' 23:59:59'

    collected = db.session.query(func.sum(Payment.amount)).filter(
        Payment.received_by_id == rep_id, Payment.payment_method == 'cash',
        Payment.payment_date >= start, Payment.payment_date <= end_bound,
        Payment.status != 'void'
    ).scalar() or 0
    declared = db.session.query(func.sum(CashDeclaration.declared_amount)).filter(
        CashDeclaration.sales_rep_id == rep_id,
        CashDeclaration.created_at >= start, CashDeclaration.created_at <= end_bound
    ).scalar() or 0
    verified = db.session.query(func.sum(CashDeclaration.counted_amount)).filter(
        CashDeclaration.sales_rep_id == rep_id, CashDeclaration.status == 'verified',
        CashDeclaration.created_at >= start, CashDeclaration.created_at <= end_bound
    ).scalar() or 0

    return {
        'collected': round(collected, 2),
        'declared': round(declared, 2),
        'verified': round(verified, 2),
    }


def rep_cash_monthly_history(rep_id, months=6):
    """Collected/Declared/Net per calendar month for the last `months` months, most recent first."""
    rows = []
    cursor = _month_start()
    for _ in range(months):
        next_month = _month_start(cursor.replace(day=28) + timedelta(days=4))

        collected = db.session.query(func.sum(Payment.amount)).filter(
            Payment.received_by_id == rep_id, Payment.payment_method == 'cash',
            Payment.payment_date >= cursor, Payment.payment_date < next_month,
            Payment.status != 'void'
        ).scalar() or 0
        declared = db.session.query(func.sum(CashDeclaration.declared_amount)).filter(
            CashDeclaration.sales_rep_id == rep_id,
            CashDeclaration.created_at >= cursor, CashDeclaration.created_at < next_month
        ).scalar() or 0

        rows.append({
            'month': cursor.strftime('%B %Y'),
            'collected': round(collected, 2),
            'declared': round(declared, 2),
            'net': round(collected - declared, 2)
        })
        cursor = _month_start(cursor - timedelta(days=1))
    return rows
