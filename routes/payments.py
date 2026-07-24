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

        amount = round(min(amount, sale.balance_due), 2)

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
        # clamp the new amount against that.
        new_amount = round(min(requested_amount, sale.balance_due), 2) if sale else round(requested_amount, 2)
        if new_amount <= 0:
            db.session.rollback()
            flash('Enter a valid payment amount.', 'danger')
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

    return render_template('payments/edit.html', payment=payment, sale=sale)


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

    # Same reverse used by edit() — a void is just "reverse and never reapply".
    sale = Sale.query.get(payment.sale_id) if payment.sale_id else None
    if sale:
        sale.amount_paid -= payment.amount
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
    return jsonify([s.to_dict() for s in sales])
