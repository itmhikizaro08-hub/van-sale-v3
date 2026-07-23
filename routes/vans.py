"""Van Management blueprint — fleet CRUD, loading sheets, and stock offload.

Loading (warehouse → van) and Offload (van → warehouse) both operate on the
same VanStock ledger as the per-van drill-down page (`view()` below), so they
live together in one blueprint instead of three scattered ones.
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from app import db
from models.van import Van, Driver, Route, CustomerVisit
from models.customer import Customer
from models.user import User
from models.product import Product
from models.notification import VanStock, InventoryMovement
from models.van_management import LoadingSheet, LoadingSheetItem, StockOffload, StockOffloadItem
from services.sequence import next_loading_sheet_number, next_stock_offload_number
from services.rbac import require_module

vans_bp = Blueprint('vans', __name__)


# ── Fleet CRUD ───────────────────────────────────────────────────────────────

@vans_bp.route('/')
@login_required
def index():
    if not current_user.can_access('vans'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    vans = Van.query.order_by(Van.van_number).all()
    active_count = sum(1 for v in vans if v.status == 'active')
    assigned_count = sum(1 for v in vans if v.driver_id)
    maintenance_count = sum(1 for v in vans if v.status == 'maintenance')

    value_by_van, qty_by_van = {}, {}
    for vs in VanStock.query.filter(VanStock.quantity > 0).all():
        value = vs.quantity * (vs.product.cost_price if vs.product else 0)
        value_by_van[vs.van_id] = value_by_van.get(vs.van_id, 0) + value
        qty_by_van[vs.van_id] = qty_by_van.get(vs.van_id, 0) + vs.quantity

    for v in vans:
        v.stock_value = round(value_by_van.get(v.id, 0), 2)
        v.stock_qty = qty_by_van.get(v.id, 0)

    total_stock_value = round(sum(value_by_van.values()), 2)
    by_van_chart = sorted(
        [(v.van_number, v.stock_value) for v in vans if v.stock_value > 0],
        key=lambda x: x[1], reverse=True
    )

    return render_template('vans/index.html', vans=vans, active_count=active_count,
        assigned_count=assigned_count, maintenance_count=maintenance_count,
        total_stock_value=total_stock_value, by_van_chart=by_van_chart)


@vans_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if not current_user.can_write('vans'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('vans.index'))

    drivers = Driver.query.filter_by(status='active').all()
    routes = Route.query.filter_by(status='active').all()
    if request.method == 'POST':
        van_number = request.form['van_number'].strip()
        existing = Van.query.filter(db.func.lower(Van.van_number) == van_number.lower()).first()
        if existing:
            flash(f'A van numbered "{van_number}" already exists. Edit it instead, or use a different number.', 'warning')
            return redirect(url_for('vans.add'))

        van = Van(
            van_number=van_number,
            registration_number=request.form.get('registration_number'),
            make=request.form.get('make'),
            model=request.form.get('model'),
            year=request.form.get('year') or None,
            driver_id=request.form.get('driver_id') or None,
            route_id=request.form.get('route_id') or None,
            status=request.form.get('status', 'active'),
            notes=request.form.get('notes')
        )
        db.session.add(van)
        db.session.commit()
        flash(f'Van {van.van_number} added!', 'success')
        return redirect(url_for('vans.index'))
    return render_template('vans/form.html', van=None, drivers=drivers, routes=routes)


@vans_bp.route('/<int:van_id>')
@login_required
def view(van_id):
    if not current_user.can_access('vans'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    van = Van.query.get_or_404(van_id)

    start = request.args.get('start', (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end   = request.args.get('end',   datetime.utcnow().strftime('%Y-%m-%d'))
    end_bound = end + ' 23:59:59'

    loading_sheets = LoadingSheet.query.filter(
        LoadingSheet.van_id == van_id,
        LoadingSheet.created_at >= start, LoadingSheet.created_at <= end_bound
    ).order_by(LoadingSheet.created_at.desc()).all()

    offloads = StockOffload.query.filter(
        StockOffload.van_id == van_id,
        StockOffload.created_at >= start, StockOffload.created_at <= end_bound
    ).order_by(StockOffload.created_at.desc()).all()

    van_stock = VanStock.query.filter(
        VanStock.van_id == van_id, VanStock.quantity > 0
    ).order_by(VanStock.quantity.desc()).all()

    stock_value = round(sum(
        vs.quantity * (vs.product.cost_price if vs.product else 0) for vs in van_stock
    ), 2)
    loaded_value = round(sum(s.total_value for s in loading_sheets), 2)
    offload_count = len(offloads)

    return render_template('vans/view.html', van=van, start=start, end=end,
        loading_sheets=loading_sheets, offloads=offloads, van_stock=van_stock,
        stock_value=stock_value, loaded_value=loaded_value, offload_count=offload_count)


@vans_bp.route('/<int:van_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(van_id):
    if not current_user.can_write('vans'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('vans.index'))

    van = Van.query.get_or_404(van_id)
    drivers = Driver.query.filter_by(status='active').all()
    routes = Route.query.filter_by(status='active').all()
    if request.method == 'POST':
        van_number = request.form['van_number'].strip()
        existing = Van.query.filter(
            Van.id != van.id, db.func.lower(Van.van_number) == van_number.lower()
        ).first()
        if existing:
            flash(f'A van numbered "{van_number}" already exists.', 'warning')
            return redirect(url_for('vans.edit', van_id=van.id))

        van.van_number = van_number
        van.registration_number = request.form.get('registration_number')
        van.make = request.form.get('make')
        van.model = request.form.get('model')
        van.year = request.form.get('year') or None
        van.driver_id = request.form.get('driver_id') or None
        van.route_id = request.form.get('route_id') or None
        van.status = request.form.get('status', 'active')
        van.notes = request.form.get('notes')
        db.session.commit()
        flash('Van updated!', 'success')
        return redirect(url_for('vans.view', van_id=van.id))
    return render_template('vans/form.html', van=van, drivers=drivers, routes=routes)


@vans_bp.route('/<int:van_id>/delete', methods=['POST'])
@login_required
def delete(van_id):
    if not current_user.can_write('vans'):
        return jsonify({'error': 'Permission denied'}), 403
    van = Van.query.get_or_404(van_id)
    van.status = 'inactive'
    db.session.commit()
    return jsonify({'success': True})


@vans_bp.route('/stock')
@login_required
def stock():
    if not current_user.can_access('van_stock'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    q = VanStock.query.filter(VanStock.quantity > 0)
    van_filter_id = None
    rep_filter_id = None
    vans = reps = []
    if current_user.scope('van_stock') == 'own':
        q = q.filter_by(sales_rep_id=current_user.id)
    else:
        van_filter_id = request.args.get('van_id', type=int)
        rep_filter_id = request.args.get('rep_id', type=int)
        if van_filter_id:
            q = q.filter_by(van_id=van_filter_id)
        if rep_filter_id:
            q = q.filter_by(sales_rep_id=rep_filter_id)
        vans = Van.query.filter_by(status='active').order_by(Van.van_number).all()
        rep_ids_with_stock = {vs.sales_rep_id for vs in VanStock.query.filter(
            VanStock.quantity > 0, VanStock.sales_rep_id.isnot(None)
        ).all()}
        reps = User.query.filter(User.id.in_(rep_ids_with_stock)).order_by(User.full_name).all()
    stocks = q.all()

    total_qty = round(sum(vs.quantity for vs in stocks), 2)
    total_value = round(sum(vs.quantity * (vs.product.cost_price if vs.product else 0) for vs in stocks), 2)
    rep_count = len({vs.sales_rep_id for vs in stocks if vs.sales_rep_id})

    return render_template('vans/stock.html', stocks=stocks,
        total_qty=total_qty, total_value=total_value, rep_count=rep_count,
        vans=vans, reps=reps, van_filter_id=van_filter_id, rep_filter_id=rep_filter_id)


@vans_bp.route('/stock/statement/<int:van_id>/<int:rep_id>')
@login_required
def stock_statement(van_id, rep_id):
    if not current_user.can_access('van_stock'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    if current_user.scope('van_stock') == 'own' and rep_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('vans.stock'))

    van = Van.query.get_or_404(van_id)
    rep = User.query.get_or_404(rep_id)
    product_id = request.args.get('product_id', type=int)
    product = Product.query.get_or_404(product_id) if product_id else None

    start = request.args.get('start', (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end = request.args.get('end', datetime.utcnow().strftime('%Y-%m-%d'))

    from services.statements import van_stock_ledger_rows
    rows = van_stock_ledger_rows(van_id, rep_id, start, end, product_id=product_id)

    current_stock_q = VanStock.query.filter_by(van_id=van_id, sales_rep_id=rep_id).filter(
        VanStock.quantity > 0
    )
    if product_id:
        current_stock_q = current_stock_q.filter_by(product_id=product_id)
    current_stock = current_stock_q.order_by(VanStock.quantity.desc()).all()
    current_total_qty = round(sum(vs.quantity for vs in current_stock), 2)
    current_total_value = round(sum(
        vs.quantity * (vs.product.cost_price if vs.product else 0) for vs in current_stock
    ), 2)

    return render_template('vans/stock_statement.html', van=van, rep=rep, product=product, rows=rows,
        current_stock=current_stock, current_total_qty=current_total_qty,
        current_total_value=current_total_value, start=start, end=end)


@vans_bp.route('/stock/statement/<int:van_id>/<int:rep_id>/pdf')
@login_required
def stock_statement_pdf(van_id, rep_id):
    if not current_user.can_access('van_stock'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    if current_user.scope('van_stock') == 'own' and rep_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('vans.stock'))

    from flask import make_response
    van = Van.query.get_or_404(van_id)
    rep = User.query.get_or_404(rep_id)
    product_id = request.args.get('product_id', type=int)
    product = Product.query.get_or_404(product_id) if product_id else None

    start = request.args.get('start', (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end = request.args.get('end', datetime.utcnow().strftime('%Y-%m-%d'))

    from services.statements import van_stock_ledger_rows
    rows = van_stock_ledger_rows(van_id, rep_id, start, end, product_id=product_id)

    current_stock_q = VanStock.query.filter_by(van_id=van_id, sales_rep_id=rep_id).filter(
        VanStock.quantity > 0
    )
    if product_id:
        current_stock_q = current_stock_q.filter_by(product_id=product_id)
    current_stock = current_stock_q.order_by(VanStock.quantity.desc()).all()
    current_total_qty = round(sum(vs.quantity for vs in current_stock), 2)
    current_total_value = round(sum(
        vs.quantity * (vs.product.cost_price if vs.product else 0) for vs in current_stock
    ), 2)

    from services.pdf_service import generate_van_stock_statement_pdf
    from models.settings import Settings
    s = Settings.get()
    company = {'name': s.company_name, 'address': s.company_address,
               'phone': s.company_phone, 'email': s.company_email}

    pdf_bytes = generate_van_stock_statement_pdf(
        van, rep, product, company, start, end, current_stock, current_total_qty,
        current_total_value, rows, show_value=current_user.see_cost_prices()
    )
    response = make_response(pdf_bytes)
    response.headers['Content-Type'] = 'application/pdf'
    filename = f'van_stock_statement_{van.van_number}_{rep.full_name.replace(" ", "_")}_{start}_to_{end}.pdf'
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response


# ── Loading Sheets (warehouse → van) ─────────────────────────────────────────

@vans_bp.route('/loading')
@login_required
@require_module('loading')
def loading_index():
    route_id = request.args.get('route_id', type=int)
    routes = []
    if current_user.scope('loading') == 'own':
        sheets = LoadingSheet.query.filter_by(
            sales_rep_id=current_user.id
        ).order_by(LoadingSheet.created_at.desc()).limit(100).all()
    else:
        q = LoadingSheet.query.join(Van, LoadingSheet.van_id == Van.id)
        if route_id:
            q = q.filter(Van.route_id == route_id)
        sheets = q.order_by(LoadingSheet.created_at.desc()).limit(100).all()
        routes = Route.query.filter_by(status='active').order_by(Route.route_name).all()

    return render_template('vans/loading_index.html', sheets=sheets, routes=routes, route_id=route_id)


@vans_bp.route('/loading/new', methods=['GET', 'POST'])
@login_required
@require_module('loading', need_write=True)
def loading_new():
    vans = Van.query.filter_by(status='active').all()
    reps = User.query.filter(
        User.role.in_(['sales_rep', 'supervisor']),
        User.is_active == True
    ).all()
    products = Product.query.filter_by(status='active').filter(
        Product.stock_quantity > 0
    ).order_by(Product.product_name).all()

    # Format: { "vanId_repId": { productId: qty, ... }, ... }
    van_stock_data = {}
    all_van_stocks = VanStock.query.filter(VanStock.quantity > 0).all()
    for vs in all_van_stocks:
        key = f"{vs.van_id}_{vs.sales_rep_id}"
        if key not in van_stock_data:
            van_stock_data[key] = {}
        van_stock_data[key][vs.product_id] = vs.quantity

    if request.method == 'POST':
        van_id       = request.form.get('van_id')
        sales_rep_id = request.form.get('sales_rep_id')
        reference_note = request.form.get('reference_note')

        if not van_id or not sales_rep_id:
            flash('Van and Sales Rep are required.', 'danger')
            return redirect(url_for('vans.loading_new'))

        sheet = LoadingSheet(
            sheet_number=next_loading_sheet_number(),
            van_id=van_id,
            sales_rep_id=sales_rep_id,
            loading_date=datetime.utcnow().date(),
            notes=request.form.get('notes'),
            reference_note=reference_note,
            issued_by_id=current_user.id,
            status='issued'
        )
        db.session.add(sheet)
        db.session.flush()

        product_ids = request.form.getlist('product_id[]')
        quantities  = request.form.getlist('quantity[]')
        has_items = False

        for pid, qty_str in zip(product_ids, quantities):
            if not pid or not qty_str:
                continue
            try:
                qty = int(qty_str)
            except ValueError:
                db.session.rollback()
                flash(f'"{qty_str}" is not a valid quantity.', 'danger')
                return redirect(url_for('vans.loading_new'))
            if qty <= 0:
                continue

            product = Product.query.get(pid)
            if not product:
                continue

            if product.stock_quantity < qty:
                db.session.rollback()
                flash(f'Insufficient warehouse stock for {product.product_name}: have {product.stock_quantity}, need {qty}.', 'danger')
                return redirect(url_for('vans.loading_new'))

            db.session.add(LoadingSheetItem(
                sheet_id=sheet.id,
                product_id=int(pid),
                quantity=qty
            ))
            has_items = True

            before = product.stock_quantity
            product.stock_quantity -= qty
            db.session.add(InventoryMovement(
                product_id=product.id, movement_type='transfer_out',
                quantity=-qty, quantity_before=before, quantity_after=product.stock_quantity,
                van_id=int(van_id), reference_id=sheet.id, reference_type='loading_sheet',
                reference_note=reference_note,
                notes=f'Loaded to van via {sheet.sheet_number}',
                created_by_id=current_user.id
            ))

            vs = VanStock.query.filter_by(
                van_id=int(van_id),
                sales_rep_id=int(sales_rep_id),
                product_id=int(pid)
            ).first()
            if vs:
                vs.quantity += qty
            else:
                db.session.add(VanStock(
                    van_id=int(van_id),
                    sales_rep_id=int(sales_rep_id),
                    product_id=int(pid),
                    quantity=qty
                ))

        if not has_items:
            db.session.rollback()
            flash('Add at least one product with quantity > 0.', 'danger')
            return redirect(url_for('vans.loading_new'))

        sheet.status = 'acknowledged'
        db.session.commit()

        flash(f'Loading sheet {sheet.sheet_number} issued successfully!', 'success')
        return redirect(url_for('vans.loading_view', sheet_id=sheet.id))

    return render_template('vans/loading_new.html',
        vans=vans, reps=reps, products=products,
        van_stock_json=van_stock_data)


@vans_bp.route('/loading/<int:sheet_id>')
@login_required
@require_module('loading')
def loading_view(sheet_id):
    sheet = LoadingSheet.query.get_or_404(sheet_id)

    if current_user.scope('loading') == 'own' and sheet.sales_rep_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('vans.loading_index'))

    return render_template('vans/loading_view.html', sheet=sheet)


@vans_bp.route('/loading/api/van-stock/<int:van_id>/<int:rep_id>')
@login_required
@require_module('loading')
def loading_api_van_stock(van_id, rep_id):
    """API endpoint — returns current custody for a van+rep pair."""
    stocks = VanStock.query.filter_by(
        van_id=van_id, sales_rep_id=rep_id
    ).filter(VanStock.quantity > 0).all()

    return jsonify([{
        'product_id':   vs.product_id,
        'product_name': vs.product.product_name if vs.product else '—',
        'quantity':     vs.quantity
    } for vs in stocks])


# ── Stock Offload (van → warehouse) ──────────────────────────────────────────

@vans_bp.route('/offload')
@login_required
@require_module('stock_offload')
def offload_index():
    if current_user.scope('stock_offload') == 'own':
        van_stock = VanStock.query.filter_by(
            sales_rep_id=current_user.id).filter(VanStock.quantity > 0).all()
        offloads = StockOffload.query.filter_by(
            sales_rep_id=current_user.id).order_by(StockOffload.created_at.desc()).limit(30).all()
        return render_template('vans/offload_index.html', own_scope=True,
            van_stock=van_stock, offloads=offloads)

    pending = StockOffload.query.filter_by(status='pending').order_by(
        StockOffload.created_at).all()
    recent = StockOffload.query.filter(StockOffload.status != 'pending').order_by(
        StockOffload.confirmed_at.desc()).limit(30).all()
    return render_template('vans/offload_index.html', own_scope=False,
        pending=pending, recent=recent)


@vans_bp.route('/offload/<int:offload_id>')
@login_required
@require_module('stock_offload')
def offload_view(offload_id):
    offload = StockOffload.query.get_or_404(offload_id)

    if current_user.scope('stock_offload') == 'own' and offload.sales_rep_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('vans.offload_index'))

    return render_template('vans/offload_view.html', offload=offload)


@vans_bp.route('/offload/submit', methods=['POST'])
@login_required
@require_module('stock_offload', need_write=True)
def offload_submit():
    product_ids = request.form.getlist('product_id[]')
    quantities = request.form.getlist('quantity[]')

    items_data = []
    for pid, qty_str in zip(product_ids, quantities):
        if not pid or not qty_str:
            continue
        try:
            qty = round(float(qty_str), 3)
        except ValueError:
            flash(f'"{qty_str}" is not a valid quantity.', 'danger')
            return redirect(url_for('vans.offload_index'))
        if qty <= 0:
            continue
        vs = VanStock.query.filter_by(
            sales_rep_id=current_user.id, product_id=int(pid)).first()
        held = vs.quantity if vs else 0
        if qty > held:
            flash(f'Cannot offload {qty} of {vs.product.product_name if vs and vs.product else "a product"} — you only hold {held}.', 'danger')
            return redirect(url_for('vans.offload_index'))
        items_data.append((int(pid), qty, vs.van_id))

    if not items_data:
        flash('Select at least one product with quantity > 0.', 'warning')
        return redirect(url_for('vans.offload_index'))

    offload = StockOffload(
        offload_number=next_stock_offload_number(),
        sales_rep_id=current_user.id,
        van_id=items_data[0][2],
        status='pending',
        notes=request.form.get('notes')
    )
    db.session.add(offload)
    db.session.flush()
    for pid, qty, _van_id in items_data:
        db.session.add(StockOffloadItem(
            offload_id=offload.id, product_id=pid, quantity_declared=qty))
    db.session.commit()
    flash(f'Stock offload {offload.offload_number} submitted for warehouse confirmation.', 'success')
    return redirect(url_for('vans.offload_index'))


@vans_bp.route('/offload/<int:offload_id>/confirm', methods=['POST'])
@login_required
@require_module('stock_offload', need_approve=True)
def offload_confirm(offload_id):
    offload = StockOffload.query.get_or_404(offload_id)
    if offload.status != 'pending':
        flash('This offload has already been processed.', 'warning')
        return redirect(url_for('vans.offload_index'))

    any_mismatch = False
    for item in offload.items:
        received = request.form.get(f'received_{item.id}', type=float)
        if received is None:
            received = item.quantity_declared
        # Clamp to [0, declared] — a warehouse manager typing a value larger
        # than what was declared must not be able to inflate warehouse stock
        # beyond what the rep actually said they were returning.
        received = round(min(max(0, received), item.quantity_declared), 3)
        item.quantity_received = received
        if abs(received - item.quantity_declared) > 0.001:
            any_mismatch = True

        vs = VanStock.query.filter_by(
            sales_rep_id=offload.sales_rep_id, product_id=item.product_id).first()
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

    offload.status = 'discrepancy' if any_mismatch else 'confirmed'
    offload.confirmed_by_id = current_user.id
    offload.confirmed_at = datetime.utcnow()
    note = request.form.get('notes')
    if note:
        offload.notes = (offload.notes + '\n' if offload.notes else '') + note
    db.session.commit()

    if offload.status == 'discrepancy':
        flash(f'Offload {offload.offload_number} confirmed with a quantity mismatch — remainder stays on the rep\'s liability.', 'warning')
    else:
        flash(f'Offload {offload.offload_number} confirmed — stock received in full.', 'success')
    return redirect(url_for('vans.offload_index'))
