"""Account statement (ledger) construction for customers and suppliers.

Both ledgers are built exclusively from the same events that mutate the
entity's `outstanding_balance` column elsewhere in the app, so the computed
closing balance for a range ending today always reconciles exactly to the
live `outstanding_balance` field. See routes/sales.py, routes/payments.py,
routes/notes.py, routes/returns.py (customer) and routes/inventory.py,
routes/suppliers.py (supplier) for the mutation call sites this mirrors.
"""
from models.sale import Sale
from models.payment import Payment
from models.notification import InventoryMovement, SupplierPayment


def _running_balance(events, start, end):
    """events: list of (date, description, debit, credit) tuples, unsorted.
    Returns (opening_balance, rows, closing_balance).

    Every real mutation of outstanding_balance elsewhere in the app clamps to
    a floor of 0 at that individual step (routes/payments.py:106,
    routes/returns.py:83,267, routes/suppliers.py:183,209) — an overpayment
    or over-credit doesn't carry forward as a negative/credit balance, it's
    simply discarded. The running balance here must apply that same floor at
    each step (not just at the end) or it will drift from the real balance
    field whenever the entity is ever credited past zero mid-history."""
    events.sort(key=lambda e: e[0])

    balance = 0.0
    for dt, _desc, debit, credit in events:
        if dt < start:
            balance = max(0.0, balance + debit - credit)
    opening_balance = balance

    rows = []
    for dt, desc, debit, credit in events:
        if dt < start or dt > end:
            continue
        balance = max(0.0, balance + debit - credit)
        rows.append({'date': dt, 'description': desc, 'debit': debit, 'credit': credit,
                      'balance': round(balance, 2)})

    return round(opening_balance, 2), rows, round(balance, 2)


def customer_statement_rows(customer, start, end):
    end_bound = end + ' 23:59:59'
    events = []

    sales = Sale.query.filter(
        Sale.customer_id == customer.id, Sale.status == 'completed'
    ).all()
    for s in sales:
        dt = s.sale_date.strftime('%Y-%m-%d %H:%M:%S') if s.sale_date else ''
        events.append((dt, f'Invoice {s.invoice_number}', round(s.total_amount or 0, 2), 0.0))

    # A cancelled sale's own creation debit is already excluded above (status
    # filter), and routes/sales.py:232 reverses that sale's balance_due at
    # cancel time — which nets its whole lifecycle to zero regardless of
    # payment timing. So any payment tied to a cancelled sale must also be
    # excluded here, or it would show as an uncancelled credit with nothing
    # offsetting it.
    payments = Payment.query.join(Sale, Payment.sale_id == Sale.id).filter(
        Payment.customer_id == customer.id, Sale.status != 'cancelled',
        Payment.status != 'void'
    ).all()
    for p in payments:
        dt = p.payment_date.strftime('%Y-%m-%d %H:%M:%S') if p.payment_date else ''
        events.append((dt, f'Payment {p.payment_number}', 0.0, round(p.amount or 0, 2)))

    from models.v4_models import DebitNote, CreditNote, ReturnOrder
    debit_notes = DebitNote.query.filter(
        DebitNote.customer_id == customer.id, DebitNote.status != 'void'
    ).all()
    for n in debit_notes:
        dt = n.created_at.strftime('%Y-%m-%d %H:%M:%S') if n.created_at else ''
        events.append((dt, f'Debit Note {n.note_number}', round(n.amount or 0, 2), 0.0))

    # Only credit notes tied to a return that was actually refunded 'as credit'
    # ever touched the balance (routes/returns.py:82-83) — summing every
    # non-void CreditNote would overcount cash-refunded returns.
    credit_notes = CreditNote.query.join(
        ReturnOrder, CreditNote.return_order_id == ReturnOrder.id
    ).filter(
        CreditNote.customer_id == customer.id,
        CreditNote.status != 'void',
        ReturnOrder.refund_method == 'credit',
    ).all()
    for n in credit_notes:
        dt = n.created_at.strftime('%Y-%m-%d %H:%M:%S') if n.created_at else ''
        events.append((dt, f'Credit Note {n.note_number}', 0.0, round(n.amount or 0, 2)))

    return _running_balance(events, start, end_bound)


def supplier_statement_rows(supplier, start, end):
    end_bound = end + ' 23:59:59'
    events = []

    deliveries = InventoryMovement.query.filter(
        InventoryMovement.supplier_id == supplier.id,
        InventoryMovement.movement_type == 'stock_in',
    ).all()
    for m in deliveries:
        dt = m.created_at.strftime('%Y-%m-%d %H:%M:%S') if m.created_at else ''
        value = round(m.quantity * (m.product.cost_price if m.product else 0), 2)
        name = m.product.product_name if m.product else 'item'
        events.append((dt, f'Stock In — {name} x{m.quantity}', value, 0.0))

    payments = SupplierPayment.query.filter(
        SupplierPayment.supplier_id == supplier.id, SupplierPayment.status == 'approved'
    ).all()
    for p in payments:
        dt = p.payment_date.strftime('%Y-%m-%d %H:%M:%S') if p.payment_date else ''
        events.append((dt, f'Payment {p.payment_number}', 0.0, round(p.amount or 0, 2)))

    return _running_balance(events, start, end_bound)
