from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from app import db
from models.customer import Customer
from models.product import Product
from models.sale import Sale

returns_bp = Blueprint('returns', __name__)


@returns_bp.route('/')
@login_required
def index():
    if not current_user.can_access('returns'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    from models.v4_models import ReturnOrder
    start = request.args.get('start', (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end   = request.args.get('end',   datetime.utcnow().strftime('%Y-%m-%d'))

    q = ReturnOrder.query.filter(
        ReturnOrder.created_at >= start,
        ReturnOrder.created_at <= end + ' 23:59:59'
    )
    if current_user.scope('returns') == 'own':
        q = q.filter_by(received_by_rep_id=current_user.id)
    orders = q.order_by(ReturnOrder.created_at.desc()).all()

    return render_template('returns/index.html', orders=orders, start=start, end=end)


@returns_bp.route('/add')
@login_required
def add():
    # Legacy single-item return flow — superseded by the multi-item returns.new form.
    return redirect(url_for('returns.new'))


def _bulk_resolve(order, new_status):
    """Approve or reject every still-pending line on a return order, mirroring
    approve_line/reject_line but applied to the whole order at once."""
    from models.v4_models import ReturnOrderItem, CreditNote
    from services.sequence import next_credit_note_number
    from models.product import Product
    from models.notification import VanStock

    pending_items = [i for i in order.items if i.line_status == 'pending']
    if not pending_items:
        return False

    for item in pending_items:
        item.line_status = new_status
        if new_status != 'approved':
            continue

        if order.return_destination == 'warehouse':
            p = Product.query.get(item.product_id)
            if p: p.stock_quantity += item.quantity
        elif order.return_destination == 'van_stock' and order.van_id and order.received_by_rep_id:
            vs = VanStock.query.filter_by(
                van_id=order.van_id, sales_rep_id=order.received_by_rep_id, product_id=item.product_id
            ).first()
            if vs: vs.quantity += item.quantity
            else:
                db.session.add(VanStock(van_id=order.van_id, sales_rep_id=order.received_by_rep_id,
                                        product_id=item.product_id, quantity=item.quantity))

        cn = CreditNote(
            note_number=next_credit_note_number(),
            customer_id=order.customer_id,
            sale_id=order.sale_id,
            return_order_id=order.id,
            amount=round(item.line_total, 2),
            reason=f'Return {order.return_number} — {item.product.product_name if item.product else "item"}',
            reference_note=order.reference_note,
            created_by_id=current_user.id,
            status='applied'
        )
        db.session.add(cn)
        if order.refund_method == 'credit' and order.customer:
            order.customer.outstanding_balance = max(0, order.customer.outstanding_balance - item.line_total)

    order.recalculate()
    statuses = {i.line_status for i in order.items}
    order.status = 'approved' if statuses == {'approved'} else 'rejected' if statuses == {'rejected'} else 'partial'
    order.approved_by_id = current_user.id
    order.approved_at = datetime.utcnow()
    return True


@returns_bp.route('/<int:order_id>/approve', methods=['POST'])
@login_required
def approve(order_id):
    if not current_user.can_approve_module('returns'):
        return jsonify({'error': 'Permission denied'}), 403
    from models.v4_models import ReturnOrder
    order = ReturnOrder.query.get_or_404(order_id)
    if not _bulk_resolve(order, 'approved'):
        return jsonify({'error': 'No pending lines to approve'}), 400
    db.session.commit()
    return jsonify({'success': True, 'status': order.status})


@returns_bp.route('/<int:order_id>/reject', methods=['POST'])
@login_required
def reject(order_id):
    if not current_user.can_approve_module('returns'):
        return jsonify({'error': 'Permission denied'}), 403
    from models.v4_models import ReturnOrder
    order = ReturnOrder.query.get_or_404(order_id)
    if not _bulk_resolve(order, 'rejected'):
        return jsonify({'error': 'No pending lines to reject'}), 400
    db.session.commit()
    return jsonify({'success': True, 'status': order.status})


@returns_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    if not current_user.can_write('returns'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('returns.index'))
    from models.customer import Customer
    from models.product import Product
    from models.van import Van
    customers = Customer.query.filter_by(status='active').order_by(Customer.name).all()
    products = Product.query.filter_by(status='active').order_by(Product.product_name).all()
    vans = Van.query.filter_by(status='active').all()
    if request.method == 'POST':
        from models.v4_models import ReturnOrder, ReturnOrderItem
        from services.sequence import next_return_order_number
        customer_id = request.form.get('customer_id')
        if not customer_id:
            flash('Customer is required.', 'danger')
            return redirect(url_for('returns.new'))
        order = ReturnOrder(
            return_number=next_return_order_number(),
            sale_id=request.form.get('sale_id') or None,
            customer_id=customer_id,
            received_by_rep_id=current_user.id,
            van_id=request.form.get('van_id') or None,
            return_destination=request.form.get('return_destination', 'warehouse'),
            refund_method=request.form.get('refund_method', 'credit'),
            notes=request.form.get('notes'),
            reference_note=request.form.get('reference_note'),
            created_by_id=current_user.id,
            status='pending'
        )
        db.session.add(order)
        db.session.flush()
        product_ids = request.form.getlist('product_id[]')
        quantities  = request.form.getlist('quantity[]')
        prices      = request.form.getlist('unit_price[]')
        reasons     = request.form.getlist('reason[]')
        has_items = False
        for i, pid in enumerate(product_ids):
            if not pid: continue
            qty   = int(quantities[i]) if i < len(quantities) and quantities[i] else 0
            if qty <= 0: continue
            price  = float(prices[i]) if i < len(prices) and prices[i] else 0.0
            reason = reasons[i] if i < len(reasons) else 'sales_return'
            item = ReturnOrderItem(
                return_order_id=order.id,
                product_id=int(pid),
                quantity=qty,
                unit_price=price,
                reason=reason,
                line_status='pending'
            )
            item.calculate_total()
            db.session.add(item)
            has_items = True
        if not has_items:
            db.session.rollback()
            flash('Add at least one product.', 'danger')
            return redirect(url_for('returns.new'))
        order.recalculate()
        db.session.commit()
        flash(f'Return order {order.return_number} submitted.', 'success')
        return redirect(url_for('returns.view', order_id=order.id))
    return render_template('returns/new.html', customers=customers, products=products, vans=vans)


@returns_bp.route('/<int:order_id>')
@login_required
def view(order_id):
    from models.v4_models import ReturnOrder
    order = ReturnOrder.query.get_or_404(order_id)
    if current_user.scope('returns') == 'own' and order.received_by_rep_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('returns.index'))
    return render_template('returns/view.html', order=order)


@returns_bp.route('/api/customer-sales/<int:customer_id>')
@login_required
def customer_sales(customer_id):
    from models.sale import Sale
    sales = Sale.query.filter_by(
        customer_id=customer_id, status='completed'
    ).order_by(Sale.sale_date.desc()).limit(20).all()
    return jsonify([{
        'id': s.id,
        'invoice_number': s.invoice_number,
        'sale_date': s.sale_date.strftime('%d %b %Y') if s.sale_date else ''
    } for s in sales])


@returns_bp.route('/api/sale-items/<int:sale_id>')
@login_required
def sale_items(sale_id):
    from models.sale import Sale, SaleItem
    sale = Sale.query.get_or_404(sale_id)
    return jsonify([{
        'sale_item_id': i.id,
        'product_id':   i.product_id,
        'product_name': i.product.product_name if i.product else '',
        'quantity':     i.quantity,
        'unit_price':   i.unit_price
    } for i in sale.items])


@returns_bp.route('/<int:order_id>/approve-line/<int:item_id>', methods=['POST'])
@login_required
def approve_line(order_id, item_id):
    if not current_user.can_approve_module('returns'):
        return jsonify({'error': 'Permission denied'}), 403
    from models.v4_models import ReturnOrder, ReturnOrderItem, CreditNote
    from services.sequence import next_credit_note_number
    order = ReturnOrder.query.get_or_404(order_id)
    item  = ReturnOrderItem.query.filter_by(id=item_id, return_order_id=order.id).first_or_404()
    if item.line_status != 'pending':
        return jsonify({'error': 'Already processed'}), 400

    item.line_status = 'approved'
    # Route stock
    from models.product import Product
    if order.return_destination == 'warehouse':
        p = Product.query.get(item.product_id)
        if p: p.stock_quantity += item.quantity
    elif order.return_destination == 'van_stock' and order.van_id and order.received_by_rep_id:
        from models.notification import VanStock
        vs = VanStock.query.filter_by(
            van_id=order.van_id, sales_rep_id=order.received_by_rep_id, product_id=item.product_id
        ).first()
        if vs: vs.quantity += item.quantity
        else:
            db.session.add(VanStock(van_id=order.van_id, sales_rep_id=order.received_by_rep_id,
                                    product_id=item.product_id, quantity=item.quantity))

    # Credit note for this line
    cn = CreditNote(
        note_number=next_credit_note_number(),
        customer_id=order.customer_id,
        sale_id=order.sale_id,
        return_order_id=order.id,
        amount=round(item.line_total, 2),
        reason=f'Return {order.return_number} — {item.product.product_name if item.product else "item"}',
        reference_note=order.reference_note,
        created_by_id=current_user.id,
        status='applied'
    )
    db.session.add(cn)
    if order.refund_method == 'credit' and order.customer:
        order.customer.outstanding_balance = max(0, order.customer.outstanding_balance - item.line_total)

    order.recalculate()
    statuses = {i.line_status for i in order.items}
    order.status = 'approved' if statuses == {'approved'} else 'rejected' if statuses == {'rejected'} else 'partial'
    order.approved_by_id = current_user.id
    from datetime import datetime
    order.approved_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True, 'status': order.status, 'credit_note': cn.note_number})


