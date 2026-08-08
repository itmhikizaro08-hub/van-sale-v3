"""Shared return-aware COGS calculation for P&L-style reports.

Revenue already nets out returns via the applied CreditNote (see
routes/finance.py and routes/reports.py's `total_credits`, keyed off
CreditNote.created_at falling within the report period), but COGS was
being computed from every completed sale's original items with zero
awareness of returns at all -- it never dropped when goods came back.

The relief must be keyed the SAME way revenue's reduction already is: by
when the return's CreditNote was created, not by when (or whether) the
original sale happened. routes/returns.py explicitly allows filing a
return without picking a specific sale at all (`sale_id=... or None`), and
even when a sale is picked it may fall in an earlier report period than
the return itself. Either way the return still brings real inventory back
into stock (see services/stock.py's log_stock_movement call sites) during
THIS period, so this period's COGS should get relief for it the same way
this period's revenue already does -- exactly mirroring standard
return-period accounting (a return this month reduces this month's
figures, regardless of which month the original sale was in).

One consequence: a period with unusually large/many returns relative to
its sales can legitimately push net COGS below the sales-only total, or
even negative -- more inventory value came back than went out that
period. That's a correct signal, not a bug; it isn't floored away here.
"""
from app import db


def returned_cogs_for_period(start, end_bound):
    """Total cost-price value of every approved-return line item belonging
    to a ReturnOrder whose CreditNote was applied within [start, end_bound]
    -- the same population routes/finance.py and routes/reports.py already
    sum for `total_credits`. Grouped by return order (a CreditNote is
    created per approved line item, all sharing one return_order_id), so
    this can slightly over- or under-count in the rare case where an
    order's lines were approved on different days straddling the period
    boundary -- an acceptable approximation, same spirit as the CURRENT-
    cost-price approximation already documented below for COGS generally.
    """
    from models.notes import CreditNote
    from models.returns import ReturnOrder

    order_ids = [row[0] for row in db.session.query(CreditNote.return_order_id).filter(
        CreditNote.status == 'applied',
        CreditNote.created_at >= start, CreditNote.created_at <= end_bound,
        CreditNote.return_order_id.isnot(None)
    ).distinct().all()]
    if not order_ids:
        return 0.0

    total = 0.0
    for order in ReturnOrder.query.filter(ReturnOrder.id.in_(order_ids)).all():
        for item in order.items:
            if item.line_status == 'approved':
                total += item.quantity * (item.product.cost_price if item.product else 0)
    return round(total, 2)


def net_cogs_for_period(sales, start, end_bound):
    """COGS for the period: full quantity x current-cost-price of every
    item across `sales` (the period's completed sales), minus
    returned_cogs_for_period()'s relief. Not floored at 0 -- see module
    docstring."""
    full_cogs = 0.0
    for s in sales:
        for item in s.items:
            full_cogs += item.quantity * (item.product.cost_price if item.product else 0)
    return round(full_cogs - returned_cogs_for_period(start, end_bound), 2)
