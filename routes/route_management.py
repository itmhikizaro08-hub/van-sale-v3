"""Route management blueprint"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from app import db
from models.van import Route, CustomerVisit
from models.customer import Customer
from models.sale import Sale

routes_bp = Blueprint('routes', __name__)


def _date_range():
    start = request.args.get('start', (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end   = request.args.get('end',   datetime.utcnow().strftime('%Y-%m-%d'))
    return start, end


@routes_bp.route('/')
@login_required
def index():
    if not current_user.can_access('routes'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    start, end = _date_range()
    routes = Route.query.order_by(Route.route_name).all()
    active_count = sum(1 for r in routes if r.status == 'active')
    total_customers = sum(r.customers.count() for r in routes)

    for r in routes:
        r.total_sales = db.session.query(db.func.sum(Sale.total_amount)).join(
            Customer, Sale.customer_id == Customer.id
        ).filter(
            Customer.assigned_route_id == r.id, Sale.status == 'completed',
            Sale.sale_date >= start, Sale.sale_date <= end + ' 23:59:59'
        ).scalar() or 0
        r.total_outstanding = db.session.query(db.func.sum(Customer.outstanding_balance)).filter(
            Customer.assigned_route_id == r.id
        ).scalar() or 0

    total_sales_all       = round(sum(r.total_sales for r in routes), 2)
    total_outstanding_all = round(sum(r.total_outstanding for r in routes), 2)
    by_route = sorted(
        [(r.route_name, r.total_sales) for r in routes if r.total_sales > 0],
        key=lambda x: x[1], reverse=True
    )

    customers_geo = [
        {
            'name': c.name,
            'phone': c.phone or '',
            'address': c.address or c.location or '',
            'lat': c.gps_latitude,
            'lng': c.gps_longitude,
            'outstanding': c.outstanding_balance,
            'route': c.route.route_name if c.route else None,
            'url': url_for('customers.view', customer_id=c.id)
        }
        for c in Customer.query.filter_by(status='active').all()
        if c.gps_latitude and c.gps_longitude
    ]

    return render_template('routes/index.html', routes=routes,
        active_count=active_count, total_customers=total_customers, customers_geo=customers_geo,
        total_sales_all=total_sales_all, total_outstanding_all=total_outstanding_all,
        by_route=by_route, start=start, end=end)


@routes_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if not current_user.can_write('routes'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('routes.index'))

    if request.method == 'POST':
        last = Route.query.order_by(Route.id.desc()).first()
        n = (last.id + 1) if last else 1
        route = Route(
            route_code=f'RT{n:03d}',
            route_name=request.form['route_name'],
            description=request.form.get('description'),
            area=request.form.get('area'),
            status=request.form.get('status', 'active')
        )
        db.session.add(route)
        db.session.commit()
        flash(f'Route {route.route_name} added!', 'success')
        return redirect(url_for('routes.index'))
    return render_template('routes/form.html', route=None)


@routes_bp.route('/<int:route_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(route_id):
    if not current_user.can_write('routes'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('routes.index'))

    route = Route.query.get_or_404(route_id)
    if request.method == 'POST':
        route.route_name = request.form['route_name']
        route.description = request.form.get('description')
        route.area = request.form.get('area')
        route.status = request.form.get('status', 'active')
        db.session.commit()
        flash('Route updated!', 'success')
        return redirect(url_for('routes.index'))
    return render_template('routes/form.html', route=route)


@routes_bp.route('/<int:route_id>')
@login_required
def view(route_id):
    if not current_user.can_access('routes'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    route = Route.query.get_or_404(route_id)
    customers = Customer.query.filter_by(assigned_route_id=route_id).all()
    customers_geo = [
        {
            'name': c.name,
            'phone': c.phone or '',
            'address': c.address or c.location or '',
            'lat': c.gps_latitude,
            'lng': c.gps_longitude,
            'outstanding': c.outstanding_balance,
            'url': url_for('customers.view', customer_id=c.id)
        }
        for c in customers if c.gps_latitude and c.gps_longitude
    ]
    return render_template('routes/view.html', route=route, customers=customers, customers_geo=customers_geo)
