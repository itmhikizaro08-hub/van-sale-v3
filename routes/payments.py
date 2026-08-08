"""Payments blueprint"""
import threading
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from app import db
from models.payment import Payment
from models.sale import Sale
from models.customer import Customer
from models.supplier import SupplierPayment
from services.sequence import next_payment_number
from services.sms_service import send_payment_sms

payments_bp = Blueprint('payments', __name__)

# Serializes concurrent payment submissions against the same sale, so a
# double-click that fires two near-simultaneous requests can't both pass
# the duplicate check before either has committed.
_sale_locks = {}
_sale_locks_guard = threading.Lock()


def _lock_for_sale(sale_id):
    with _sale_locks_guard:
        return _sale_locks.setdefault(sale_id, threading.Lock())


@payments_bp.route('/')
@login_required
def index():
    if not current_user.can_access('payments'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    start = request.args.get('start', (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end   = request.args.get('end',   datetime.utcnow().strftime('%Y-%m-%d'))

    q = Payment.query.filter(
        Payment.payment_date >= start,
        Payment.payment_date <= end + ' 23:59:59'
    )
    if current_user.scope('payments') == 'own':
        q = q.filter_by(received_by_id=current_user.id)
    payments = q.order_by(Payment.payment_date.desc()).limit(200).all()

    # A voided payment never actually collected money — don't count it.
    total_collected = round(sum(p.amount for p in payments if p.status != 'void'), 2)

    # Money we pay OUT to suppliers is a separate ledger direction — only
    # meaningful to roles with full visibility, not a rep's "own" scope.
    supplier_payments = []
    total_paid_out = 0.0
    pending_approval_count = 0
    if current_user.scope('payments') != 'own':
        supplier_payments = SupplierPayment.query.filter(
            SupplierPayment.payment_date >= start,
            SupplierPayment.payment_date <= end + ' 23:59:59'
        ).order_by(SupplierPayment.payment_date.desc()).limit(200).all()
        # Only money that's actually left the business counts toward "paid out" —
        # a pending proposal hasn't reduced the supplier's balance yet.
        total_paid_out = round(sum(p.amount for p in supplier_payments if p.status == 'approved'), 2)
        pending_approval_count = sum(1 for p in supplier_payments if p.status == 'pending')

    net_cash_flow = round(total_collected - total_paid_out, 2)

    return render_template('payments/index.html', payments=payments, start=start, end=end,
        total_collected=total_collected, supplier_payments=supplier_payments,
        total_paid_out=total_paid_out, net_cash_flow=net_cash_flow,
        pending_approval_count=pending_approval_count)


@payments_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    customers = Customer.query.filter_by(status='active').order_by(Customer.name).all()
    if request.method == 'POST':
        sale_id = request.form.get('sale_id', type=int)
        customer_id = request.form.get('customer_id', type=int)
        try:
            amount = float(request.form.get('amount') or 0)
        except ValueError:
            flash('Enter a valid payment amount.', 'danger')
            return redirect(url_for('payments.add', customer_id=customer_id, sale_id=sale_id))
        method = request.form.get('payment_method', 'cash')
        reference = request.form.get('reference_number')

        customer = Customer.query.get(customer_id)
        if not customer:
            flash('Customer not found.', 'danger')
            return redirect(url_for('payments.add'))

        # Every payment must be applied to a specific invoice — Payment.sale_id
        # is a required column, so without this check every submission would
        # crash with a NOT NULL constraint error.
        sale = Sale.query.get(sale_id) if sale_id else None
        if not sale or sale.customer_id != customer.id:
            flash('Select which invoice this payment applies to.', 'danger')
            return redirect(url_for('payments.add', customer_id=customer.id))

        if amount <= 0:
            flash('Enter a valid payment amount.', 'danger')
            return redirect(url_for('payments.add', customer_id=customer.id, sale_id=sale.id))

        # Cap at the NET balance (raw balance_due minus applied credit
        # notes — see routes/invoices.py's _net_balances()), not the raw
        # column. sale.balance_due alone doesn't know about a return, so
        # capping at it would let a cashier collect real cash for an
        # invoice a credit note has already partly or fully settled.
        from routes.invoices import _net_balances
        net_balance_due = _net_balances([sale])[sale.id]['net_balance_due']
        if net_balance_due <= 0:
            flash(f'{sale.invoice_number} has no balance left to collect — '
                  f'it\'s already fully covered by a credit note.', 'warning')
            return redirect(url_for('payments.add', customer_id=customer.id, sale_id=sale.id))
        amount = round(min(amount, net_balance_due), 2)

        # Guard against an accidental double-save — a double-click on the
        # submit button, or the browser resubmitting the form via the back
        # button, would otherwise record the same payment twice. The lock
        # serializes concurrent requests for this sale so the duplicate
        # check below always sees the other request's committed payment
        # instead of racing it.
        with _lock_for_sale(sale.id):
            recent_cutoff = datetime.utcnow() - timedelta(seconds=20)
            duplicate = Payment.query.filter(
                Payment.sale_id == sale.id,
                Payment.amount == amount,
                Payment.received_by_id == current_user.id,
                Payment.status != 'void',
                Payment.created_at >= recent_cutoff
            ).first()
            if duplicate:
                flash(f'This payment was already recorded as {duplicate.payment_number}.', 'warning')
                return redirect(url_for('payments.index'))

            payment = Payment(
                payment_number=next_payment_number(),
                sale_id=sale.id,
                customer_id=customer.id,
                amount=amount,
                payment_method=method,
                reference_number=reference,
                reference_note=request.form.get('reference_note'),
                notes=request.form.get('notes'),
                received_by_id=current_user.id
            )
            db.session.add(payment)

            sale.amount_paid += amount
            sale.recalculate()

            # Update customer balance
            customer.outstanding_balance = max(0, customer.outstanding_balance - amount)

            # Collecting a payment in the field implies the rep visited this
            # customer today — auto-record it, same as a completed sale does.
            if current_user.role == 'sales_rep':
                from services.visits import record_auto_visit
                record_auto_visit(customer.id, current_user.id, 'payment_collected')

            db.session.commit()

        try:
            send_payment_sms(customer, payment, sale)
        except Exception:
            pass

        flash(f'Payment of GHS {amount:.2f} recorded against {sale.invoice_number}!', 'success')
        return redirect(url_for('payments.index'))

    preselect_sale_id = request.args.get('sale_id', type=int)
    preselect_customer_id = request.args.get('customer_id', type=int)
    return render_template('payments/add.html', customers=customers,
        preselect_sale_id=preselect_sale_id, preselect_customer_id=preselect_customer_id)


@payments_bp.route('/<int:payment_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(payment_id):
    if not current_user.can_write('payments'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('payments.index'))

    payment = Payment.query.get_or_404(payment_id)

    if current_user.scope('payments') == 'own' and payment.received_by_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('payments.index'))

    if payment.status == 'void':
        flash('This payment has been voided and can no longer be edited.', 'warning')
        return redirect(url_for('payments.index'))

    # A negative amount means this Payment IS a cash refund (routes/returns.py's
    # _record_cash_refund), which never touched sale.amount_paid or the
    # customer's balance when created — the reverse-then-reapply math below
    # assumes a normal positive collection and would corrupt both if applied
    # to a refund. Void it and let the return flow create a fresh, correct
    # refund instead of trying to edit this one's amount.
    if payment.amount < 0:
        flash('This is a cash-refund payment, not a collection — void it instead of editing it.', 'warning')
        return redirect(url_for('payments.index'))

    sale = Sale.query.get(payment.sale_id) if payment.sale_id else None

    if request.method == 'POST':
        try:
            requested_amount = float(request.form.get('amount') or 0)
        except ValueError:
            flash('Enter a valid payment amount.', 'danger')
            return redirect(url_for('payments.edit', payment_id=payment.id))
        if requested_amount <= 0:
            flash('Enter a valid payment amount.', 'danger')
            return redirect(url_for('payments.edit', payment_id=payment.id))

        old_amount = payment.amount

        # Reverse this payment's old effect before reapplying the new amount,
        # same reverse-then-reapply approach used when a sale is cancelled —
        # otherwise editing the amount would double-count or under-count
        # against sale.balance_due / customer.outstanding_balance.
        if sale:
            sale.amount_paid -= old_amount
            sale.recalculate()
        payment.customer.outstanding_balance += old_amount

        # balance_due now reflects "as if this payment never happened" —
        # clamp the new amount against the NET balance (minus applied
        # credit notes — see routes/invoices.py's _net_balances()), not
        # the raw column, for the same reason as add() above.
        if sale:
            from routes.invoices import _net_balances
            net_balance_due = _net_balances([sale])[sale.id]['net_balance_due']
            new_amount = round(min(requested_amount, net_balance_due), 2)
        else:
            new_amount = round(requested_amount, 2)
        if new_amount <= 0:
            db.session.rollback()
            flash('Enter a valid payment amount.', 'danger')
            return redirect(url_for('payments.edit', payment_id=payment.id))

        # A return can have already cash-refunded real money out of what this
        # payment covered (see routes/returns.py's _cash_refundable_available).
        # Dropping the payment low enough to undercut that would leave the
        # books showing less was ever paid than was already handed back in
        # cash — an impossible state. sale.amount_paid at this point is
        # already net of the reversal above, so + new_amount previews the
        # final value before it's actually applied.
        if sale:
            from routes.returns import _cash_already_refunded
            already_refunded = _cash_already_refunded(sale)
            prospective_paid = round(sale.amount_paid + new_amount, 2)
            if prospective_paid < already_refunded:
                db.session.rollback()
                flash(f'Cannot reduce this payment to GHS {new_amount:.2f} — GHS {already_refunded:.2f} has '
                      f'already been cash-refunded against this sale via a return. Void the related return\'s '
                      f'cash refund first, or keep this payment high enough to cover it.', 'danger')
                return redirect(url_for('payments.edit', payment_id=payment.id))

        payment.amount = new_amount
        payment.payment_method = request.form.get('payment_method', payment.payment_method)
        payment.reference_number = request.form.get('reference_number')
        payment.reference_note = request.form.get('reference_note')
        payment.notes = request.form.get('notes')

        if sale:
            sale.amount_paid += new_amount
            sale.recalculate()
        payment.customer.outstanding_balance = max(0, payment.customer.outstanding_balance - new_amount)

        db.session.commit()
        flash(f'Payment {payment.payment_number} updated: GHS {old_amount:.2f} → GHS {new_amount:.2f}.', 'success')
        return redirect(url_for('payments.index'))

    # "As if this payment never happened" balance, net of applied credit
    # notes — see add()'s comment above. Shown on the form so the hint
    # doesn't overstate what's actually still owed.
    net_balance_before = None
    if sale:
        from routes.invoices import _net_balances
        credit_total = _net_balances([sale])[sale.id]['credit_total']
        net_balance_before = round(max(0, (sale.balance_due + payment.amount) - credit_total), 2)

    return render_template('payments/edit.html', payment=payment, sale=sale,
        net_balance_before=net_balance_before)


@payments_bp.route('/<int:payment_id>/void', methods=['POST'])
@login_required
def void(payment_id):
    if not current_user.can_write('payments'):
        return jsonify({'error': 'Permission denied'}), 403

    payment = Payment.query.get_or_404(payment_id)

    if current_user.scope('payments') == 'own' and payment.received_by_id != current_user.id:
        return jsonify({'error': 'Permission denied'}), 403

    if payment.status == 'void':
        return jsonify({'error': 'Already voided'}), 400

    # A negative amount means this Payment IS a cash refund (routes/returns.py's
    # _record_cash_refund) — those deliberately never touch sale.amount_paid or
    # customer.outstanding_balance when created (the refund is tracked purely
    # for rep cash-on-hand reconciliation), so voiding one must not touch them
    # either. Applying the normal reverse math here would actually SUBTRACT a
    # negative number and inflate amount_paid, plus wrongly shrink the
    # customer's balance for money that was never added to it in the first
    # place. Voiding a refund payment is exactly how routes/returns.py's
    # _cash_already_refunded() expects a refund to be undone — no separate
    # guard needed, since freeing up refund room can never itself create an
    # inconsistency the way reducing a real collection can.
    sale = Sale.query.get(payment.sale_id) if payment.sale_id else None
    if payment.amount >= 0:
        if sale:
            # A return can have already cash-refunded real money out of what
            # this payment covered (see routes/returns.py's
            # _cash_refundable_available). Voiding this payment anyway would
            # leave the books showing less was ever paid than was already
            # handed back in cash — an impossible state — so block it until
            # the related cash refund is undone first.
            from routes.returns import _cash_already_refunded
            already_refunded = _cash_already_refunded(sale)
            prospective_paid = round(sale.amount_paid - payment.amount, 2)
            if prospective_paid < already_refunded:
                return jsonify({'error': f'Cannot void this payment — GHS {already_refunded:.2f} has already been '
                                          f'cash-refunded against this sale via a return, more than the GHS '
                                          f'{prospective_paid:.2f} that would remain paid. Void the related '
                                          f'return\'s cash refund first.'}), 400
            sale.amount_paid = prospective_paid
            sale.recalculate()
        payment.customer.outstanding_balance += payment.amount

    payment.status = 'void'
    payment.voided_by_id = current_user.id
    payment.voided_at = datetime.utcnow()
    db.session.commit()

    return jsonify({'success': True})


@payments_bp.route('/<int:payment_id>/delete', methods=['POST'])
@login_required
def delete(payment_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    payment = Payment.query.get_or_404(payment_id)

    # A live 'completed' payment still represents real collected money — voiding
    # it (which reverses the balance) is the correct action, not deletion.
    # Deletion is only for purging a payment that's already been voided (no
    # remaining balance effect to lose track of), matching how this app never
    # hard-deletes a financial record while it's still "live" — customers,
    # suppliers, and products are all soft-deleted (status='inactive') too.
    if payment.status != 'void':
        return jsonify({'error': 'Void this payment first before deleting it.'}), 400

    db.session.delete(payment)
    db.session.commit()

    return jsonify({'success': True})


@payments_bp.route('/outstanding')
@login_required
def outstanding():
    if not current_user.can_access('payments'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    q = Customer.query.filter(Customer.outstanding_balance > 0)
    if current_user.scope('payments') == 'own':
        q = q.filter_by(sales_rep_id=current_user.id)
    customers = q.order_by(Customer.outstanding_balance.desc()).all()

    total_outstanding = round(sum(c.outstanding_balance for c in customers), 2)

    return render_template('payments/outstanding.html', customers=customers,
        total_outstanding=total_outstanding)


@payments_bp.route('/api/customer-sales/<int:customer_id>')
@login_required
def customer_sales(customer_id):
    sales = Sale.query.filter_by(customer_id=customer_id).filter(
        Sale.status == 'completed',
        Sale.payment_status.in_(['unpaid', 'partial'])
    ).all()

    # Net of applied credit notes — without this, an invoice a return has
    # already fully settled (raw payment_status still 'unpaid') would show
    # up here with its full original balance, letting a cashier collect
    # real cash for something the customer already got credited back.
    from routes.invoices import _net_balances
    net = _net_balances(sales)

    result = []
    for s in sales:
        n = net[s.id]
        if n['net_balance_due'] <= 0:
            continue  # fully covered by a credit note — nothing left to collect
        d = s.to_dict()
        d['balance_due'] = n['net_balance_due']
        d['payment_status'] = n['net_payment_status']
        result.append(d)
    return jsonify(result)
