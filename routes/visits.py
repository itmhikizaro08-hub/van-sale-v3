from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from app import db
from models.van import CustomerVisit, Route
from models.customer import Customer

visits_bp = Blueprint('visits', __name__)


@visits_bp.route('/')
@login_required
def index():
    if not current_user.can_access('visits'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    start = request.args.get('start', (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end   = request.args.get('end',   datetime.utcnow().strftime('%Y-%m-%d'))

    q = CustomerVisit.query.filter(
        CustomerVisit.visit_date >= start,
        CustomerVisit.visit_date <= end + ' 23:59:59'
    )
    if current_user.scope('visits') == 'own':
        q = q.filter_by(sales_rep_id=current_user.id)
    visits = q.order_by(CustomerVisit.visit_date.desc()).limit(200).all()

    completed_count = sum(1 for v in visits if v.status == 'completed')

    visits_geo = [
        {
            'customer': v.customer.name if v.customer else 'Unknown',
            'rep': v.sales_rep.full_name if v.sales_rep else '—',
            'date': v.visit_date.strftime('%d %b %Y %H:%M') if v.visit_date else '',
            'status': v.status,
            'outcome': (v.outcome or '').replace('_', ' ').title(),
            'lat': v.gps_latitude,
            'lng': v.gps_longitude,
            'url': url_for('customers.view', customer_id=v.customer_id)
        }
        for v in visits if v.gps_latitude and v.gps_longitude
    ]

    return render_template('visits/index.html', visits=visits, start=start, end=end,
        completed_count=completed_count, visits_geo=visits_geo)


@visits_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if not current_user.can_write('visits'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('visits.index'))
    customers = Customer.query.filter_by(status='active').order_by(Customer.name).all()
    routes = Route.query.filter_by(status='active').all()
    if request.method == 'POST':
        visit = CustomerVisit(
            customer_id=request.form['customer_id'],
            route_id=request.form.get('route_id') or None,
            sales_rep_id=current_user.id,
            visit_date=datetime.utcnow(),
            status='planned',
            notes=request.form.get('notes')
        )
        db.session.add(visit)
        db.session.commit()
        flash('Visit scheduled!', 'success')
        return redirect(url_for('visits.index'))
    return render_template('visits/add.html', customers=customers, routes=routes)


@visits_bp.route('/<int:visit_id>/checkin', methods=['POST'])
@login_required
def checkin(visit_id):
    if not current_user.can_write('visits'):
        return jsonify({'error': 'Permission denied'}), 403
    visit = CustomerVisit.query.get_or_404(visit_id)
    if current_user.scope('visits') == 'own' and visit.sales_rep_id != current_user.id:
        return jsonify({'error': 'Access denied'}), 403
    data = request.get_json() or {}
    visit.check_in_time = datetime.utcnow()
    visit.gps_latitude = data.get('lat')
    visit.gps_longitude = data.get('lng')
    visit.customer.last_visit_date = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True})


@visits_bp.route('/<int:visit_id>/checkout', methods=['POST'])
@login_required
def checkout(visit_id):
    if not current_user.can_write('visits'):
        return jsonify({'error': 'Permission denied'}), 403
    visit = CustomerVisit.query.get_or_404(visit_id)
    if current_user.scope('visits') == 'own' and visit.sales_rep_id != current_user.id:
        return jsonify({'error': 'Access denied'}), 403
    if not visit.check_in_time:
        return jsonify({'error': 'Visit must be checked in first.'}), 400
    data = request.get_json() or {}
    visit.check_out_time = datetime.utcnow()
    visit.outcome = data.get('outcome', 'no_sale')
    visit.notes = data.get('notes', visit.notes)
    visit.status = 'completed'
    db.session.commit()
    return jsonify({'success': True})


@visits_bp.route('/today')
@login_required
def today():
    from models.customer import Customer
    from models.van import CustomerVisit, RouteAssignment
    from datetime import date

    today_date = date.today()
    visited_ids = set(
        v.customer_id for v in CustomerVisit.query.filter_by(
            sales_rep_id=current_user.id
        ).filter(db.func.date(CustomerVisit.visit_date) == today_date).all()
    )

    assignments = []
    if current_user.scope('visits') == 'own':
        assignments = RouteAssignment.query.filter_by(sales_rep_id=current_user.id).all()

    if assignments:
        # Rep has explicit route coverage — show every customer on each
        # assigned route (not just ones nominally owned via sales_rep_id),
        # grouped by route so a rep serving several routes sees all of them.
        route_groups = [
            {
                'route': a.route,
                'customers': Customer.query.filter_by(
                    status='active', assigned_route_id=a.route_id
                ).order_by(Customer.name).all()
            }
            for a in assignments
        ]
        return render_template('visits/today.html', route_groups=route_groups,
            customers=None, visited_ids=visited_ids)

    # No route assignments yet — original behavior, unchanged: all customers
    # this user owns (or all active customers, for non-'own' scopes), ungrouped.
    q = Customer.query.filter_by(status='active')
    if current_user.scope('visits') == 'own':
        q = q.filter_by(sales_rep_id=current_user.id)
    customers = q.order_by(Customer.name).all()
    return render_template('visits/today.html', route_groups=None,
        customers=customers, visited_ids=visited_ids)


@visits_bp.route('/mark', methods=['POST'])
@login_required
def mark():
    if not current_user.can_write('visits'):
        return jsonify({'error': 'Permission denied'}), 403
    data = request.get_json()
    if not data or not data.get('customer_id'):
        return jsonify({'error': 'customer_id required'}), 400
    try:
        customer = Customer.query.get(data['customer_id'])
        visit = CustomerVisit(
            customer_id=data['customer_id'],
            route_id=customer.assigned_route_id if customer else None,
            sales_rep_id=current_user.id,
            gps_latitude=data.get('latitude'),
            gps_longitude=data.get('longitude'),
            visit_date=datetime.utcnow(),
            check_in_time=datetime.utcnow(),
            status='completed',
            outcome=data.get('outcome', 'visited')
        )
        db.session.add(visit)
        # checkin() updates this too — without it, a visit logged through
        # this quick-mark flow leaves Customer.last_visit_date stale, which
        # customers/view.html and reports read directly.
        if customer:
            customer.last_visit_date = datetime.utcnow()
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
