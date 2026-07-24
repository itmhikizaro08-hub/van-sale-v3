"""Stock-offload business logic (van → warehouse).

Moved out of routes/vans.py's offload_submit()/offload_confirm() view
functions so the actual reconciliation math is discoverable/testable on its
own rather than inlined in a request handler. The routes still own request
parsing, flashing, and redirects — this module only does the domain logic.
"""
from flask_login import current_user
from app import db
from models.inventory import VanStock, InventoryMovement


def validate_offload_items(product_ids, quantities, sales_rep_id):
    """Validate and resolve a stock-offload submission's raw form lists into
    (product_id, quantity, van_id) tuples, checking each product's quantity
    against what the rep actually holds in VanStock.

    Returns (items_data, error_message) — error_message is None on success;
    when it's set, items_data is always [] and the caller should surface the
    message to the user without processing anything.
    """
    items_data = []
    for pid, qty_str in zip(product_ids, quantities):
        if not pid or not qty_str:
            continue
        try:
            qty = round(float(qty_str), 3)
        except ValueError:
            return [], f'"{qty_str}" is not a valid quantity.'
        if qty <= 0:
            continue
        vs = VanStock.query.filter_by(sales_rep_id=sales_rep_id, product_id=int(pid)).first()
        held = vs.quantity if vs else 0
        if qty > held:
            product_name = vs.product.product_name if vs and vs.product else 'a product'
            return [], f'Cannot offload {qty} of {product_name} — you only hold {held}.'
        items_data.append((int(pid), qty, vs.van_id))
    return items_data, None


def reconcile_offload_item(item, received_input, offload):
    """Process one StockOffload line: clamp the warehouse-confirmed received
    quantity to [0, declared], deduct it from the rep's VanStock, credit it
    back to warehouse Product.stock_quantity, and log the InventoryMovement.

    Call once per item, after item.offload has been set (i.e. item already
    belongs to `offload`). Returns True if the received amount fell short of
    what was declared (a mismatch worth flagging on the parent offload).
    """
    from models.product import Product

    if received_input is None:
        received_input = item.quantity_declared
    # Clamp to [0, declared] — a warehouse manager typing a value larger
    # than what was declared must not be able to inflate warehouse stock
    # beyond what the rep actually said they were returning.
    received = round(min(max(0, received_input), item.quantity_declared), 3)
    item.quantity_received = received
    mismatch = abs(received - item.quantity_declared) > 0.001

    vs = VanStock.query.filter_by(sales_rep_id=offload.sales_rep_id, product_id=item.product_id).first()
    if vs:
        vs.quantity = max(0, vs.quantity - received)

    product = Product.query.get(item.product_id)
    if product and received > 0:
        before = product.stock_quantity
        product.stock_quantity += received
        db.session.add(InventoryMovement(
            product_id=product.id, movement_type='transfer_in',
            quantity=received, quantity_before=before, quantity_after=product.stock_quantity,
            van_id=offload.van_id, reference_id=offload.id, reference_type='stock_offload',
            notes=f'Offload {offload.offload_number} from {offload.sales_rep.full_name if offload.sales_rep else "rep"}',
            created_by_id=current_user.id
        ))
    return mismatch
