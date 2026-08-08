"""Shared return-aware COGS calculation for P&L-style reports.

Revenue already nets out returns via the applied CreditNote (see
routes/finance.py and routes/reports.py's `total_credits`), but COGS was
being computed from every sale's original items with zero awareness of
returns — so a fully-returned sale still charged its full original cost,
even though the goods physically went back into stock (routes/returns.py
calls services/stock.py's log_stock_movement after crediting
Product.stock_quantity). That turned a should-be-neutral sale+return into
an apparent loss equal to the goods' cost. Nets by product_id per sale,
same matching approach as routes/dashboard.py's _net_company_sales(), since
ReturnOrderItem.sale_item_id isn't reliably wired through from the
return-creation form. Counts BOTH refund methods (cash and credit) — the
goods come back into stock either way, so COGS relief isn't conditional on
refund_method the way cash-refund Payment bookkeeping is elsewhere.
"""


def net_cogs_by_sale(sales):
    """Return {sale_id: cost-of-goods actually retained} for the given
    Sale objects, i.e. each sale's original COGS minus the cost-price value
    of anything approved-returned from it (floored at 0 per sale)."""
    from models.returns import ReturnOrder
    sale_ids = [s.id for s in sales]
    returned_by_sale = {}
    if sale_ids:
        for order in ReturnOrder.query.filter(ReturnOrder.sale_id.in_(sale_ids)).all():
            by_product = returned_by_sale.setdefault(order.sale_id, {})
            for item in order.items:
                if item.line_status == 'approved':
                    by_product[item.product_id] = by_product.get(item.product_id, 0) + item.quantity

    result = {}
    for s in sales:
        cost_by_product = {}
        sale_cogs = 0.0
        for i in s.items:
            cost = i.product.cost_price if i.product else 0
            cost_by_product[i.product_id] = cost
            sale_cogs += i.quantity * cost

        by_product = returned_by_sale.get(s.id)
        returned_cost = 0.0
        if by_product:
            returned_cost = sum(cost_by_product.get(pid, 0) * qty for pid, qty in by_product.items())

        result[s.id] = round(max(0.0, sale_cogs - returned_cost), 2)
    return result
