import re
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from sqlalchemy.orm import joinedload
from sqlalchemy import func
from app import db
from models.expense import Expense, ExpenseCategory
from models.van import Van
from services.sequence import next_expense_number
from services.uploads import save_upload

expenses_bp = Blueprint('expenses', __name__)


def _active_categories():
    return ExpenseCategory.query.filter_by(is_active=True).order_by(ExpenseCategory.label).all()


def _slugify(label):
    key = re.sub(r'[^a-z0-9]+', '_', label.strip().lower()).strip('_')
    return key or 'category'


def _monthly_expense_trend(months=6):
    """Last `months` calendar months of approved expense totals, oldest
    first — same shape as routes/finance.py's _monthly_trend()."""
    today = datetime.utcnow().date()
    month_starts = []
    y, m = today.year, today.month
    for _ in range(months):
        month_starts.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    month_starts.reverse()

    labels, values = [], []
    for y, m in month_starts:
        m_start = datetime(y, m, 1)
        m_end = datetime(y + 1, 1, 1) if m == 12 else datetime(y, m + 1, 1)
        total = db.session.query(func.sum(Expense.amount)).filter(
            Expense.status == 'approved', Expense.expense_date >= m_start, Expense.expense_date < m_end
        ).scalar() or 0
        labels.append(m_start.strftime('%b %Y'))
        values.append(round(total, 2))
    return labels, values


