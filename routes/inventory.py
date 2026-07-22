from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from app import db
from models.product import Product
from models.van import Van
from models.notification import InventoryMovement, VanStock, Supplier

inventory_bp = Blueprint('inventory', __name__)


def _require_access():
    if not current_user.can_access('inventory'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    return None


def _require_write():
    if not current_user.can_write('inventory'):
        flash('Write access required for this action.', 'danger')
        return redirect(url_for('inventory.index'))
    return None


@inventory_bp.route('/')
@login_required
def index():
    denied = _require_access()
    if denied:
        return denied

    products = Product.query.filter_by(status='active').order_by(Product.product_name).all()

    field_qty_map = dict(
        db.session.query(VanStock.product_id, db.func.sum(VanStock.quantity))
        .group_by(VanStock.product_id).all()
    )

    low_stock_count = sum(1 for p in products if p.is_low_stock and p.stock_quantity > 0)
    out_of_stock_count = sum(1 for p in products if p.stock_quantity == 0)

    return render_template('inventory/index.html', products=products, field_qty_map=field_qty_map,
        low_stock_count=low_stock_count, out_of_stock_count=out_of_stock_count)


@inventory_bp.route('/movements')
@login_required
def movements():
    denied = _require_access()
    if denied:
        return denied

    start = request.args.get('start', (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end   = request.args.get('end',   datetime.utcnow().strftime('%Y-%m-%d'))

    movements = InventoryMovement.query.filter(
        InventoryMovement.created_at >= start,
        InventoryMovement.created_at <= end + ' 23:59:59'
    ).order_by(InventoryMovement.created_at.desc()).limit(200).all()

    return render_template('inventory/movements.html', movements=movements, start=start, end=end)


@inventory_bp.route('/stock-in', methods=['GET', 'POST'])
@login_required
def stock_in():
    denied = _require_write()
    if denied:
        return denied

    products = Product.query.filter_by(status='active').order_by(Product.product_name).all()
    suppliers = Supplier.query.filter_by(status='active').order_by(Supplier.name).all()

    if request.method == 'POST':
        supplier_id = request.form.get('supplier_id', type=int)
        reference_note = request.form.get('reference_note')
        notes = request.form.get('notes')

        if not supplier_id:
            flash('Select which supplier this stock came from.', 'danger')
            return redirect(url_for('inventory.stock_in'))

        product_ids = request.form.getlist('product_id[]')
        quantities  = request.form.getlist('quantity[]')

        created = []
        for pid, qty_str in zip(product_ids, quantities):
            if not pid or not qty_str:
                continue
            try:
                qty = int(qty_str)
            except ValueError:
                continue
            if qty <= 0:
                continue
            product = Product.query.get(pid)
            if not product:
                continue

            qty_before = product.stock_quantity
            product.stock_quantity += qty
            movement = InventoryMovement(
                product_id=product.id,
                movement_type='stock_in',
                quantity=qty,
                quantity_before=qty_before,
                quantity_after=product.stock_quantity,
                supplier_id=supplier_id,
                reference_note=reference_note,
                reference_type='stock_in_batch',
                notes=notes,
                created_by_id=current_user.id
            )
            db.session.add(movement)
            created.append(movement)

        if not created:
            db.session.rollback()
            flash('Add at least one product with a valid quantity.', 'danger')
            return redirect(url_for('inventory.stock_in'))

        # Tag every line in this delivery with a shared batch reference so
        # they can be traced back to the same receipt on the Movements list.
        db.session.flush()
        batch_ref = created[0].id
        for m in created:
            m.reference_id = batch_ref

        # Goods received on credit are money we now owe the supplier —
        # this is the payable side of the purchase; settled via Pay Supplier.
        supplier = Supplier.query.get(supplier_id)
        total_value = round(sum(m.quantity * (m.product.cost_price or 0) for m in created), 2)
        supplier.outstanding_balance = round((supplier.outstanding_balance or 0) + total_value, 2)

        db.session.commit()

        total_units = sum(m.quantity for m in created)
        flash(f'Received {total_units} units (GHS {total_value:.2f}) across {len(created)} product(s) '
              f'from {supplier.name}. Added to their balance.', 'success')
        return redirect(url_for('inventory.index'))

    return render_template('inventory/stock_in.html', products=products, suppliers=suppliers)


@inventory_bp.route('/stock-out', methods=['GET', 'POST'])
@login_required
def stock_out():
    denied = _require_write()
    if denied:
        return denied

    products = Product.query.filter_by(status='active').order_by(Product.product_name).all()
    if request.method == 'POST':
        product = Product.query.get_or_404(request.form['product_id'])
        try:
            qty = int(request.form.get('quantity') or 0)
        except ValueError:
            flash('Enter a valid quantity.', 'danger')
            return redirect(url_for('inventory.stock_out'))
        if qty <= 0:
            flash('Quantity must be greater than zero.', 'danger')
            return redirect(url_for('inventory.stock_out'))
        if qty > product.stock_quantity:
            flash('Insufficient stock.', 'danger')
            return redirect(url_for('inventory.stock_out'))
        qty_before = product.stock_quantity
        product.stock_quantity -= qty
        movement = InventoryMovement(
            product_id=product.id,
            movement_type=request.form.get('movement_type', 'stock_out'),
            quantity=-qty,
            quantity_before=qty_before,
            quantity_after=product.stock_quantity,
            reference_note=request.form.get('reference_note'),
            notes=request.form.get('notes'),
            created_by_id=current_user.id
        )
        db.session.add(movement)
        db.session.commit()
        flash(f'Removed {qty} units of {product.product_name}. Remaining: {product.stock_quantity}', 'success')
        return redirect(url_for('inventory.index'))
    return render_template('inventory/stock_out.html', products=products)


@inventory_bp.route('/adjustment', methods=['GET', 'POST'])
@login_required
def adjustment():
    denied = _require_write()
    if denied:
        return denied

    products = Product.query.filter_by(status='active').order_by(Product.product_name).all()
    if request.method == 'POST':
        product = Product.query.get_or_404(request.form['product_id'])
        try:
            new_qty = int(request.form.get('new_quantity') or 0)
        except ValueError:
            flash('Enter a valid quantity.', 'danger')
            return redirect(url_for('inventory.adjustment'))
        if new_qty < 0:
            flash('Quantity cannot be negative.', 'danger')
            return redirect(url_for('inventory.adjustment'))
        qty_before = product.stock_quantity
        diff = new_qty - qty_before
        product.stock_quantity = new_qty
        movement = InventoryMovement(
            product_id=product.id,
            movement_type='adjustment',
            quantity=diff,
            quantity_before=qty_before,
            quantity_after=new_qty,
            reference_note=request.form.get('reference_note'),
            notes=request.form.get('notes'),
            created_by_id=current_user.id
        )
        db.session.add(movement)
        db.session.commit()
        flash(f'Stock adjusted for {product.product_name} to {new_qty} units.', 'success')
        return redirect(url_for('inventory.index'))
    return render_template('inventory/adjustment.html', products=products)


@inventory_bp.route('/van-stock')
@login_required
def van_stock():
    # Superseded by the canonical van stock view in the Van Management module.
    return redirect(url_for('vans.stock'))
