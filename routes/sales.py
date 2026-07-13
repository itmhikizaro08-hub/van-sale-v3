from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from app import db
from models.sale import Sale, SaleItem
from models.customer import Customer
from models.product import Product
from models.van import Van
from models.notification import InventoryMovement, VanStock
from models.audit import PricingAuditLog
from services.sms_service import send_invoice_sms
from services.sequence import next_invoice_number

sales_bp = Blueprint('sales', __name__)


@sales_bp.route('/')
@login_required
def index():
    if not current_user.can_access('sales'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    start = request.args.get('start', (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end   = request.args.get('end',   datetime.utcnow().strftime('%Y-%m-%d'))
    q = Sale.query.filter(
        Sale.sale_date >= start,
        Sale.sale_date <= end + ' 23:59:59'
    )
    if current_user.scope('sales') == 'own':
        q = q.filter(Sale.sales_rep_id == current_user.id)
    sales = q.order_by(Sale.sale_date.desc()).limit(200).all()

    total_sales_amount = round(sum(s.total_amount for s in sales), 2)
    total_outstanding = round(sum(s.balance_due for s in sales), 2)

    return render_template('sales/index.html', sales=sales, start=start, end=end,
        total_sales_amount=total_sales_amount, total_outstanding=total_outstanding)


@sales_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new_sale():
    if not current_user.can_write('sales'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('sales.index'))

    customers = Customer.query.filter_by(status='active').order_by(Customer.name).all()
    products = Product.query.filter_by(status='active').filter(Product.stock_quantity > 0).order_by(Product.product_name).all()
    vans = Van.query.filter_by(status='active').all()
    return render_template('sales/new.html', customers=customers, products=products, vans=vans)


@sales_bp.route('/create', methods=['POST'])
@login_required
def create():
    if not current_user.can_write('sales'):
        return jsonify({'error': 'Permission denied'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data received'}), 400

    customer = Customer.query.get(data.get('customer_id'))
    if not customer:
        return jsonify({'error': 'Customer not found'}), 400

    if not data.get('items'):
        return jsonify({'error': 'No items in sale'}), 400

    sale = Sale(
        invoice_number=next_invoice_number(),
        customer_id=customer.id,
        van_id=data.get('van_id'),
        sales_rep_id=current_user.id,
        discount_percent=float(data.get('discount_percent') or 0),
        discount_amount=float(data.get('discount_amount') or 0),
        tax_percent=float(data.get('tax_percent') or 0),
        payment_method=data.get('payment_method', 'cash'),
        notes=data.get('notes'),
        status='completed'
    )
    db.session.add(sale)
    db.session.flush()

    for item_data in data['items']:
        product = Product.query.get(item_data['product_id'])
        if not product:
            db.session.rollback()
            return jsonify({'error': 'Unknown product'}), 400

        qty_needed = item_data['quantity']

        # Sales reps sell out of their own van custody, not the warehouse —
        # loading a van already moved this stock out of Product.stock_quantity,
        # so a rep's sale must draw down VanStock, not the warehouse figure again.
        van_stock_row = None
        if current_user.role == 'sales_rep':
            van_stock_row = VanStock.query.filter_by(
                sales_rep_id=current_user.id, product_id=product.id
            ).first()
            available = van_stock_row.quantity if van_stock_row else 0
            if available < qty_needed:
                db.session.rollback()
                return jsonify({'error': f'Insufficient van stock for {product.product_name} '
                                          f'(you have {available}, need {qty_needed}).'}), 400
        elif product.stock_quantity < qty_needed:
            db.session.rollback()
            return jsonify({'error': f'Insufficient stock for {product.product_name}'}), 400

        try:
            unit_price = round(float(item_data['unit_price']), 2)
        except (TypeError, ValueError, KeyError):
            db.session.rollback()
            return jsonify({'error': f'Invalid selling price for {product.product_name}'}), 400

        # Company Selling Price is the enforced floor — snapshotted at sale time.
        official_price = product.selling_price
        if unit_price < official_price:
            db.session.rollback()
            return jsonify({
                'error': f'Selling price cannot be lower than the company selling price '
                         f'(GHS {official_price:.2f}) for {product.product_name}.'
            }), 400

        tip_amount = round(unit_price - official_price, 2)

        item = SaleItem(
            sale_id=sale.id,
            product_id=product.id,
            quantity=item_data['quantity'],
            official_price=official_price,
            unit_price=unit_price,
            tip_amount=tip_amount,
            discount_percent=float(item_data.get('discount_percent') or 0)
        )
        item.calculate_total()
        db.session.add(item)

        db.session.add(PricingAuditLog(
            user_id=current_user.id,
            sale_id=sale.id,
            invoice_number=sale.invoice_number,
            product_id=product.id,
            company_selling_price=official_price,
            selling_price_entered=unit_price,
            tip_calculated=tip_amount,
            quantity=item.quantity,
            total_amount=item.line_total,
            action='sale'
        ))

        # Deduct stock — from van custody for reps, from the warehouse otherwise
        if van_stock_row:
            qty_before = van_stock_row.quantity
            van_stock_row.quantity -= qty_needed
            qty_after = van_stock_row.quantity
            movement_van_id = van_stock_row.van_id
        else:
            qty_before = product.stock_quantity
            product.stock_quantity -= qty_needed
            qty_after = product.stock_quantity
            movement_van_id = data.get('van_id')

        movement = InventoryMovement(
            product_id=product.id,
            movement_type='sale',
            quantity=-qty_needed,
            quantity_before=qty_before,
            quantity_after=qty_after,
            van_id=movement_van_id,
            reference_id=sale.id,
            reference_type='sale',
            created_by_id=current_user.id
        )
        db.session.add(movement)

    sale.recalculate()

    # Handle upfront payment
    upfront = float(data.get('amount_paid') or 0)
    if upfront > 0:
        from models.payment import Payment
        from services.sequence import next_payment_number
        payment = Payment(
            payment_number=next_payment_number(),
            sale_id=sale.id,
            customer_id=customer.id,
            amount=min(upfront, sale.total_amount),
            payment_method=sale.payment_method,
            received_by_id=current_user.id
        )
        db.session.add(payment)
        sale.amount_paid = payment.amount
        sale.recalculate()

    # Update customer balance
    customer.outstanding_balance += sale.balance_due
    customer.last_purchase_date = datetime.utcnow()

    # A completed field sale implies the rep visited this customer today —
    # auto-record it so "Today's Route" reflects reality without a separate tap.
    if current_user.role == 'sales_rep':
        from services.visits import record_auto_visit
        record_auto_visit(customer.id, current_user.id, 'sale_made', force_outcome=True)

    credit_warning = None
    if customer.credit_limit > 0 and customer.outstanding_balance > customer.credit_limit:
        credit_warning = (
            f'{customer.name} is now over their credit limit '
            f'(GHS {customer.outstanding_balance:.2f} owed vs GHS {customer.credit_limit:.2f} limit).'
        )

    db.session.commit()

    # Send SMS
    try:
        send_invoice_sms(customer, sale)
    except Exception:
        pass

    return jsonify({
        'success': True, 'invoice_number': sale.invoice_number, 'sale_id': sale.id,
        'credit_warning': credit_warning
    })


@sales_bp.route('/<int:sale_id>')
@login_required
def view(sale_id):
    if not current_user.can_access('sales'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    sale = Sale.query.get_or_404(sale_id)

    if current_user.scope('sales') == 'own' and sale.sales_rep_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('sales.index'))

    return render_template('sales/view.html', sale=sale)


@sales_bp.route('/<int:sale_id>/cancel', methods=['POST'])
@login_required
def cancel(sale_id):
    if not current_user.can_approve_module('sales'):
        return jsonify({'error': 'Permission denied'}), 403
    sale = Sale.query.get_or_404(sale_id)
    if sale.status == 'completed':
        # Reverse stock
        for item in sale.items:
            item.product.stock_quantity += item.quantity
        sale.status = 'cancelled'
        sale.customer.outstanding_balance -= sale.balance_due
        db.session.commit()
        return jsonify({'success': True})
    return jsonify({'error': 'Cannot cancel this sale'}), 400


@sales_bp.route('/drafts')
@login_required
def drafts():
    if not current_user.can_access('sales'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    drafts = Sale.query.filter_by(status='draft', sales_rep_id=current_user.id).order_by(Sale.created_at.desc()).all()
    return render_template('sales/drafts.html', drafts=drafts)