@returns_bp.route('/<int:order_id>/reject-line/<int:item_id>', methods=['POST'])
@login_required
def reject_line(order_id, item_id):
    if not current_user.can_approve_module('returns'):
        return jsonify({'error': 'Permission denied'}), 403
    from models.v4_models import ReturnOrder, ReturnOrderItem
    order = ReturnOrder.query.get_or_404(order_id)
    item  = ReturnOrderItem.query.filter_by(id=item_id, return_order_id=order.id).first_or_404()
    if item.line_status != 'pending':
        return jsonify({'error': 'Already processed'}), 400
    item.line_status = 'rejected'
    statuses = {i.line_status for i in order.items}
    order.status = 'approved' if statuses == {'approved'} else 'rejected' if statuses == {'rejected'} else 'partial'
    order.approved_by_id = current_user.id
    from datetime import datetime
    order.approved_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True, 'status': order.status})


# ── Supplier Returns (goods sent back to a supplier) ────────────────────────
# Gated by the 'procurement' permission, not 'returns' — the customer-return
# 'returns' key grants sales_rep write access ('own', True, False), which
# would incorrectly let a rep submit a supplier return (a warehouse/admin
# operation touching warehouse stock and a supplier's balance, not a rep's
# own scope). 'procurement' already has the right shape: admin/manager full,
# warehouse_manager submit-only, everyone else blocked.

