from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from app import db
from services.sequence import next_debit_note_number

notes_bp = Blueprint('notes', __name__)


def _models():
    try:
        from models.notes import CreditNote, DebitNote
        return CreditNote, DebitNote
    except ImportError:
        return None, None


@notes_bp.route('/')
@login_required
def index():
    if not current_user.can_access('notes'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    start = request.args.get('start', (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end   = request.args.get('end',   datetime.utcnow().strftime('%Y-%m-%d'))

    CreditNote, DebitNote = _models()
    credit_notes = CreditNote.query.filter(
        CreditNote.created_at >= start, CreditNote.created_at <= end + ' 23:59:59'
    ).order_by(CreditNote.created_at.desc()).limit(200).all() if CreditNote else []
    debit_notes = DebitNote.query.filter(
        DebitNote.created_at >= start, DebitNote.created_at <= end + ' 23:59:59'
    ).order_by(DebitNote.created_at.desc()).limit(200).all() if DebitNote else []

    total_credit = round(sum(n.amount for n in credit_notes if n.status != 'void'), 2)
    total_debit = round(sum(n.amount for n in debit_notes if n.status != 'void'), 2)

    return render_template('notes/index.html', credit_notes=credit_notes, debit_notes=debit_notes,
        total_credit=total_credit, total_debit=total_debit, start=start, end=end)


@notes_bp.route('/debit/new', methods=['GET', 'POST'])
@login_required
def new_debit():
    if not current_user.can_write('notes'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('notes.index'))
    _, DebitNote = _models()
    from models.customer import Customer
    customers = Customer.query.filter_by(status='active').order_by(Customer.name).all()

    if request.method == 'POST':
        customer_id = request.form.get('customer_id')
        amount = float(request.form.get('amount') or 0)
        if not customer_id or amount <= 0:
            flash('Customer and a positive amount are required.', 'danger')
            return redirect(url_for('notes.new_debit'))

        note = DebitNote(
            note_number=next_debit_note_number(),
            customer_id=customer_id,
            amount=amount,
            reason=request.form.get('reason'),
            reference_note=request.form.get('reference_note'),
            created_by_id=current_user.id
        )
        db.session.add(note)
        customer = Customer.query.get(customer_id)
        if customer:
            customer.outstanding_balance += amount
        db.session.commit()
        flash(f'Debit note {note.note_number} created.', 'success')
        return redirect(url_for('notes.index'))

    return render_template('notes/new_debit.html', customers=customers)


@notes_bp.route('/<string:kind>/<int:note_id>/void', methods=['POST'])
@login_required
def void_note(kind, note_id):
    if not current_user.can_approve_module('notes'):
        return jsonify({'error': 'Permission denied'}), 403
    CreditNote, DebitNote = _models()

    if kind == 'credit':
        note = CreditNote.query.get_or_404(note_id)
        if note.status == 'void':
            return jsonify({'error': 'Already void'}), 400
        # A credit note only ever reduced outstanding_balance if it was
        # refunded 'as credit' (routes/returns.py) — a cash-refunded return's
        # note never touched the balance, so reversing it here would inflate
        # what the customer owes by an amount that was never subtracted.
        was_credit_refund = note.return_order and note.return_order.refund_method == 'credit'
        if note.status == 'applied' and note.customer and was_credit_refund:
            note.customer.outstanding_balance += note.amount
        note.status = 'void'
    elif kind == 'debit':
        note = DebitNote.query.get_or_404(note_id)
        if note.status == 'void':
            return jsonify({'error': 'Already void'}), 400
        if note.customer:
            note.customer.outstanding_balance = max(0, note.customer.outstanding_balance - note.amount)
        note.status = 'void'
    else:
        return jsonify({'error': 'Unknown note type'}), 400

    db.session.commit()
    return jsonify({'success': True})
