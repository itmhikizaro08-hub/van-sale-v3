"""Suppliers blueprint"""
import threading
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from app import db
from models.notification import Supplier, InventoryMovement, SupplierPayment
from services.sequence import next_supplier_payment_number

suppliers_bp = Blueprint('suppliers', __name__)

# Serializes proposing/approving payments for the same supplier. Pending
# proposals don't touch outstanding_balance until approved, so two proposals
# made against the same (not-yet-reduced) balance can jointly exceed what's
# actually owed — the lock alone doesn't fix that logical gap (see the
# pending-total check in pay() and the re-clamp in approve_payment()), but it
# does stop two truly-simultaneous requests from both reading a stale balance.
_supplier_locks = {}
_supplier_locks_guard = threading.Lock()


def _lock_for_supplier(supplier_id):
    with _supplier_locks_guard:
        return _supplier_locks.setdefault(supplier_id, threading.Lock())


def _next_code():
    last = Supplier.query.order_by(Supplier.id.desc()).first()
    n = (last.id + 1) if last else 1
    return f'SUP{n:04d}'


@suppliers_bp.route('/')
@login_required
def index():
    if not current_user.can_access('suppliers'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    suppliers = Supplier.query.order_by(Supplier.name).all()
    total_outstanding = round(sum(s.outstanding_balance for s in suppliers), 2)
    active_count = sum(1 for s in suppliers if s.status == 'active')

    return render_template('suppliers/index.html', suppliers=suppliers,
        total_outstanding=total_outstanding, active_count=active_count)


@suppliers_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if not current_user.can_write('suppliers'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('suppliers.index'))

    if request.method == 'POST':
        name = request.form['name'].strip()
        existing = Supplier.query.filter(
            Supplier.status == 'active', db.func.lower(Supplier.name) == name.lower()
        ).first()
        if existing:
            flash(f'A supplier named "{name}" already exists ({existing.supplier_code}). '
                  f'Edit it instead, or use a different name.', 'warning')
            return redirect(url_for('suppliers.add'))

        s = Supplier(
            supplier_code=_next_code(),
            name=name,
            contact_person=request.form.get('contact_person'),
            phone=request.form.get('phone'),
            email=request.form.get('email'),
            address=request.form.get('address'),
            payment_terms=request.form.get('payment_terms'),
            notes=request.form.get('notes')
        )
        db.session.add(s)
        db.session.commit()
        flash(f'Supplier {s.name} added!', 'success')
        return redirect(url_for('suppliers.index'))
    return render_template('suppliers/form.html', supplier=None)


@suppliers_bp.route('/<int:supplier_id>')
@login_required
def view(supplier_id):
    if not current_user.can_access('suppliers'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    s = Supplier.query.get_or_404(supplier_id)

    start = request.args.get('start', (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end   = request.args.get('end',   datetime.utcnow().strftime('%Y-%m-%d'))

    deliveries = InventoryMovement.query.filter(
        InventoryMovement.supplier_id == supplier_id,
        InventoryMovement.movement_type == 'stock_in',
        InventoryMovement.created_at >= start,
        InventoryMovement.created_at <= end + ' 23:59:59'
    ).order_by(InventoryMovement.created_at.desc()).limit(200).all()
    payments = SupplierPayment.query.filter(
        SupplierPayment.supplier_id == supplier_id,
        SupplierPayment.payment_date >= start,
        SupplierPayment.payment_date <= end + ' 23:59:59'
    ).order_by(SupplierPayment.payment_date.desc()).limit(200).all()

    from models.supplier_return import SupplierReturn
    returns = SupplierReturn.query.filter(
        SupplierReturn.supplier_id == supplier_id,
        SupplierReturn.created_at >= start,
        SupplierReturn.created_at <= end + ' 23:59:59'
    ).order_by(SupplierReturn.created_at.desc()).limit(200).all()

    total_units = sum(m.quantity for m in deliveries)
    total_value = round(sum(
        m.quantity * (m.product.cost_price if m.product else 0) for m in deliveries
    ), 2)
    total_paid = round(sum(p.amount for p in payments if p.status == 'approved'), 2)
    pending_count = sum(1 for p in payments if p.status == 'pending')
    total_returned = round(sum(
        item.line_total for r in returns for item in r.items if item.line_status == 'approved'
    ), 2)

    # Deliveries sharing a reference_id came from the same batch submission —
    # group them into one row per delivery instead of one row per product line.
    batches = {}
    for m in deliveries:
        batch_ref = m.reference_id or m.id
        b = batches.setdefault(batch_ref, {
            'batch_ref': batch_ref, 'created_at': m.created_at,
            'reference_note': m.reference_note, 'item_count': 0,
            'total_qty': 0, 'total_value': 0.0,
        })
        b['item_count'] += 1
        b['total_qty'] += m.quantity
        b['total_value'] += m.quantity * (m.product.cost_price if m.product else 0)
    delivery_batches = sorted(batches.values(), key=lambda b: b['created_at'] or datetime.min, reverse=True)
    for b in delivery_batches:
        b['total_value'] = round(b['total_value'], 2)
    delivery_count = len(delivery_batches)

    return render_template('suppliers/view.html', supplier=s, deliveries=deliveries,
        delivery_batches=delivery_batches, payments=payments, returns=returns,
        total_units=total_units, total_value=total_value, total_paid=total_paid,
        total_returned=total_returned, pending_count=pending_count,
        delivery_count=delivery_count, start=start, end=end)


@suppliers_bp.route('/deliveries/<int:batch_ref>')
@login_required
def delivery_view(batch_ref):
    if not current_user.can_access('suppliers'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    items = InventoryMovement.query.filter(
        InventoryMovement.movement_type == 'stock_in',
        (InventoryMovement.reference_id == batch_ref) |
        ((InventoryMovement.reference_id.is_(None)) & (InventoryMovement.id == batch_ref))
    ).order_by(InventoryMovement.id).all()
    if not items:
        flash('Delivery not found.', 'danger')
        return redirect(url_for('suppliers.index'))

    supplier = items[0].supplier
    total_value = round(sum(m.quantity * (m.product.cost_price if m.product else 0) for m in items), 2)

    return render_template('suppliers/delivery_view.html', batch_ref=batch_ref,
        items=items, supplier=supplier, total_value=total_value)


@suppliers_bp.route('/<int:supplier_id>/statement')
@login_required
def statement(supplier_id):
    if not current_user.can_access('suppliers'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    s = Supplier.query.get_or_404(supplier_id)
    start = request.args.get('start', (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end   = request.args.get('end',   datetime.utcnow().strftime('%Y-%m-%d'))

    from services.statements import supplier_statement_rows
    opening_balance, rows, closing_balance = supplier_statement_rows(s, start, end)
    total_debit = round(sum(r['debit'] for r in rows), 2)
    total_credit = round(sum(r['credit'] for r in rows), 2)

    return render_template('suppliers/statement.html', supplier=s, start=start, end=end,
        opening_balance=opening_balance, rows=rows, closing_balance=closing_balance,
        total_debit=total_debit, total_credit=total_credit)


@suppliers_bp.route('/<int:supplier_id>/statement/pdf')
@login_required
def statement_pdf(supplier_id):
    if not current_user.can_access('suppliers'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    from flask import make_response
    s = Supplier.query.get_or_404(supplier_id)
    start = request.args.get('start', (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end   = request.args.get('end',   datetime.utcnow().strftime('%Y-%m-%d'))

    from services.statements import supplier_statement_rows
    from services.pdf_service import generate_statement_pdf
    from models.settings import Settings
    opening_balance, rows, closing_balance = supplier_statement_rows(s, start, end)

    settings = Settings.get()
    company = {'name': settings.company_name, 'address': settings.company_address,
               'phone': settings.company_phone, 'email': settings.company_email}
    entity = {'name': s.name, 'code': s.supplier_code, 'phone': s.phone, 'email': s.email}

    pdf_bytes = generate_statement_pdf('Supplier', entity, company, start, end,
                                        opening_balance, rows, closing_balance)
    response = make_response(pdf_bytes)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=statement_{s.supplier_code}_{start}_to_{end}.pdf'
    return response


@suppliers_bp.route('/<int:supplier_id>/pay', methods=['GET', 'POST'])
@login_required
def pay(supplier_id):
    if not current_user.can_write('suppliers'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('suppliers.view', supplier_id=supplier_id))

    s = Supplier.query.get_or_404(supplier_id)

    can_approve = current_user.can_approve_module('suppliers')

    if request.method == 'POST':
        amount = float(request.form.get('amount') or 0)
        if amount <= 0:
            flash('Enter a valid payment amount.', 'danger')
            return redirect(url_for('suppliers.pay', supplier_id=supplier_id))

        with _lock_for_supplier(s.id):
            # Pending proposals don't reduce outstanding_balance until
            # approved — clamping against outstanding_balance alone lets
            # two proposals each pass individually while jointly exceeding
            # what's actually owed. Subtract what's already pending too.
            pending_total = db.session.query(db.func.sum(SupplierPayment.amount)).filter(
                SupplierPayment.supplier_id == s.id, SupplierPayment.status == 'pending'
            ).scalar() or 0
            available = round(max(0, s.outstanding_balance - pending_total), 2)
            amount = round(min(amount, available), 2) if available > 0 else round(amount, 2)

            payment = SupplierPayment(
                payment_number=next_supplier_payment_number(),
                supplier_id=s.id,
                amount=amount,
                payment_method=request.form.get('payment_method', 'cash'),
                reference_number=request.form.get('reference_number'),
                reference_note=request.form.get('reference_note'),
                notes=request.form.get('notes'),
                paid_by_id=current_user.id,
                status='approved' if can_approve else 'pending'
            )
            db.session.add(payment)

            if can_approve:
                # Admin/manager pay directly — no separate approval step needed.
                payment.approved_by_id = current_user.id
                payment.approved_at = datetime.utcnow()
                s.outstanding_balance = round(max(0, s.outstanding_balance - amount), 2)
                db.session.commit()
                flash(f'Payment of GHS {amount:.2f} recorded to {s.name}.', 'success')
            else:
                # Cashier proposes — balance stays as-is until a manager/admin approves.
                db.session.commit()
                flash(f'Payment proposal of GHS {amount:.2f} to {s.name} submitted for approval.', 'info')

        return redirect(url_for('suppliers.view', supplier_id=supplier_id))

    return render_template('suppliers/pay.html', supplier=s, can_approve=can_approve)


@suppliers_bp.route('/payments/<int:payment_id>/approve', methods=['POST'])
@login_required
def approve_payment(payment_id):
    if not current_user.can_approve_module('suppliers'):
        return jsonify({'error': 'Permission denied'}), 403

    payment = SupplierPayment.query.get_or_404(payment_id)
    if payment.status != 'pending':
        return jsonify({'error': 'Already processed'}), 400

    with _lock_for_supplier(payment.supplier_id):
        supplier = payment.supplier
        # Re-check against the CURRENT balance, not just at proposal time —
        # an earlier-approved overlapping proposal (see pay()'s docstring)
        # can mean less is actually owed now than when this was proposed.
        # Clamp down and record what was truly approved rather than letting
        # the excess silently vanish with no overpayment/credit trail.
        original_amount = payment.amount
        approved_amount = round(min(original_amount, supplier.outstanding_balance), 2)

        payment.amount = approved_amount
        payment.status = 'approved'
        payment.approved_by_id = current_user.id
        payment.approved_at = datetime.utcnow()
        supplier.outstanding_balance = round(max(0, supplier.outstanding_balance - approved_amount), 2)
        db.session.commit()

    message = f'Payment of GHS {approved_amount:.2f} approved.'
    if approved_amount < original_amount:
        message = (f'Only GHS {approved_amount:.2f} of the proposed GHS {original_amount:.2f} was approved — '
                    f'the balance owed had already dropped below the proposed amount.')
    return jsonify({'success': True, 'message': message})


@suppliers_bp.route('/payments/<int:payment_id>/reject', methods=['POST'])
@login_required
def reject_payment(payment_id):
    if not current_user.can_approve_module('suppliers'):
        return jsonify({'error': 'Permission denied'}), 403

    payment = SupplierPayment.query.get_or_404(payment_id)
    if payment.status != 'pending':
        return jsonify({'error': 'Already processed'}), 400

    payment.status = 'rejected'
    payment.approved_by_id = current_user.id
    payment.approved_at = datetime.utcnow()
    db.session.commit()

    return jsonify({'success': True})


@suppliers_bp.route('/<int:supplier_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(supplier_id):
    if not current_user.can_write('suppliers'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('suppliers.index'))

    s = Supplier.query.get_or_404(supplier_id)
    if request.method == 'POST':
        name = request.form['name'].strip()
        existing = Supplier.query.filter(
            Supplier.id != s.id, Supplier.status == 'active',
            db.func.lower(Supplier.name) == name.lower()
        ).first()
        if existing:
            flash(f'A supplier named "{name}" already exists ({existing.supplier_code}).', 'warning')
            return redirect(url_for('suppliers.edit', supplier_id=s.id))

        s.name = name
        s.contact_person = request.form.get('contact_person')
        s.phone = request.form.get('phone')
        s.email = request.form.get('email')
        s.address = request.form.get('address')
        s.payment_terms = request.form.get('payment_terms')
        s.notes = request.form.get('notes')
        s.status = request.form.get('status', 'active')
        db.session.commit()
        flash('Supplier updated!', 'success')
        return redirect(url_for('suppliers.index'))
    return render_template('suppliers/form.html', supplier=s)


@suppliers_bp.route('/<int:supplier_id>/delete', methods=['POST'])
@login_required
def delete(supplier_id):
    if not current_user.can_write('suppliers'):
        return jsonify({'error': 'Permission denied'}), 403
    s = Supplier.query.get_or_404(supplier_id)
    s.status = 'inactive'
    db.session.commit()
    return jsonify({'success': True})
