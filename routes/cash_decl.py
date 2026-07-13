"""
Cash Declarations
==================
- Sales Rep : declares cash collected during the day, broken down by
              denomination, and submits it to a cashier. Their outstanding
              balance (collected minus declared) drops the moment they submit.
- Cashier   : sees the queue of reps' balances and pending declarations,
              records what they actually counted, and verifies. A mismatch
              is flagged as a discrepancy but does not alter the rep's
              running balance — it's a separate reconciliation flag.
- Manager/Admin : full visibility, can also verify.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from app import db
from models.user import User
from models.cash_declaration import CashDeclaration, CashDeclarationLine, DENOMINATIONS
from services.cash_decl import rep_cash_balance, rep_cash_monthly_history
from services.rbac import require_module

cash_decl_bp = Blueprint('cash_decl', __name__)


def _next_declaration_number():
    last = CashDeclaration.query.order_by(CashDeclaration.id.desc()).first()
    n = (last.id + 1) if last else 1
    return f'CD-{n:05d}'


@cash_decl_bp.route('/')
@login_required
@require_module('cash_decl')
def index():
    start = request.args.get('start', (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end   = request.args.get('end',   datetime.utcnow().strftime('%Y-%m-%d'))

    if current_user.scope('cash_decl') == 'own':
        balance = rep_cash_balance(current_user.id)
        declarations = CashDeclaration.query.filter_by(
            sales_rep_id=current_user.id
        ).filter(
            CashDeclaration.created_at >= start,
            CashDeclaration.created_at <= end + ' 23:59:59'
        ).order_by(CashDeclaration.created_at.desc()).limit(200).all()
        return render_template('cash_decl/my_declarations.html',
            balance=balance, declarations=declarations, denominations=DENOMINATIONS,
            start=start, end=end)

    pending = CashDeclaration.query.filter_by(status='pending').order_by(
        CashDeclaration.created_at).all()
    reps = User.query.filter(User.role == 'sales_rep', User.is_active == True).order_by(User.full_name).all()
    balances = [
        {'rep': r, **rep_cash_balance(r.id), 'monthly': rep_cash_monthly_history(r.id)}
        for r in reps
    ]
    recent = CashDeclaration.query.filter(
        CashDeclaration.status != 'pending',
        CashDeclaration.created_at >= start,
        CashDeclaration.created_at <= end + ' 23:59:59'
    ).order_by(CashDeclaration.verified_at.desc()).limit(200).all()
    return render_template('cash_decl/queue.html',
        pending=pending, balances=balances, recent=recent,
        start=start, end=end)


@cash_decl_bp.route('/submit', methods=['POST'])
@login_required
@require_module('cash_decl', need_write=True)
def submit():
    lines_data = []
    total = 0.0
    for denom in DENOMINATIONS:
        key = f'denom_{str(denom).replace(".", "_")}'
        count = int(request.form.get(key) or 0)
        if count > 0:
            subtotal = round(denom * count, 2)
            lines_data.append((denom, count, subtotal))
            total += subtotal
    total = round(total, 2)

    if total <= 0:
        flash('Enter at least one denomination count.', 'warning')
        return redirect(url_for('cash_decl.index'))

    declaration = CashDeclaration(
        declaration_number=_next_declaration_number(),
        sales_rep_id=current_user.id,
        declared_amount=total,
        status='pending',
        notes=request.form.get('notes')
    )
    db.session.add(declaration)
    db.session.flush()
    for denom, count, subtotal in lines_data:
        db.session.add(CashDeclarationLine(
            declaration_id=declaration.id, denomination=denom, count=count, subtotal=subtotal))
    db.session.commit()
    flash(f'Cash declaration {declaration.declaration_number} submitted — GHS {total:.2f}', 'success')
    return redirect(url_for('cash_decl.index'))


@cash_decl_bp.route('/<int:decl_id>/verify', methods=['POST'])
@login_required
@require_module('cash_decl', need_approve=True)
def verify(decl_id):
    declaration = CashDeclaration.query.get_or_404(decl_id)
    counted = float(request.form.get('counted_amount') or 0)
    declaration.counted_amount = round(counted, 2)
    declaration.discrepancy_amount = round(counted - declaration.declared_amount, 2)
    declaration.status = 'verified' if abs(declaration.discrepancy_amount) < 0.01 else 'discrepancy'
    declaration.verified_by_id = current_user.id
    declaration.verified_at = datetime.utcnow()
    note = request.form.get('notes')
    if note:
        declaration.notes = (declaration.notes + '\n' if declaration.notes else '') + note
    db.session.commit()

    if declaration.status == 'discrepancy':
        flash(f'Declaration {declaration.declaration_number} verified with a discrepancy of '
              f'GHS {declaration.discrepancy_amount:.2f}.', 'warning')
    else:
        flash(f'Declaration {declaration.declaration_number} verified — matches.', 'success')
    return redirect(url_for('cash_decl.index'))
