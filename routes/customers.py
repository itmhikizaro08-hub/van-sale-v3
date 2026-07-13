from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
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
    if not current_user.can_add:
        flash('Permission denied.', 'danger')
        return redirect(url_for('customers.index'))

    vans = Van.query.filter_by(status='active').all()
    routes = Route.query.filter_by(status='active').all()
    sales_reps = User.query.filter(User.role.in_(['sales_rep', 'supervisor', 'manager'])).all()

    if request.method == 'POST':
        customer = Customer(
            customer_code=_next_code(),
            name=request.form['name'],
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
    return render_template('customers/view.html', customer=customer, recent_sales=recent_sales,
                           recent_payments=recent_payments, recent_visits=recent_visits)


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
    if not current_user.can_edit:
        flash('Permission denied.', 'danger')
        return redirect(url_for('customers.index'))

    customer = Customer.query.get_or_404(customer_id)
    vans = Van.query.filter_by(status='active').all()
    routes = Route.query.filter_by(status='active').all()
    sales_reps = User.query.filter(User.role.in_(['sales_rep', 'supervisor', 'manager'])).all()

    if request.method == 'POST':
        customer.name = request.form['name']
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
    if not current_user.can_delete:
        return jsonify({'error': 'Permission denied'}), 403
    customer = Customer.query.get_or_404(customer_id)
    customer.status = 'inactive'
    db.session.commit()
    flash('Customer deactivated.', 'success')
    return redirect(url_for('customers.index'))


@customers_bp.route('/search')
@login_required
def search():
    q = request.args.get('q', '').strip()
    customers = Customer.query.filter(
        Customer.name.ilike(f'%{q}%') |
        Customer.customer_code.ilike(f'%{q}%') |
        Customer.phone.ilike(f'%{q}%')
    ).filter_by(status='active').limit(20).all()
    return jsonify([c.to_dict() for c in customers])
