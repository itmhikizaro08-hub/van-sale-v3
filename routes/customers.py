import csv
import io
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, Response
from flask_login import login_required, current_user
from app import db
from models.customer import Customer
from models.van import Van, Route
from models.user import User
from models.sale import Sale
from models.payment import Payment
from datetime import datetime

customers_bp = Blueprint('customers', __name__)


def _next_code():
    last = Customer.query.order_by(Customer.id.desc()).first()
    n = (last.id + 1) if last else 1
    return f'CUST{n:04d}'


CUSTOMER_IMPORT_COLUMNS = [
    'customer_code', 'name', 'phone', 'email', 'address', 'location',
    'customer_type', 'credit_limit', 'status', 'notes'
]


@customers_bp.route('/import', methods=['GET', 'POST'])
@login_required
def import_csv():
    if not current_user.can_write('customers'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('customers.index'))

    if request.method == 'POST':
        file = request.files.get('file')
        if not file or not file.filename:
            flash('Choose a CSV file to upload.', 'warning')
            return redirect(url_for('customers.import_csv'))

        try:
            stream = io.StringIO(file.stream.read().decode('utf-8-sig'))
            reader = csv.DictReader(stream)
        except Exception:
            flash('Could not read that file — make sure it is a valid CSV.', 'danger')
            return redirect(url_for('customers.import_csv'))

        created, skipped, errors = 0, 0, []
        for i, row in enumerate(reader, start=2):  # row 1 is the header
            name = (row.get('name') or '').strip()
            if not name:
                errors.append(f'Row {i}: missing name — skipped.')
                continue

            code = (row.get('customer_code') or '').strip() or _next_code()
            if Customer.query.filter_by(customer_code=code).first():
                skipped += 1
                continue

            try:
                customer = Customer(
                    customer_code=code,
                    name=name,
                    phone=(row.get('phone') or '').strip() or None,
                    email=(row.get('email') or '').strip() or None,
                    address=(row.get('address') or '').strip() or None,
                    location=(row.get('location') or '').strip() or None,
                    customer_type=(row.get('customer_type') or 'retail').strip(),
                    credit_limit=float(row.get('credit_limit') or 0),
                    status=(row.get('status') or 'active').strip(),
                    notes=(row.get('notes') or '').strip() or None
                )
                db.session.add(customer)
                created += 1
            except (TypeError, ValueError):
                errors.append(f'Row {i} ({name}): invalid number in one of the fields — skipped.')
                continue

        db.session.commit()
        msg = f'Imported {created} customer(s), skipped {skipped} duplicate(s).'
        flash(msg, 'success' if created else 'warning')
        for err in errors[:20]:
            flash(err, 'warning')
        return redirect(url_for('customers.index'))

    return render_template('customers/import.html')


