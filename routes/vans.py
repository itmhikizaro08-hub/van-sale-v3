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

    total_stock_value = round(sum(
        vs.quantity * (vs.product.cost_price if vs.product else 0)
        for vs in VanStock.query.filter(VanStock.quantity > 0).all()
    ), 2)

    return render_template('vans/index.html', vans=vans, active_count=active_count,
        assigned_count=assigned_count, total_stock_value=total_stock_value)


@vans_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if not current_user.can_write('vans'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('vans.index'))

    drivers = Driver.query.filter_by(status='active').all()
    routes = Route.query.filter_by(status='active').all()
    if request.method == 'POST':
        van = Van(
            van_number=request.form['van_number'],
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
        van.van_number = request.form['van_number']
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


@vans_bp.route('/stock')
@login_required
def stock():
    if not current_user.can_access('van_stock'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    q = VanStock.query.filter(VanStock.quantity > 0)
    if current_user.scope('van_stock') == 'own':
        q = q.filter_by(sales_rep_id=current_user.id)
    stocks = q.all()
    return render_template('vans/stock.html', stocks=stocks)


# ── Loading Sheets (warehouse → van) ─────────────────────────────────────────

@vans_bp.route('/loading')
@login_required
@require_module('loading')
def loading_index():
    if current_user.scope('loading') == 'own':
        sheets = LoadingSheet.query.filter_by(
            sales_rep_id=current_user.id
        ).order_by(LoadingSheet.created_at.desc()).limit(100).all()
    else:
        sheets = LoadingSheet.query.order_by(
            LoadingSheet.created_at.desc()).limit(100).all()

    return render_template('vans/loading_index.html', sheets=sheets)


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

            product.stock_quantity -= qty

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