@returns_bp.route('/supplier')
@login_required
def supplier_index():
    if not current_user.can_access('procurement'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    from models.supplier_return import SupplierReturn
    start = request.args.get('start', (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end   = request.args.get('end',   datetime.utcnow().strftime('%Y-%m-%d'))

    returns = SupplierReturn.query.filter(
        SupplierReturn.created_at >= start,
        SupplierReturn.created_at <= end + ' 23:59:59'
    ).order_by(SupplierReturn.created_at.desc()).all()

    return render_template('returns/supplier_index.html', returns=returns, start=start, end=end)


@returns_bp.route('/supplier/new', methods=['GET', 'POST'])
@login_required
def supplier_new():
    if not current_user.can_write('procurement'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('returns.supplier_index'))

    from models.notification import Supplier
    from models.product import Product
    suppliers = Supplier.query.filter_by(status='active').order_by(Supplier.name).all()
    products = Product.query.filter_by(status='active').order_by(Product.product_name).all()

    if request.method == 'POST':
        from models.supplier_return import SupplierReturn, SupplierReturnItem
        from services.sequence import next_supplier_return_number

        supplier_id = request.form.get('supplier_id')
        if not supplier_id:
            flash('Supplier is required.', 'danger')
            return redirect(url_for('returns.supplier_new'))

        ret = SupplierReturn(
            return_number=next_supplier_return_number(),
            supplier_id=supplier_id,
            notes=request.form.get('notes'),
            reference_note=request.form.get('reference_note'),
            created_by_id=current_user.id,
            status='pending'
        )
        db.session.add(ret)
        db.session.flush()

        product_ids = request.form.getlist('product_id[]')
        quantities  = request.form.getlist('quantity[]')
        reasons     = request.form.getlist('reason[]')
        has_items = False
        for i, pid in enumerate(product_ids):
            if not pid:
                continue
            try:
                qty = round(float(quantities[i]), 3) if i < len(quantities) and quantities[i] else 0
            except (TypeError, ValueError):
                continue
            if qty <= 0:
                continue
            product = Product.query.get(int(pid))
            if not product:
                continue
            # A supplier return removes stock we're claiming to have — can't
            # return more of something than the warehouse actually holds.
            if qty > product.stock_quantity:
                db.session.rollback()
                flash(f'Cannot return {qty} of {product.product_name} — only '
                      f'{product.stock_quantity} in warehouse stock.', 'danger')
                return redirect(url_for('returns.supplier_new'))
            reason = reasons[i] if i < len(reasons) else 'other'
            item = SupplierReturnItem(
                supplier_return_id=ret.id,
                product_id=product.id,
                quantity=qty,
                unit_cost=product.cost_price or 0,
                reason=reason,
                line_status='pending'
            )
            item.calculate_total()
            db.session.add(item)
            has_items = True

        if not has_items:
            db.session.rollback()
            flash('Add at least one product.', 'danger')
            return redirect(url_for('returns.supplier_new'))

        ret.recalculate()
        db.session.commit()
        flash(f'Supplier return {ret.return_number} submitted.', 'success')
        return redirect(url_for('returns.supplier_view', return_id=ret.id))

    return render_template('returns/supplier_new.html', suppliers=suppliers, products=products)


@returns_bp.route('/supplier/<int:return_id>')
@login_required
def supplier_view(return_id):
    if not current_user.can_access('procurement'):
        flash('Access denied.', 'danger')
        return redirect(url_for('returns.supplier_index'))
    from models.supplier_return import SupplierReturn
    ret = SupplierReturn.query.get_or_404(return_id)
    return render_template('returns/supplier_view.html', ret=ret)


def _supplier_bulk_resolve(ret, new_status):
    """Approve or reject every still-pending line, mirroring the customer
    return's _bulk_resolve but decrementing stock/supplier balance instead."""
    from models.product import Product

    pending_items = [i for i in ret.items if i.line_status == 'pending']
    if not pending_items:
        return False

    for item in pending_items:
        item.line_status = new_status
        if new_status != 'approved':
            continue

        product = Product.query.get(item.product_id)
        if product:
            product.stock_quantity = max(0, product.stock_quantity - item.quantity)

        if ret.supplier:
            ret.supplier.outstanding_balance = max(0, ret.supplier.outstanding_balance - item.line_total)

    statuses = {i.line_status for i in ret.items}
    ret.status = 'approved' if statuses == {'approved'} else 'rejected' if statuses == {'rejected'} else 'partial'
    ret.approved_by_id = current_user.id
    ret.approved_at = datetime.utcnow()
    return True


@returns_bp.route('/supplier/<int:return_id>/approve', methods=['POST'])
@login_required
def supplier_approve(return_id):
    if not current_user.can_approve_module('procurement'):
        return jsonify({'error': 'Permission denied'}), 403
    from models.supplier_return import SupplierReturn
    ret = SupplierReturn.query.get_or_404(return_id)
    if not _supplier_bulk_resolve(ret, 'approved'):
        return jsonify({'error': 'No pending lines to approve'}), 400
    db.session.commit()
    return jsonify({'success': True, 'status': ret.status})


@returns_bp.route('/supplier/<int:return_id>/reject', methods=['POST'])
@login_required
def supplier_reject(return_id):
    if not current_user.can_approve_module('procurement'):
        return jsonify({'error': 'Permission denied'}), 403
    from models.supplier_return import SupplierReturn
    ret = SupplierReturn.query.get_or_404(return_id)
    if not _supplier_bulk_resolve(ret, 'rejected'):
        return jsonify({'error': 'No pending lines to reject'}), 400
    db.session.commit()
    return jsonify({'success': True, 'status': ret.status})


@returns_bp.route('/supplier/<int:return_id>/approve-line/<int:item_id>', methods=['POST'])
@login_required
def supplier_approve_line(return_id, item_id):
    if not current_user.can_approve_module('procurement'):
        return jsonify({'error': 'Permission denied'}), 403
    from models.supplier_return import SupplierReturn, SupplierReturnItem
    from models.product import Product
    ret  = SupplierReturn.query.get_or_404(return_id)
    item = SupplierReturnItem.query.filter_by(id=item_id, supplier_return_id=ret.id).first_or_404()
    if item.line_status != 'pending':
        return jsonify({'error': 'Already processed'}), 400

    item.line_status = 'approved'
    product = Product.query.get(item.product_id)
    if product:
        product.stock_quantity = max(0, product.stock_quantity - item.quantity)
    if ret.supplier:
        ret.supplier.outstanding_balance = max(0, ret.supplier.outstanding_balance - item.line_total)

    statuses = {i.line_status for i in ret.items}
    ret.status = 'approved' if statuses == {'approved'} else 'rejected' if statuses == {'rejected'} else 'partial'
    ret.approved_by_id = current_user.id
    ret.approved_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True, 'status': ret.status})


@returns_bp.route('/supplier/<int:return_id>/reject-line/<int:item_id>', methods=['POST'])
@login_required
def supplier_reject_line(return_id, item_id):
    if not current_user.can_approve_module('procurement'):
        return jsonify({'error': 'Permission denied'}), 403
    from models.supplier_return import SupplierReturn, SupplierReturnItem
    ret  = SupplierReturn.query.get_or_404(return_id)
    item = SupplierReturnItem.query.filter_by(id=item_id, supplier_return_id=ret.id).first_or_404()
    if item.line_status != 'pending':
        return jsonify({'error': 'Already processed'}), 400
    item.line_status = 'rejected'
    statuses = {i.line_status for i in ret.items}
    ret.status = 'approved' if statuses == {'approved'} else 'rejected' if statuses == {'rejected'} else 'partial'
    ret.approved_by_id = current_user.id
    ret.approved_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True, 'status': ret.status})
