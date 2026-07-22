import csv
import io
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, Response
from flask_login import login_required, current_user
from app import db
from models.product import Product, Category
from models.settings import Settings

products_bp = Blueprint('products', __name__)


def _next_code():
    last = Product.query.order_by(Product.id.desc()).first()
    n = (last.id + 1) if last else 1
    return f'PRD{n:04d}'


PRODUCT_IMPORT_COLUMNS = [
    'product_code', 'product_name', 'category', 'brand', 'unit',
    'cost_price', 'selling_price', 'wholesale_price', 'reorder_level',
    'pieces_per_unit', 'stock_quantity', 'tax_rate'
]


@products_bp.route('/import', methods=['GET', 'POST'])
@login_required
def import_csv():
    if not current_user.can_write('products'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('products.index'))

    if request.method == 'POST':
        file = request.files.get('file')
        if not file or not file.filename:
            flash('Choose a CSV file to upload.', 'warning')
            return redirect(url_for('products.import_csv'))

        try:
            stream = io.StringIO(file.stream.read().decode('utf-8-sig'))
            reader = csv.DictReader(stream)
        except Exception:
            flash('Could not read that file — make sure it is a valid CSV.', 'danger')
            return redirect(url_for('products.import_csv'))

        created, skipped, errors = 0, 0, []
        seen_names = {p.product_name.lower() for p in Product.query.filter_by(status='active').all()}
        for i, row in enumerate(reader, start=2):  # row 1 is the header
            name = (row.get('product_name') or '').strip()
            if not name:
                errors.append(f'Row {i}: missing product_name — skipped.')
                continue
            if name.lower() in seen_names:
                skipped += 1
                continue

            code = (row.get('product_code') or '').strip() or _next_code()
            if Product.query.filter_by(product_code=code).first():
                skipped += 1
                continue

            category_obj = None
            cat_name = (row.get('category') or '').strip()
            if cat_name:
                category_obj = Category.query.filter_by(name=cat_name).first()
                if not category_obj:
                    category_obj = Category(name=cat_name)
                    db.session.add(category_obj)
                    db.session.flush()

            try:
                product = Product(
                    product_code=code,
                    product_name=name,
                    category_id=category_obj.id if category_obj else None,
                    brand=(row.get('brand') or '').strip() or None,
                    unit=(row.get('unit') or 'piece').strip(),
                    cost_price=float(row.get('cost_price') or 0),
                    selling_price=float(row.get('selling_price') or 0),
                    wholesale_price=float(row.get('wholesale_price') or 0),
                    reorder_level=int(float(row.get('reorder_level') or Settings.get().default_reorder_level or 10)),
                    pieces_per_unit=int(float(row.get('pieces_per_unit') or 1)),
                    stock_quantity=float(row.get('stock_quantity') or 0),
                    tax_rate=float(row.get('tax_rate') or 0),
                    status='active'
                )
                db.session.add(product)
                seen_names.add(name.lower())
                created += 1
            except (TypeError, ValueError) as e:
                errors.append(f'Row {i} ({name}): invalid number in one of the fields — skipped.')
                continue

        db.session.commit()
        msg = f'Imported {created} product(s), skipped {skipped} duplicate(s).'
        flash(msg, 'success' if created else 'warning')
        for err in errors[:20]:
            flash(err, 'warning')
        return redirect(url_for('products.index'))

    return render_template('products/import.html')


