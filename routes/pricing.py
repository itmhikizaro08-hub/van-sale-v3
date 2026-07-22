"""
Pricing Management
==================
Admin/Manager only. Set the company selling price (the enforced floor sales
reps cannot sell below) and cost price per product, with a mandatory reason
logged to PriceHistory on every change.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, make_response
from flask_login import login_required, current_user
from app import db
from models.product import Product
from models.pricing import PriceHistory

pricing_bp = Blueprint('pricing', __name__)


def _can_manage_pricing():
    return current_user.role in ('admin', 'manager') and current_user.can_write('products')


@pricing_bp.route('/')
@login_required
def index():
    if not _can_manage_pricing():
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    products = Product.query.filter_by(status='active').order_by(Product.product_name).all()
    return render_template('pricing/index.html', products=products)


@pricing_bp.route('/<int:product_id>/history')
@login_required
def history(product_id):
    if not _can_manage_pricing():
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    product = Product.query.get_or_404(product_id)
    return render_template('pricing/history.html', product=product)


@pricing_bp.route('/<int:product_id>/update', methods=['POST'])
@login_required
def update(product_id):
    if not _can_manage_pricing():
        return jsonify({'error': 'Access denied'}), 403

    product = Product.query.get_or_404(product_id)
    data = request.get_json() or {}
    reason = (data.get('reason') or '').strip()
    if not reason:
        return jsonify({'error': 'A reason is required.'}), 400

    try:
        new_company_price = round(float(data['company_price']), 2)
        new_cost_price = round(float(data['cost_price']), 2)
    except (TypeError, ValueError, KeyError):
        return jsonify({'error': 'Invalid price value.'}), 400

    if new_company_price < 0 or new_cost_price < 0:
        return jsonify({'error': 'Prices cannot be negative.'}), 400

    old_company_price = product.selling_price
    old_cost_price = product.cost_price

    if new_company_price == old_company_price and new_cost_price == old_cost_price:
        return jsonify({'error': 'No change detected.'}), 400

    product.selling_price = new_company_price
    product.cost_price = new_cost_price

    db.session.add(PriceHistory(
        product_id=product.id,
        old_company_price=old_company_price, new_company_price=new_company_price,
        old_cost_price=old_cost_price, new_cost_price=new_cost_price,
        reason=reason, changed_by_id=current_user.id
    ))
    db.session.commit()

    return jsonify({'success': True, 'message': f'{product.product_name} price updated.'})


@pricing_bp.route('/bulk-update', methods=['POST'])
@login_required
def bulk_update():
    if not _can_manage_pricing():
        return jsonify({'error': 'Access denied'}), 403

    reason = (request.form.get('reason') or '').strip()
    if not reason:
        return jsonify({'error': 'A reason is required.'}), 400

    product_ids = request.form.getlist('product_id[]')
    new_prices = request.form.getlist('new_company_price[]')

    updated = 0
    for pid, price in zip(product_ids, new_prices):
        if not price or not pid.isdigit():
            continue
        product = Product.query.get(int(pid))
        if not product:
            continue
        try:
            new_company_price = round(float(price), 2)
        except ValueError:
            continue
        if new_company_price < 0 or new_company_price == product.selling_price:
            continue

        old_company_price = product.selling_price
        product.selling_price = new_company_price
        db.session.add(PriceHistory(
            product_id=product.id,
            old_company_price=old_company_price, new_company_price=new_company_price,
            old_cost_price=product.cost_price, new_cost_price=product.cost_price,
            reason=reason, changed_by_id=current_user.id
        ))
        updated += 1

    db.session.commit()
    return jsonify({'success': True, 'updated': updated})


@pricing_bp.route('/export')
@login_required
def export():
    if not _can_manage_pricing():
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    import pandas as pd, io
    products = Product.query.filter_by(status='active').order_by(Product.product_name).all()
    data = [{
        'Product Code': p.product_code,
        'Product Name': p.product_name,
        'Cost Price': p.cost_price,
        'Company Price': p.selling_price,
        'Margin %': p.profit_margin,
    } for p in products]
    df = pd.DataFrame(data)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        df.to_excel(w, index=False, sheet_name='Pricing')
    buf.seek(0)
    response = make_response(buf.read())
    response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    response.headers['Content-Disposition'] = 'attachment; filename=pricing_export.xlsx'
    return response


@pricing_bp.route('/import', methods=['POST'])
@login_required
def import_prices():
    if not _can_manage_pricing():
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    file = request.files.get('price_file')
    if not file:
        flash('No file uploaded.', 'warning')
        return redirect(url_for('pricing.index'))

    reason = (request.form.get('reason') or 'Bulk import from Excel').strip()

    import pandas as pd
    try:
        df = pd.read_excel(file)
    except Exception:
        flash('Could not read the Excel file.', 'danger')
        return redirect(url_for('pricing.index'))

    updated = 0
    for _, row in df.iterrows():
        code = str(row.get('Product Code', '')).strip()
        if not code:
            continue
        product = Product.query.filter_by(product_code=code).first()
        if not product:
            continue

        try:
            new_cost = float(row.get('Cost Price', product.cost_price))
            new_company = float(row.get('Company Price', product.selling_price))
        except (TypeError, ValueError):
            continue

        if new_cost == product.cost_price and new_company == product.selling_price:
            continue

        old_cost, old_company = product.cost_price, product.selling_price
        product.cost_price = round(new_cost, 2)
        product.selling_price = round(new_company, 2)
        db.session.add(PriceHistory(
            product_id=product.id,
            old_company_price=old_company, new_company_price=product.selling_price,
            old_cost_price=old_cost, new_cost_price=product.cost_price,
            reason=reason, changed_by_id=current_user.id
        ))
        updated += 1

    db.session.commit()
    flash(f'{updated} product price(s) imported.', 'success')
    return redirect(url_for('pricing.index'))
