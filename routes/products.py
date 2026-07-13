from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app import db
from models.product import Product, Category
from models.settings import Settings

products_bp = Blueprint('products', __name__)


def _next_code():
    last = Product.query.order_by(Product.id.desc()).first()
    n = (last.id + 1) if last else 1
    return f'PRD{n:04d}'


@products_bp.route('/')
@login_required
def index():
    products = Product.query.order_by(Product.product_name).all()
    categories = Category.query.order_by(Category.name).all()
    return render_template('products/index.html', products=products, categories=categories)


@products_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if not current_user.can_add:
        flash('Permission denied.', 'danger')
        return redirect(url_for('products.index'))

    categories = Category.query.order_by(Category.name).all()

    if request.method == 'POST':
        product = Product(
            product_code=_next_code(),
            product_name=request.form['product_name'],
            category_id=request.form.get('category_id') or None,
            brand=request.form.get('brand'),
            description=request.form.get('description'),
            barcode=request.form.get('barcode') or None,
            unit=request.form.get('unit', 'pcs'),
            cost_price=float(request.form.get('cost_price') or 0),
            selling_price=float(request.form.get('selling_price') or 0),
            wholesale_price=float(request.form.get('wholesale_price') or 0),
            reorder_level=int(request.form.get('reorder_level') or Settings.get().default_reorder_level or 10),
            stock_quantity=int(request.form.get('stock_quantity') or 0),
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
    if not current_user.can_edit:
        flash('Permission denied.', 'danger')
        return redirect(url_for('products.index'))

    product = Product.query.get_or_404(product_id)
    categories = Category.query.order_by(Category.name).all()

    if request.method == 'POST':
        product.product_name = request.form['product_name']
        product.category_id = request.form.get('category_id') or None
        product.brand = request.form.get('brand')
        product.description = request.form.get('description')
        product.barcode = request.form.get('barcode') or None
        product.unit = request.form.get('unit', 'pcs')
        product.cost_price = float(request.form.get('cost_price') or 0)
        product.selling_price = float(request.form.get('selling_price') or 0)
        product.wholesale_price = float(request.form.get('wholesale_price') or 0)
        product.reorder_level = int(request.form.get('reorder_level') or Settings.get().default_reorder_level or 10)
        product.tax_rate = float(request.form.get('tax_rate') or 0)
        product.status = request.form.get('status', 'active')
        db.session.commit()
        flash('Product updated!', 'success')
        return redirect(url_for('products.index'))

    return render_template('products/form.html', product=product, categories=categories)


@products_bp.route('/<int:product_id>/delete', methods=['POST'])
@login_required
def delete(product_id):
    if not current_user.can_delete:
        return jsonify({'error': 'Permission denied'}), 403
    product = Product.query.get_or_404(product_id)
    product.status = 'inactive'
    db.session.commit()
    return jsonify({'success': True})


@products_bp.route('/search')
@login_required
def search():
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
    products = Product.query.filter(
        Product.stock_quantity <= Product.reorder_level,
        Product.status == 'active'
    ).all()
    return render_template('products/low_stock.html', products=products)


@products_bp.route('/categories', methods=['GET', 'POST'])
@login_required
def categories():
    if request.method == 'POST':
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
    from models.product import Product
    product = Product.query.get_or_404(product_id)
    return render_template('products/view.html', product=product)