@products_bp.route('/import/template.csv')
@login_required
def import_template():
    if not current_user.can_write('products'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('products.index'))

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(PRODUCT_IMPORT_COLUMNS)
    writer.writerow(['', 'Sample Product', 'Beverages', '', 'piece', '10.00', '15.00', '13.00', '10', '1', '0', '0'])
    return Response(output.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=products_import_template.csv'})


@products_bp.route('/')
@login_required
def index():
    if not current_user.can_access('products'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    # Soft-deleted (deactivated) products stay in the table forever — never
    # show them on the main catalog, same convention as customers/suppliers.
    products = Product.query.filter_by(status='active').order_by(Product.product_name).all()
    categories = Category.query.order_by(Category.name).all()
    low_stock_count = sum(1 for p in products if p.is_low_stock and p.stock_quantity > 0)
    out_of_stock_count = sum(1 for p in products if p.stock_quantity == 0)
    total_stock_value = round(sum(p.stock_quantity * p.cost_price for p in products), 2)
    return render_template('products/index.html', products=products, categories=categories,
        low_stock_count=low_stock_count, out_of_stock_count=out_of_stock_count,
        total_stock_value=total_stock_value)


@products_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if not current_user.can_write('products'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('products.index'))

    categories = Category.query.order_by(Category.name).all()

    if request.method == 'POST':
        name = request.form['product_name'].strip()
        # Guards against both a genuine typo'd duplicate and an accidental
        # double-submit (double-click / slow network resubmission) creating
        # two active products with the same name under different codes.
        existing = Product.query.filter(
            Product.status == 'active', db.func.lower(Product.product_name) == name.lower()
        ).first()
        if existing:
            flash(f'A product named "{name}" already exists ({existing.product_code}). '
                  f'Edit it instead, or use a different name.', 'warning')
            return redirect(url_for('products.add'))

        product = Product(
            product_code=_next_code(),
            product_name=name,
            category_id=request.form.get('category_id') or None,
            brand=request.form.get('brand'),
            description=request.form.get('description'),
            barcode=request.form.get('barcode') or None,
            unit=request.form.get('unit', 'pcs'),
            cost_price=float(request.form.get('cost_price') or 0),
            selling_price=float(request.form.get('selling_price') or 0),
            wholesale_price=float(request.form.get('wholesale_price') or 0),
            reorder_level=int(request.form.get('reorder_level') or Settings.get().default_reorder_level or 10),
            stock_quantity=float(request.form.get('stock_quantity') or 0),
            pieces_per_unit=int(request.form.get('pieces_per_unit') or 1),
            tax_rate=float(request.form.get('tax_rate') or 0),
            status=request.form.get('status', 'active')
        )
        db.session.add(product)
        db.session.commit()
        flash(f'Product {product.product_name} added!', 'success')
        return redirect(url_for('products.index'))

    return render_template('products/form.html', product=None, categories=categories)


@products_bp.route('/<int:product_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(product_id):
    if not current_user.can_write('products'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('products.index'))

    product = Product.query.get_or_404(product_id)
    categories = Category.query.order_by(Category.name).all()

    if request.method == 'POST':
        name = request.form['product_name'].strip()
        existing = Product.query.filter(
            Product.status == 'active', Product.id != product.id,
            db.func.lower(Product.product_name) == name.lower()
        ).first()
        if existing:
            flash(f'A product named "{name}" already exists ({existing.product_code}).', 'warning')
            return redirect(url_for('products.edit', product_id=product.id))

        product.product_name = name
        product.category_id = request.form.get('category_id') or None
        product.brand = request.form.get('brand')
        product.description = request.form.get('description')
        product.barcode = request.form.get('barcode') or None
        product.unit = request.form.get('unit', 'pcs')
        product.cost_price = float(request.form.get('cost_price') or 0)
        product.selling_price = float(request.form.get('selling_price') or 0)
        product.wholesale_price = float(request.form.get('wholesale_price') or 0)
        product.reorder_level = int(request.form.get('reorder_level') or Settings.get().default_reorder_level or 10)
        product.pieces_per_unit = int(request.form.get('pieces_per_unit') or 1)
        product.tax_rate = float(request.form.get('tax_rate') or 0)
        product.status = request.form.get('status', 'active')
        db.session.commit()
        flash('Product updated!', 'success')
        return redirect(url_for('products.index'))

    return render_template('products/form.html', product=product, categories=categories)


@products_bp.route('/<int:product_id>/delete', methods=['POST'])
@login_required
def delete(product_id):
    if not current_user.can_write('products'):
        return jsonify({'error': 'Permission denied'}), 403
    product = Product.query.get_or_404(product_id)
    product.status = 'inactive'
    db.session.commit()
    return jsonify({'success': True})


@products_bp.route('/search')
@login_required
def search():
    if not current_user.can_access('products'):
        return jsonify([]), 403
    q = request.args.get('q', '').strip()
    products = Product.query.filter(
        (Product.product_name.ilike(f'%{q}%') |
         Product.product_code.ilike(f'%{q}%') |
         Product.barcode.ilike(f'%{q}%')),
        Product.status == 'active',
        Product.stock_quantity > 0
    ).limit(20).all()
    return jsonify([p.to_dict() for p in products])


@products_bp.route('/low-stock')
@login_required
def low_stock():
    if not current_user.can_access('products'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    products = Product.query.filter(
        Product.stock_quantity <= Product.reorder_level,
        Product.status == 'active'
    ).all()
    return render_template('products/low_stock.html', products=products)


@products_bp.route('/categories', methods=['GET', 'POST'])
@login_required
def categories():
    if not current_user.can_access('products'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    if request.method == 'POST':
        if not current_user.can_write('products'):
            flash('Permission denied.', 'danger')
            return redirect(url_for('products.categories'))
        name = request.form.get('name', '').strip()
        if name and not Category.query.filter_by(name=name).first():
            db.session.add(Category(name=name, description=request.form.get('description')))
            db.session.commit()
            flash(f'Category "{name}" added!', 'success')
        else:
            flash('Category name already exists or is empty.', 'warning')
    categories = Category.query.order_by(Category.name).all()
    return render_template('products/categories.html', categories=categories)

@products_bp.route('/<int:product_id>')
@login_required
def view(product_id):
    if not current_user.can_access('products'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    product = Product.query.get_or_404(product_id)

    from models.notification import VanStock, InventoryMovement
    from models.sale import Sale, SaleItem

    field_stock = VanStock.query.filter_by(product_id=product_id).filter(VanStock.quantity > 0).all()
    total_field_qty = round(sum(fs.quantity for fs in field_stock), 2)

    recent_sales = (SaleItem.query.join(Sale, SaleItem.sale_id == Sale.id)
        .filter(SaleItem.product_id == product_id, Sale.status == 'completed')
        .order_by(Sale.sale_date.desc()).limit(10).all())
    total_sold = SaleItem.query.join(Sale, SaleItem.sale_id == Sale.id).filter(
        SaleItem.product_id == product_id, Sale.status == 'completed'
    ).with_entities(db.func.sum(SaleItem.quantity)).scalar() or 0
    total_revenue = SaleItem.query.join(Sale, SaleItem.sale_id == Sale.id).filter(
        SaleItem.product_id == product_id, Sale.status == 'completed'
    ).with_entities(db.func.sum(SaleItem.line_total)).scalar() or 0

    recent_movements = InventoryMovement.query.filter_by(product_id=product_id) \
        .order_by(InventoryMovement.created_at.desc()).limit(15).all()

    return render_template('products/view.html', product=product,
        field_stock=field_stock, total_field_qty=total_field_qty,
        recent_sales=recent_sales, total_sold=round(total_sold, 2), total_revenue=round(total_revenue, 2),
        recent_movements=recent_movements)
