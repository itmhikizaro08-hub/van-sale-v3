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
from models.inventory import InventoryMovement
from models.supplier import SupplierPayment


def van_stock_ledger_rows(van_id, rep_id, start, end, product_id=None):
    """Every event that moved a specific rep's custody of a specific van,
    across the four places that mutate VanStock (routes/vans.py loading_new/
    offload_confirm, routes/sales.py create, routes/returns.py approvals).
    Unlike customer/supplier statements, this has no single running balance
    to reconcile against — a van holds many different products at once, so
    a single number would be meaningless. Returns a flat, dated ledger
    instead; the caller pairs it with the live VanStock snapshot for the
    current per-product totals.

    `product_id`, when given, narrows the ledger to just that product —
    used by the Van Stock page's per-row "this item's movement" link,
    distinct from the "all items" statement link."""
    end_bound = end + ' 23:59:59'
    events = []

    from models.van_management import LoadingSheet, LoadingSheetItem, StockOffload, StockOffloadItem
    from models.sale import SaleItem

    sheets = LoadingSheet.query.filter_by(van_id=van_id, sales_rep_id=rep_id).all()
    for sheet in sheets:
        dt = sheet.created_at.strftime('%Y-%m-%d %H:%M:%S') if sheet.created_at else ''
        for item in sheet.items:
            if product_id and item.product_id != product_id:
                continue
            name = item.product.product_name if item.product else 'item'
            events.append((dt, 'Loaded', name, item.quantity, f'Loading Sheet {sheet.sheet_number}'))

    offloads = StockOffload.query.filter_by(sales_rep_id=rep_id, van_id=van_id).filter(
        StockOffload.status != 'pending'
    ).all()
    for offload in offloads:
        dt = offload.confirmed_at.strftime('%Y-%m-%d %H:%M:%S') if offload.confirmed_at else \
             (offload.created_at.strftime('%Y-%m-%d %H:%M:%S') if offload.created_at else '')
        for item in offload.items:
            if product_id and item.product_id != product_id:
                continue
            received = item.quantity_received or 0
            if received <= 0:
                continue
            name = item.product.product_name if item.product else 'item'
            events.append((dt, 'Offloaded', name, -received, f'Offload {offload.offload_number}'))

    sales = Sale.query.filter_by(van_id=van_id, sales_rep_id=rep_id, status='completed').all()
    for s in sales:
        dt = s.sale_date.strftime('%Y-%m-%d %H:%M:%S') if s.sale_date else ''
        for item in s.items:
            if product_id and item.product_id != product_id:
                continue
            name = item.product.product_name if item.product else 'item'
            events.append((dt, 'Sold', name, -item.quantity, f'Invoice {s.invoice_number}'))

    from models.returns import ReturnOrder
    orders = ReturnOrder.query.filter_by(
        van_id=van_id, received_by_rep_id=rep_id, return_destination='van_stock'
    ).all()
    for order in orders:
        dt = order.approved_at.strftime('%Y-%m-%d %H:%M:%S') if order.approved_at else \
             (order.created_at.strftime('%Y-%m-%d %H:%M:%S') if order.created_at else '')
        for item in order.items:
            if item.line_status != 'approved':
                continue
            if product_id and item.product_id != product_id:
                continue
            name = item.product.product_name if item.product else 'item'
            events.append((dt, 'Returned', name, item.quantity, f'Return {order.return_number}'))

    events = [e for e in events if e[0] and start <= e[0] <= end_bound]
    events.sort(key=lambda e: e[0], reverse=True)
    return [{'date': dt, 'type': t, 'product': name, 'qty': qty, 'reference': ref}
            for dt, t, name, qty, ref in events]


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

    from models.notes import DebitNote, CreditNote
    from models.returns import ReturnOrder
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

    # An approved supplier-return line reduces outstanding_balance the same
    # way a payment does (routes/returns.py's _supplier_bulk_resolve /
    # supplier_approve_line) - only approved lines ever touched the balance,
    # so pending/rejected lines are excluded here too.
    from models.supplier_return import SupplierReturn
    returns = SupplierReturn.query.filter(SupplierReturn.supplier_id == supplier.id).all()
    for r in returns:
        dt = r.approved_at.strftime('%Y-%m-%d %H:%M:%S') if r.approved_at else \
             (r.created_at.strftime('%Y-%m-%d %H:%M:%S') if r.created_at else '')
        for item in r.items:
            if item.line_status != 'approved':
                continue
            name = item.product.product_name if item.product else 'item'
            events.append((dt, f'Return {r.return_number} — {name} x{item.quantity}', 0.0, round(item.line_total or 0, 2)))

    return _running_balance(events, start, end_bound)