@customers_bp.route('/import/template.csv')
@login_required
def import_template():
    if not current_user.can_write('customers'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('customers.index'))

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(CUSTOMER_IMPORT_COLUMNS)
    writer.writerow(['', 'Sample Customer', '0241234567', '', '', '', 'retail', '1000', 'active', ''])
    return Response(output.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=customers_import_template.csv'})


@customers_bp.route('/')
@login_required
def index():
    if not current_user.can_access('customers'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    q = Customer.query
    if current_user.scope('customers') == 'own':
        q = q.filter_by(sales_rep_id=current_user.id)
    customers = q.order_by(Customer.name).all()

    total_outstanding = round(sum(c.outstanding_balance for c in customers), 2)
    active_count = sum(1 for c in customers if c.status == 'active')

    return render_template('customers/index.html', customers=customers,
        total_outstanding=total_outstanding, active_count=active_count)


@customers_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if not current_user.can_write('customers'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('customers.index'))

    vans = Van.query.filter_by(status='active').all()
    routes = Route.query.filter_by(status='active').all()
    sales_reps = User.query.filter(User.role.in_(['sales_rep', 'supervisor', 'manager'])).all()

    if request.method == 'POST':
        name = request.form['name'].strip()
        existing = Customer.query.filter(
            Customer.status == 'active', db.func.lower(Customer.name) == name.lower()
        ).first()
        if existing:
            flash(f'A customer named "{name}" already exists ({existing.customer_code}). '
                  f'Edit it instead, or use a different name.', 'warning')
            return redirect(url_for('customers.add'))

        customer = Customer(
            customer_code=_next_code(),
            name=name,
            phone=request.form.get('phone'),
            email=request.form.get('email'),
            address=request.form.get('address'),
            location=request.form.get('location'),
            gps_latitude=request.form.get('gps_latitude') or None,
            gps_longitude=request.form.get('gps_longitude') or None,
            customer_type=request.form.get('customer_type', 'retail'),
            credit_limit=float(request.form.get('credit_limit') or 0),
            assigned_route_id=request.form.get('assigned_route_id') or None,
            assigned_van_id=request.form.get('assigned_van_id') or None,
            sales_rep_id=request.form.get('sales_rep_id') or None,
            status=request.form.get('status', 'active'),
            notes=request.form.get('notes')
        )
        db.session.add(customer)
        db.session.commit()
        flash(f'Customer {customer.name} added!', 'success')
        return redirect(url_for('customers.view', customer_id=customer.id))

    return render_template('customers/form.html', customer=None, vans=vans, routes=routes, sales_reps=sales_reps)


def _can_view_customer(customer):
    if not current_user.can_access('customers'):
        return False
    if current_user.scope('customers') == 'own' and customer.sales_rep_id != current_user.id:
        return False
    return True


@customers_bp.route('/<int:customer_id>')
@login_required
def view(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    if not _can_view_customer(customer):
        flash('Access denied.', 'danger')
        return redirect(url_for('customers.index'))
    recent_sales = Sale.query.filter_by(customer_id=customer_id).order_by(Sale.sale_date.desc()).limit(10).all()
    recent_payments = Payment.query.filter_by(customer_id=customer_id).order_by(Payment.payment_date.desc()).limit(10).all()
    from models.van import CustomerVisit
    recent_visits = CustomerVisit.query.filter_by(customer_id=customer_id).order_by(CustomerVisit.visit_date.desc()).limit(10).all()

    from models.sale import SaleItem
    from models.product import Product
    from sqlalchemy import func

    completed_sales = Sale.query.filter_by(customer_id=customer_id, status='completed').all()
    total_orders = len(completed_sales)
    lifetime_value = round(sum(s.total_amount for s in completed_sales), 2)
    avg_order_value = round(lifetime_value / total_orders, 2) if total_orders else 0

    monthly = {}
    for s in completed_sales:
        if s.sale_date:
            key = s.sale_date.strftime('%Y-%m')
            monthly[key] = monthly.get(key, 0) + s.total_amount
    sorted_months = sorted(monthly.keys())[-12:]
    trend_labels = [datetime.strptime(m, '%Y-%m').strftime('%b %Y') for m in sorted_months]
    trend_values = [round(monthly[m], 2) for m in sorted_months]

    product_rows = db.session.query(
        SaleItem.product_id, func.sum(SaleItem.line_total).label('val'), func.sum(SaleItem.quantity).label('qty')
    ).join(Sale, SaleItem.sale_id == Sale.id).filter(
        Sale.customer_id == customer_id, Sale.status == 'completed'
    ).group_by(SaleItem.product_id).order_by(func.sum(SaleItem.line_total).desc()).limit(5).all()
    by_product = []
    for pid, val, qty in product_rows:
        product = Product.query.get(pid)
        by_product.append((product.product_name if product else 'Unknown', round(val, 2), qty))

    non_void_payments = Payment.query.filter_by(customer_id=customer_id).filter(Payment.status != 'void').all()
    method_map = {}
    for p in non_void_payments:
        method_map[p.payment_method] = method_map.get(p.payment_method, 0) + p.amount
    by_method = sorted(method_map.items(), key=lambda x: x[1], reverse=True)

    return render_template('customers/view.html', customer=customer, recent_sales=recent_sales,
                           recent_payments=recent_payments, recent_visits=recent_visits,
                           total_orders=total_orders, lifetime_value=lifetime_value, avg_order_value=avg_order_value,
                           trend_labels=trend_labels, trend_values=trend_values,
                           by_product=by_product, by_method=by_method)


@customers_bp.route('/<int:customer_id>/statement')
@login_required
def statement(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    if not _can_view_customer(customer):
        flash('Access denied.', 'danger')
        return redirect(url_for('customers.index'))

    from datetime import timedelta
    start = request.args.get('start', (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end   = request.args.get('end',   datetime.utcnow().strftime('%Y-%m-%d'))

    from services.statements import customer_statement_rows
    opening_balance, rows, closing_balance = customer_statement_rows(customer, start, end)
    total_debit = round(sum(r['debit'] for r in rows), 2)
    total_credit = round(sum(r['credit'] for r in rows), 2)

    return render_template('customers/statement.html', customer=customer, start=start, end=end,
        opening_balance=opening_balance, rows=rows, closing_balance=closing_balance,
        total_debit=total_debit, total_credit=total_credit)


@customers_bp.route('/<int:customer_id>/statement/pdf')
@login_required
def statement_pdf(customer_id):
    from flask import make_response, current_app
    customer = Customer.query.get_or_404(customer_id)
    if not _can_view_customer(customer):
        flash('Access denied.', 'danger')
        return redirect(url_for('customers.index'))

    from datetime import timedelta
    start = request.args.get('start', (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end   = request.args.get('end',   datetime.utcnow().strftime('%Y-%m-%d'))

    from services.statements import customer_statement_rows
    from services.pdf_service import generate_statement_pdf
    from models.settings import Settings
    opening_balance, rows, closing_balance = customer_statement_rows(customer, start, end)

    s = Settings.get()
    company = {'name': s.company_name, 'address': s.company_address,
               'phone': s.company_phone, 'email': s.company_email}
    entity = {'name': customer.name, 'code': customer.customer_code,
              'phone': customer.phone, 'email': customer.email}

    pdf_bytes = generate_statement_pdf('Customer', entity, company, start, end,
                                        opening_balance, rows, closing_balance)
    response = make_response(pdf_bytes)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=statement_{customer.customer_code}_{start}_to_{end}.pdf'
    return response


@customers_bp.route('/<int:customer_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(customer_id):
    if not current_user.can_write('customers'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('customers.index'))

    customer = Customer.query.get_or_404(customer_id)
    if current_user.scope('customers') == 'own' and customer.sales_rep_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('customers.index'))
    vans = Van.query.filter_by(status='active').all()
    routes = Route.query.filter_by(status='active').all()
    sales_reps = User.query.filter(User.role.in_(['sales_rep', 'supervisor', 'manager'])).all()

    if request.method == 'POST':
        name = request.form['name'].strip()
        existing = Customer.query.filter(
            Customer.id != customer.id, Customer.status == 'active',
            db.func.lower(Customer.name) == name.lower()
        ).first()
        if existing:
            flash(f'A customer named "{name}" already exists ({existing.customer_code}).', 'warning')
            return redirect(url_for('customers.edit', customer_id=customer.id))

        customer.name = name
        customer.phone = request.form.get('phone')
        customer.email = request.form.get('email')
        customer.address = request.form.get('address')
        customer.location = request.form.get('location')
        customer.gps_latitude = request.form.get('gps_latitude') or None
        customer.gps_longitude = request.form.get('gps_longitude') or None
        customer.customer_type = request.form.get('customer_type', 'retail')
        customer.credit_limit = float(request.form.get('credit_limit') or 0)
        customer.assigned_route_id = request.form.get('assigned_route_id') or None
        customer.assigned_van_id = request.form.get('assigned_van_id') or None
        customer.sales_rep_id = request.form.get('sales_rep_id') or None
        customer.status = request.form.get('status', 'active')
        customer.notes = request.form.get('notes')
        db.session.commit()
        flash('Customer updated!', 'success')
        return redirect(url_for('customers.view', customer_id=customer.id))

    return render_template('customers/form.html', customer=customer, vans=vans, routes=routes, sales_reps=sales_reps)


@customers_bp.route('/<int:customer_id>/delete', methods=['POST'])
@login_required
def delete(customer_id):
    if not current_user.can_write('customers'):
        return jsonify({'error': 'Permission denied'}), 403
    customer = Customer.query.get_or_404(customer_id)
    if current_user.scope('customers') == 'own' and customer.sales_rep_id != current_user.id:
        return jsonify({'error': 'Access denied'}), 403
    customer.status = 'inactive'
    db.session.commit()
    return jsonify({'success': True})


@customers_bp.route('/search')
@login_required
def search():
    if not current_user.can_access('customers'):
        return jsonify([]), 403
    q = request.args.get('q', '').strip()
    customers = Customer.query.filter(
        Customer.name.ilike(f'%{q}%') |
        Customer.customer_code.ilike(f'%{q}%') |
        Customer.phone.ilike(f'%{q}%')
    ).filter_by(status='active').limit(20).all()
    if current_user.scope('customers') == 'own':
        customers = [c for c in customers if c.sales_rep_id == current_user.id]
    return jsonify([c.to_dict() for c in customers])