@expenses_bp.route('/')
@login_required
def index():
    if not current_user.can_access('expenses'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    start = request.args.get('start', (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end   = request.args.get('end',   datetime.utcnow().strftime('%Y-%m-%d'))
    category_filter = request.args.get('category', '')
    van_filter = request.args.get('van_id', '')

    q = Expense.query.options(joinedload(Expense.created_by), joinedload(Expense.van)).filter(
        Expense.created_at >= start,
        Expense.created_at <= end + ' 23:59:59'
    )
    if current_user.scope('expenses') == 'own':
        q = q.filter_by(created_by_id=current_user.id)
    if category_filter:
        q = q.filter_by(category=category_filter)
    if van_filter:
        q = q.filter_by(van_id=van_filter)
    expenses = q.order_by(Expense.expense_date.desc()).all()

    approved = [e for e in expenses if e.status == 'approved']
    total_approved = round(sum(e.amount for e in approved), 2)
    pending_count = sum(1 for e in expenses if e.status == 'pending')
    rejected_count = sum(1 for e in expenses if e.status == 'rejected')
    month_start = datetime.utcnow().replace(day=1).strftime('%Y-%m-%d')
    total_this_month = round(db.session.query(func.sum(Expense.amount)).filter(
        Expense.status == 'approved', Expense.expense_date >= month_start
    ).scalar() or 0, 2)

    by_category = {}
    for e in approved:
        by_category[e.category] = by_category.get(e.category, 0) + e.amount
    by_category = sorted([(k, round(v, 2)) for k, v in by_category.items()], key=lambda x: -x[1])

    trend_labels, trend_values = _monthly_expense_trend()

    all_categories = ExpenseCategory.query.order_by(ExpenseCategory.label).all()
    category_icons = {c.key: c.icon for c in all_categories}
    category_labels = {c.key: c.label for c in all_categories}
    vans = Van.query.filter_by(status='active').order_by(Van.van_number).all()

    return render_template('expenses/index.html', expenses=expenses, total=total_approved,
        pending_count=pending_count, rejected_count=rejected_count, total_this_month=total_this_month,
        by_category=by_category, trend_labels=trend_labels, trend_values=trend_values,
        all_categories=all_categories, category_icons=category_icons, category_labels=category_labels,
        vans=vans, start=start, end=end, category_filter=category_filter, van_filter=van_filter)


@expenses_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if not current_user.can_write('expenses'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('expenses.index'))

    vans = Van.query.filter_by(status='active').all()
    categories = _active_categories()
    if request.method == 'POST':
        try:
            amount = float(request.form.get('amount') or 0)
        except ValueError:
            flash('Enter a valid amount.', 'danger')
            return redirect(url_for('expenses.add'))
        if amount <= 0:
            flash('Enter a positive amount.', 'danger')
            return redirect(url_for('expenses.add'))

        receipt_path = save_upload(request.files.get('receipt_image'), 'receipts')
        expense = Expense(
            expense_number=next_expense_number(),
            category=request.form['category'],
            description=request.form.get('description'),
            amount=amount,
            van_id=request.form.get('van_id') or None,
            reference_note=request.form.get('reference_note'),
            receipt_image=receipt_path,
            created_by_id=current_user.id
        )
        db.session.add(expense)
        db.session.commit()
        flash(f'Expense GHS {expense.amount:.2f} submitted!', 'success')
        return redirect(url_for('expenses.index'))
    return render_template('expenses/add.html', vans=vans, categories=categories)


@expenses_bp.route('/<int:expense_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(expense_id):
    if not current_user.can_approve_module('expenses'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('expenses.index'))
    expense = Expense.query.get_or_404(expense_id)
    if expense.status == 'void':
        flash('This expense is voided and cannot be edited.', 'warning')
        return redirect(url_for('expenses.index'))

    vans = Van.query.filter_by(status='active').all()
    categories = _active_categories()
    if request.method == 'POST':
        try:
            amount = float(request.form.get('amount') or 0)
        except ValueError:
            flash('Enter a valid amount.', 'danger')
            return redirect(url_for('expenses.edit', expense_id=expense.id))
        if amount <= 0:
            flash('Enter a positive amount.', 'danger')
            return redirect(url_for('expenses.edit', expense_id=expense.id))

        expense.category = request.form['category']
        expense.amount = amount
        expense.van_id = request.form.get('van_id') or None
        expense.description = request.form.get('description')
        expense.reference_note = request.form.get('reference_note')
        new_receipt = save_upload(request.files.get('receipt_image'), 'receipts')
        if new_receipt:
            expense.receipt_image = new_receipt
        db.session.commit()
        flash(f'Expense {expense.expense_number} updated.', 'success')
        return redirect(url_for('expenses.index'))
    return render_template('expenses/edit.html', expense=expense, vans=vans, categories=categories)


@expenses_bp.route('/<int:expense_id>/approve', methods=['POST'])
@login_required
def approve(expense_id):
    if not current_user.can_approve_module('expenses'):
        return jsonify({'error': 'Permission denied'}), 403
    expense = Expense.query.get_or_404(expense_id)
    if expense.status != 'pending':
        return jsonify({'error': 'Already processed'}), 400
    expense.status = 'approved'
    expense.approved_by_id = current_user.id
    db.session.commit()
    return jsonify({'success': True})


@expenses_bp.route('/<int:expense_id>/reject', methods=['POST'])
@login_required
def reject(expense_id):
    if not current_user.can_approve_module('expenses'):
        return jsonify({'error': 'Permission denied'}), 403
    expense = Expense.query.get_or_404(expense_id)
    if expense.status != 'pending':
        return jsonify({'error': 'Already processed'}), 400
    expense.status = 'rejected'
    expense.approved_by_id = current_user.id
    db.session.commit()
    return jsonify({'success': True})


@expenses_bp.route('/<int:expense_id>/void', methods=['POST'])
@login_required
def void(expense_id):
    if not current_user.can_approve_module('expenses'):
        return jsonify({'error': 'Permission denied'}), 403
    expense = Expense.query.get_or_404(expense_id)
    if expense.status != 'approved':
        return jsonify({'error': 'Only an approved expense can be voided'}), 400
    expense.status = 'void'
    db.session.commit()
    return jsonify({'success': True})


# ── Category management ──────────────────────────────────────────────────────
@expenses_bp.route('/categories/add', methods=['POST'])
@login_required
def categories_add():
    if not current_user.can_approve_module('expenses'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('expenses.index'))
    label = (request.form.get('label') or '').strip()
    if not label:
        flash('Enter a category name.', 'danger')
        return redirect(url_for('expenses.index'))
    icon = (request.form.get('icon') or '').strip() or 'fa-receipt'
    key = _slugify(label)
    if ExpenseCategory.query.filter_by(key=key).first():
        flash(f'A category named "{label}" already exists.', 'warning')
        return redirect(url_for('expenses.index'))
    db.session.add(ExpenseCategory(key=key, label=label, icon=icon))
    db.session.commit()
    flash(f'Category "{label}" added.', 'success')
    return redirect(url_for('expenses.index'))


@expenses_bp.route('/categories/<int:cat_id>/edit', methods=['POST'])
@login_required
def categories_edit(cat_id):
    if not current_user.can_approve_module('expenses'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('expenses.index'))
    cat = ExpenseCategory.query.get_or_404(cat_id)
    label = (request.form.get('label') or '').strip()
    if not label:
        flash('Enter a category name.', 'danger')
        return redirect(url_for('expenses.index'))
    cat.label = label
    cat.icon = (request.form.get('icon') or '').strip() or cat.icon
    db.session.commit()
    flash(f'Category updated to "{label}".', 'success')
    return redirect(url_for('expenses.index'))


@expenses_bp.route('/categories/<int:cat_id>/toggle', methods=['POST'])
@login_required
def categories_toggle(cat_id):
    if not current_user.can_approve_module('expenses'):
        return jsonify({'error': 'Permission denied'}), 403
    cat = ExpenseCategory.query.get_or_404(cat_id)
    cat.is_active = not cat.is_active
    db.session.commit()
    return jsonify({'success': True, 'is_active': cat.is_active})
