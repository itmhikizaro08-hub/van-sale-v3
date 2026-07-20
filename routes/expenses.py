from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from app import db
from models.notification import Expense
from models.van import Van
from services.sequence import next_expense_number
from services.uploads import save_upload

expenses_bp = Blueprint('expenses', __name__)

CATEGORIES = ['fuel', 'vehicle_repair', 'salary', 'office', 'miscellaneous']


@expenses_bp.route('/')
@login_required
def index():
    if not current_user.can_access('expenses'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    start = request.args.get('start', (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end   = request.args.get('end',   datetime.utcnow().strftime('%Y-%m-%d'))

    q = Expense.query.filter(
        Expense.created_at >= start,
        Expense.created_at <= end + ' 23:59:59'
    )
    if current_user.scope('expenses') == 'own':
        q = q.filter_by(created_by_id=current_user.id)
    expenses = q.order_by(Expense.expense_date.desc()).all()

    total_approved = round(sum(e.amount for e in expenses if e.status == 'approved'), 2)
    pending_count = sum(1 for e in expenses if e.status == 'pending')
    rejected_count = sum(1 for e in expenses if e.status == 'rejected')

    return render_template('expenses/index.html', expenses=expenses, total=total_approved,
        pending_count=pending_count, rejected_count=rejected_count, start=start, end=end)


@expenses_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if not current_user.can_write('expenses'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('expenses.index'))

    vans = Van.query.filter_by(status='active').all()
    if request.method == 'POST':
        receipt_path = save_upload(request.files.get('receipt_image'), 'receipts')
        expense = Expense(
            expense_number=next_expense_number(),
            category=request.form['category'],
            description=request.form.get('description'),
            amount=float(request.form.get('amount') or 0),
            van_id=request.form.get('van_id') or None,
            reference_note=request.form.get('reference_note'),
            receipt_image=receipt_path,
            created_by_id=current_user.id
        )
        db.session.add(expense)
        db.session.commit()
        flash(f'Expense GHS {expense.amount:.2f} submitted!', 'success')
        return redirect(url_for('expenses.index'))
    return render_template('expenses/add.html', vans=vans, categories=CATEGORIES)


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
