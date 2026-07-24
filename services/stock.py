"""Shared warehouse stock-movement logging.

Moved out of routes/returns.py (where it started as a private helper) since
it records the same InventoryMovement audit trail used by stock_in/
stock_out/adjustment elsewhere — worth having under services/ where it's
discoverable rather than hidden inside one blueprint.
"""
from flask_login import current_user
from app import db
from models.inventory import InventoryMovement


def log_stock_movement(product, delta, movement_type, reference_type, reference_id, reference_note=None):
    """Record a warehouse stock change so it shows up on the Inventory
    Movements audit log, the same as stock_in/stock_out/adjustment do —
    approving a return previously mutated Product.stock_quantity directly
    with no trace left anywhere else in the app.
    Call AFTER product.stock_quantity has already been updated by `delta`."""
    db.session.add(InventoryMovement(
        product_id=product.id,
        movement_type=movement_type,
        quantity=delta,
        quantity_before=product.stock_quantity - delta,
        quantity_after=product.stock_quantity,
        reference_id=reference_id,
        reference_type=reference_type,
        reference_note=reference_note,
        created_by_id=current_user.id
    ))
