from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime, date
from app import db
from models.scheduled_order import ScheduledOrder, ScheduledOrderItem
from models.customer import Customer
from models.product import Product

scheduled_orders_bp = Blueprint('scheduled_orders', __name__)


def _visible_query():
    q = ScheduledOrder.query
    if current_user.scope('scheduled_orders') == 'own':
        q = q.filter_by(rep_id=current_user.id)
    return q


@scheduled_orders_bp.route('/')
@login_required
def index():
    if not current_user.can_access('scheduled_orders'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    status = request.args.get('status', '')
    q = _visible_query()
    if status:
        q = q.filter_by(status=status)
    orders = q.order_by(ScheduledOrder.due_date.asc()).all()

    today = date.today()
    pending_count = sum(1 for o in orders if o.status == 'pending')
    due_today_count = sum(1 for o in orders if o.status == 'pending' and o.due_date == today)
    overdue_count = sum(1 for o in orders if o.is_overdue)
    fulfilled_count = sum(1 for o in orders if o.status == 'fulfilled')

    return render_template('scheduled_orders/index.html', orders=orders, status=status,
        today=today, pending_count=pending_count, due_today_count=due_today_count,
        overdue_count=overdue_count, fulfilled_count=fulfilled_count)


@scheduled_orders_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    if not current_user.can_write('scheduled_orders'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('scheduled_orders.index'))

    if request.method == 'POST':
        customer_id = request.form.get('customer_id')
        due_date_str = request.form.get('due_date', '')
        notes = request.form.get('notes', '').strip()
        product_ids = request.form.getlist('product_id[]')
        quantities = request.form.getlist('quantity[]')

        customer = Customer.query.get(customer_id) if customer_id else None
        if not customer:
            flash('Select a valid customer.', 'danger')
            return redirect(url_for('scheduled_orders.new'))
        if current_user.scope('scheduled_orders') == 'own' and customer.sales_rep_id != current_user.id:
            flash('You can only schedule orders for your own customers.', 'danger')
            return redirect(url_for('scheduled_orders.new'))

        try:
            due_date_val = datetime.strptime(due_date_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Enter a valid due date.', 'danger')
            return redirect(url_for('scheduled_orders.new'))
        if due_date_val < date.today():
            flash('Due date cannot be in the past.', 'danger')
            return redirect(url_for('scheduled_orders.new'))

        items = []
        for pid, qty_str in zip(product_ids, quantities):
            if not pid or not qty_str:
                continue
            try:
                qty = float(qty_str)
            except ValueError:
                flash('Quantities must be numbers.', 'danger')
                return redirect(url_for('scheduled_orders.new'))
            if qty <= 0:
                flash('Quantities must be greater than zero.', 'danger')
                return redirect(url_for('scheduled_orders.new'))
            product = Product.query.get(pid)
            if not product:
                continue
            items.append((product, qty))

        if not items:
            flash('Add at least one product.', 'danger')
            return redirect(url_for('scheduled_orders.new'))

        from services.sequence import next_scheduled_order_number
        order = ScheduledOrder(
            order_number=next_scheduled_order_number(),
            customer_id=customer.id,
            rep_id=customer.sales_rep_id,
            due_date=due_date_val,
            notes=notes or None,
            created_by_id=current_user.id
        )
        db.session.add(order)
        db.session.flush()

        for product, qty in items:
            db.session.add(ScheduledOrderItem(
                scheduled_order_id=order.id, product_id=product.id,
                quantity=qty, ref_price=product.selling_price
            ))
        db.session.commit()

        flash(f'Order {order.order_number} scheduled for {due_date_val.strftime("%d %b %Y")}.', 'success')
        return redirect(url_for('scheduled_orders.view', order_id=order.id))

    customers_q = Customer.query.filter_by(status='active')
    if current_user.scope('scheduled_orders') == 'own':
        customers_q = customers_q.filter_by(sales_rep_id=current_user.id)
    customers = customers_q.order_by(Customer.name).all()
    products = Product.query.filter_by(status='active').order_by(Product.product_name).all()
    return render_template('scheduled_orders/new.html', customers=customers, products=products,
        today=date.today().isoformat())


@scheduled_orders_bp.route('/<int:order_id>')
@login_required
def view(order_id):
    if not current_user.can_access('scheduled_orders'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    order = ScheduledOrder.query.get_or_404(order_id)
    if current_user.scope('scheduled_orders') == 'own' and order.rep_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('scheduled_orders.index'))
    return render_template('scheduled_orders/view.html', order=order)


@scheduled_orders_bp.route('/<int:order_id>/cancel', methods=['POST'])
@login_required
def cancel(order_id):
    order = ScheduledOrder.query.get_or_404(order_id)
    if current_user.scope('scheduled_orders') == 'own' and order.rep_id != current_user.id:
        return jsonify({'error': 'Access denied'}), 403
    if not (current_user.can_write('scheduled_orders') or current_user.can_approve_module('scheduled_orders')):
        return jsonify({'error': 'Permission denied'}), 403
    if order.status != 'pending':
        return jsonify({'error': 'Only pending orders can be cancelled.'}), 400
    order.status = 'cancelled'
    db.session.commit()
    return jsonify({'success': True, 'message': f'Order {order.order_number} cancelled.'})


@scheduled_orders_bp.route('/<int:order_id>/fulfill', methods=['POST'])
@login_required
def fulfill(order_id):
    order = ScheduledOrder.query.get_or_404(order_id)
    if current_user.scope('scheduled_orders') == 'own' and order.rep_id != current_user.id:
        return jsonify({'error': 'Access denied'}), 403
    if not current_user.can_write('scheduled_orders'):
        return jsonify({'error': 'Permission denied'}), 403
    if order.status != 'pending':
        return jsonify({'error': 'Only pending orders can be marked fulfilled.'}), 400
    order.status = 'fulfilled'
    db.session.commit()
    return jsonify({'success': True, 'message': f'Order {order.order_number} marked fulfilled.'})
