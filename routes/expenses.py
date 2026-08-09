import re
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, make_response
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from sqlalchemy.orm import joinedload
from sqlalchemy import func
from app import db
from models.expense import Expense, ExpenseCategory, ExpenseAuditLog, PAYMENT_METHODS
from models.user import User
from services.sequence import next_expense_number
from services.uploads import save_upload

expenses_bp = Blueprint('expenses', __name__)

RECEIPT_EXTRA_EXT = ('pdf',)


def _active_categories():
    return ExpenseCategory.query.filter_by(is_active=True).order_by(ExpenseCategory.label).all()


def _slugify(label):
    key = re.sub(r'[^a-z0-9]+', '_', label.strip().lower()).strip('_')
    return key or 'category'


def _log(expense, action, actor_id, note=None):
    db.session.add(ExpenseAuditLog(expense_id=expense.id, action=action, actor_id=actor_id, note=note))


def _scoped_query():
    """Base Expense query respecting the current user's scope('expenses')."""
    q = Expense.query
    if current_user.scope('expenses') == 'own':
        q = q.filter_by(created_by_id=current_user.id)
    return q


def _apply_filters(q, args):
    """Shared filter logic for the index page, both export routes, and the
    reports page — one place so a filter added here can never silently be
    forgotten on one of those other routes."""
    start = args.get('start', (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end   = args.get('end',   datetime.utcnow().strftime('%Y-%m-%d'))
    category = args.get('category', '')
    status = args.get('status', '')
    payment_method = args.get('payment_method', '')
    submitted_by = args.get('submitted_by', type=int)

    q = q.filter(Expense.expense_date >= start, Expense.expense_date <= end + ' 23:59:59')
    if category:
        q = q.filter_by(category=category)
    if status:
        q = q.filter_by(status=status)
    if payment_method:
        q = q.filter_by(payment_method=payment_method)
    if submitted_by:
        q = q.filter_by(created_by_id=submitted_by)

    filters = dict(start=start, end=end, category=category, status=status,
                    payment_method=payment_method, submitted_by=submitted_by)
    return q, filters


def _submitters():
    """Users who have actually submitted at least one expense — keeps the
    'Submitted By' filter from being cluttered with everyone who merely has
    permission to."""
    return User.query.join(Expense, User.id == Expense.created_by_id).distinct().order_by(User.full_name).all()


def _trend(expenses, granularity):
    """Approved-expense totals bucketed by day/week/month, operating on an
    already date-filtered `expenses` list so the trend always reflects the
    same filtered set as everything else on the page (only approved amounts
    count toward a spend trend)."""
    approved = [e for e in expenses if e.status == 'approved']
    buckets = {}
    for e in approved:
        d = e.expense_date or e.created_at
        if not d:
            continue
        if granularity == 'monthly':
            key = d.strftime('%Y-%m')
            label = d.strftime('%b %Y')
        elif granularity == 'weekly':
            iso = d.isocalendar()
            key = f'{iso[0]}-W{iso[1]:02d}'
            label = f'Wk {iso[1]}, {iso[0]}'
        else:
            key = d.strftime('%Y-%m-%d')
            label = d.strftime('%d %b')
        b = buckets.setdefault(key, {'label': label, 'total': 0.0})
        b['total'] += e.amount
    ordered = [buckets[k] for k in sorted(buckets.keys())]
    return [b['label'] for b in ordered], [round(b['total'], 2) for b in ordered]


@expenses_bp.route('/')
@login_required
def index():
    if not current_user.can_access('expenses'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    q, filters = _apply_filters(_scoped_query(), request.args)
    granularity = request.args.get('granularity', 'daily')
    expenses = q.options(joinedload(Expense.created_by), joinedload(Expense.approved_by)) \
        .order_by(Expense.expense_date.desc()).all()

    approved = [e for e in expenses if e.status == 'approved']
    pending = [e for e in expenses if e.status == 'pending']
    rejected = [e for e in expenses if e.status == 'rejected']
    non_void = [e for e in expenses if e.status != 'void']

    total_expenses = round(sum(e.amount for e in non_void), 2)
    total_approved = round(sum(e.amount for e in approved), 2)
    pending_count, pending_total = len(pending), round(sum(e.amount for e in pending), 2)
    rejected_count, rejected_total = len(rejected), round(sum(e.amount for e in rejected), 2)

    # This-month figure is whole-book, not filter-scoped — a KPI card, not a
    # filtered result — but still respects the user's own/all expense scope.
    month_start = datetime.utcnow().replace(day=1).strftime('%Y-%m-%d')
    month_q = Expense.query.filter(Expense.status == 'approved', Expense.expense_date >= month_start)
    if current_user.scope('expenses') == 'own':
        month_q = month_q.filter_by(created_by_id=current_user.id)
    total_this_month = round(month_q.with_entities(func.sum(Expense.amount)).scalar() or 0, 2)

    by_category = {}
    for e in approved:
        by_category[e.category] = by_category.get(e.category, 0) + e.amount
    by_category = sorted([(k, round(v, 2)) for k, v in by_category.items()], key=lambda x: -x[1])

    by_method = {}
    for e in non_void:
        by_method[e.payment_method or 'cash'] = by_method.get(e.payment_method or 'cash', 0) + e.amount
    by_method = sorted([(k, round(v, 2)) for k, v in by_method.items()], key=lambda x: -x[1])

    status_counts = {'approved': len(approved), 'pending': len(pending), 'rejected': len(rejected)}

    trend_labels, trend_values = _trend(expenses, granularity)

    all_categories = ExpenseCategory.query.order_by(ExpenseCategory.label).all()
    category_icons = {c.key: c.icon for c in all_categories}
    category_labels = {c.key: c.label for c in all_categories}

    return render_template('expenses/index.html', expenses=expenses,
        total_expenses=total_expenses, total_approved=total_approved,
        pending_count=pending_count, pending_total=pending_total,
        rejected_count=rejected_count, rejected_total=rejected_total,
        total_this_month=total_this_month,
        by_category=by_category, by_method=by_method, status_counts=status_counts,
        trend_labels=trend_labels, trend_values=trend_values, granularity=granularity,
        all_categories=all_categories, categories=_active_categories(),
        category_icons=category_icons, category_labels=category_labels,
        submitters=_submitters(), payment_methods=PAYMENT_METHODS,
        today=datetime.utcnow().strftime('%Y-%m-%d'), **filters)


@expenses_bp.route('/categories')
@login_required
def categories():
    if not current_user.can_approve_module('expenses'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('expenses.index'))

    all_categories = ExpenseCategory.query.order_by(ExpenseCategory.label).all()

    # All-time count + total spent per category (a management overview, not
    # a filtered report — Expense Reports' "by category" view already
    # covers the date-filtered version of this).
    cat_stats = {}
    for e in Expense.query.all():
        s = cat_stats.setdefault(e.category, {'count': 0, 'total': 0.0})
        s['count'] += 1
        if e.status == 'approved':
            s['total'] += e.amount
    for s in cat_stats.values():
        s['total'] = round(s['total'], 2)

    return render_template('expenses/categories.html', all_categories=all_categories, cat_stats=cat_stats)


@expenses_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if not current_user.can_write('expenses'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('expenses.index'))

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
        category = request.form.get('category')
        if not category or not ExpenseCategory.query.filter_by(key=category, is_active=True).first():
            flash('Select a valid, active category.', 'danger')
            return redirect(url_for('expenses.add'))
        payment_method = request.form.get('payment_method') or 'cash'
        if payment_method not in dict(PAYMENT_METHODS):
            payment_method = 'cash'

        expense_date_raw = request.form.get('expense_date')
        try:
            expense_date = datetime.strptime(expense_date_raw, '%Y-%m-%d') if expense_date_raw else datetime.utcnow()
        except ValueError:
            expense_date = datetime.utcnow()

        receipt_path = save_upload(request.files.get('receipt_image'), 'receipts', extra_extensions=RECEIPT_EXTRA_EXT)
        expense = Expense(
            expense_number=next_expense_number(),
            category=category,
            description=request.form.get('description'),
            amount=amount,
            payment_method=payment_method,
            expense_date=expense_date,
            reference_note=request.form.get('reference_note'),
            receipt_image=receipt_path,
            created_by_id=current_user.id
        )
        db.session.add(expense)
        db.session.flush()
        _log(expense, 'created', current_user.id)
        db.session.commit()

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'expense_number': expense.expense_number})
        flash(f'Expense {expense.expense_number} (GHS {expense.amount:.2f}) submitted!', 'success')
        return redirect(url_for('expenses.index'))
    return render_template('expenses/add.html', categories=categories, payment_methods=PAYMENT_METHODS,
                            today=datetime.utcnow().strftime('%Y-%m-%d'))


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
        category = request.form.get('category')
        if not category:
            flash('Select a category.', 'danger')
            return redirect(url_for('expenses.edit', expense_id=expense.id))
        payment_method = request.form.get('payment_method') or expense.payment_method
        if payment_method not in dict(PAYMENT_METHODS):
            payment_method = expense.payment_method

        expense_date_raw = request.form.get('expense_date')
        if expense_date_raw:
            try:
                expense.expense_date = datetime.strptime(expense_date_raw, '%Y-%m-%d')
            except ValueError:
                pass

        expense.category = category
        expense.amount = amount
        expense.payment_method = payment_method
        expense.description = request.form.get('description')
        expense.reference_note = request.form.get('reference_note')
        expense.updated_by_id = current_user.id
        expense.updated_at = datetime.utcnow()
        new_receipt = save_upload(request.files.get('receipt_image'), 'receipts', extra_extensions=RECEIPT_EXTRA_EXT)
        if new_receipt:
            expense.receipt_image = new_receipt
        _log(expense, 'edited', current_user.id)
        db.session.commit()
        flash(f'Expense {expense.expense_number} updated.', 'success')
        return redirect(url_for('expenses.view', expense_id=expense.id))
    return render_template('expenses/edit.html', expense=expense, categories=categories,
                            payment_methods=PAYMENT_METHODS)


@expenses_bp.route('/<int:expense_id>')
@login_required
def view(expense_id):
    if not current_user.can_access('expenses'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    expense = Expense.query.get_or_404(expense_id)
    if current_user.scope('expenses') == 'own' and expense.created_by_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('expenses.index'))
    logs = ExpenseAuditLog.query.filter_by(expense_id=expense.id).order_by(ExpenseAuditLog.created_at).all()
    cat = ExpenseCategory.query.filter_by(key=expense.category).first()
    return render_template('expenses/view.html', expense=expense, logs=logs, cat=cat)


@expenses_bp.route('/<int:expense_id>/approve', methods=['POST'])
@login_required
def approve(expense_id):
    if not current_user.can_approve_module('expenses'):
        return jsonify({'error': 'Permission denied'}), 403
    expense = Expense.query.get_or_404(expense_id)
    if expense.status != 'pending':
        return jsonify({'error': 'Already processed'}), 400
    note = (request.get_json(silent=True) or {}).get('note') if request.is_json else request.form.get('note')
    expense.status = 'approved'
    expense.approved_by_id = current_user.id
    expense.approved_at = datetime.utcnow()
    expense.approval_note = note
    _log(expense, 'approved', current_user.id, note)
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
    reason = (request.get_json(silent=True) or {}).get('reason') if request.is_json else request.form.get('reason')
    reason = (reason or '').strip()
    if not reason:
        return jsonify({'error': 'A rejection reason is required.'}), 400
    expense.status = 'rejected'
    expense.approved_by_id = current_user.id
    expense.approved_at = datetime.utcnow()
    expense.rejection_reason = reason
    _log(expense, 'rejected', current_user.id, reason)
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
    _log(expense, 'voided', current_user.id)
    db.session.commit()
    return jsonify({'success': True})


@expenses_bp.route('/<int:expense_id>/delete', methods=['POST'])
@login_required
def delete(expense_id):
    # Admin-only, and only for expenses with no financial standing (never
    # approved, or already reversed via void) — an approved expense is part
    # of the financial record and must be voided, never deleted, to keep the
    # audit trail intact.
    if current_user.role != 'admin':
        return jsonify({'error': 'Permission denied'}), 403
    expense = Expense.query.get_or_404(expense_id)
    if expense.status not in ('rejected', 'void'):
        return jsonify({'error': 'Only rejected or voided expenses can be deleted.'}), 400
    db.session.delete(expense)
    db.session.commit()
    return jsonify({'success': True})


# ── Category management ──────────────────────────────────────────────────────
@expenses_bp.route('/categories/add', methods=['POST'])
@login_required
def categories_add():
    if not current_user.can_approve_module('expenses'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('expenses.categories'))
    label = (request.form.get('label') or '').strip()
    if not label:
        flash('Enter a category name.', 'danger')
        return redirect(url_for('expenses.categories'))
    icon = (request.form.get('icon') or '').strip() or 'fa-receipt'
    key = _slugify(label)
    if ExpenseCategory.query.filter_by(key=key).first():
        flash(f'A category named "{label}" already exists.', 'warning')
        return redirect(url_for('expenses.categories'))
    db.session.add(ExpenseCategory(key=key, label=label, icon=icon))
    db.session.commit()
    flash(f'Category "{label}" added.', 'success')
    return redirect(url_for('expenses.categories'))


@expenses_bp.route('/categories/<int:cat_id>/edit', methods=['POST'])
@login_required
def categories_edit(cat_id):
    if not current_user.can_approve_module('expenses'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('expenses.categories'))
    cat = ExpenseCategory.query.get_or_404(cat_id)
    label = (request.form.get('label') or '').strip()
    if not label:
        flash('Enter a category name.', 'danger')
        return redirect(url_for('expenses.categories'))
    cat.label = label
    cat.icon = (request.form.get('icon') or '').strip() or cat.icon
    db.session.commit()
    flash(f'Category updated to "{label}".', 'success')
    return redirect(url_for('expenses.categories'))


@expenses_bp.route('/categories/<int:cat_id>/toggle', methods=['POST'])
@login_required
def categories_toggle(cat_id):
    if not current_user.can_approve_module('expenses'):
        return jsonify({'error': 'Permission denied'}), 403
    cat = ExpenseCategory.query.get_or_404(cat_id)
    cat.is_active = not cat.is_active
    db.session.commit()
    return jsonify({'success': True, 'is_active': cat.is_active})


# ── Exports ───────────────────────────────────────────────────────────────────
def _export_rows(expenses):
    return [{
        'Expense #': e.expense_number,
        'Date': e.expense_date.strftime('%Y-%m-%d') if e.expense_date else '',
        'Category': e.category,
        'Description': e.description or '',
        'Amount': e.amount,
        'Payment Method': e.payment_method_label,
        'Submitted By': e.created_by.full_name if e.created_by else '',
        'Status': e.status,
        'Approved By': e.approved_by.full_name if e.approved_by else '',
        'Approval Date': e.approved_at.strftime('%Y-%m-%d %H:%M') if e.approved_at else '',
    } for e in expenses]


@expenses_bp.route('/export/excel')
@login_required
def export_excel():
    if not current_user.can_access('expenses'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    import pandas as pd, io
    q, filters = _apply_filters(_scoped_query(), request.args)
    expenses = q.order_by(Expense.expense_date.desc()).all()
    df = pd.DataFrame(_export_rows(expenses))
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        df.to_excel(w, index=False, sheet_name='Expenses')
    buf.seek(0)
    response = make_response(buf.read())
    response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    response.headers['Content-Disposition'] = f'attachment; filename=expenses_{filters["start"]}_{filters["end"]}.xlsx'
    return response


@expenses_bp.route('/export/pdf')
@login_required
def export_pdf():
    if not current_user.can_access('expenses'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    from services.pdf_service import generate_expenses_list_pdf
    from models.settings import Settings
    q, filters = _apply_filters(_scoped_query(), request.args)
    expenses = q.order_by(Expense.expense_date.desc()).all()
    settings = Settings.get()
    company = {'name': settings.company_name, 'phone': settings.company_phone, 'address': settings.company_address}
    pdf_bytes = generate_expenses_list_pdf(expenses, company, filters['start'], filters['end'])
    response = make_response(pdf_bytes)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'inline; filename=expenses_{filters["start"]}_{filters["end"]}.pdf'
    return response


@expenses_bp.route('/<int:expense_id>/pdf')
@login_required
def expense_pdf(expense_id):
    if not current_user.can_access('expenses'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    expense = Expense.query.get_or_404(expense_id)
    if current_user.scope('expenses') == 'own' and expense.created_by_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('expenses.index'))
    from services.pdf_service import generate_expense_detail_pdf
    from models.settings import Settings
    logs = ExpenseAuditLog.query.filter_by(expense_id=expense.id).order_by(ExpenseAuditLog.created_at).all()
    settings = Settings.get()
    company = {'name': settings.company_name, 'phone': settings.company_phone, 'address': settings.company_address}
    pdf_bytes = generate_expense_detail_pdf(expense, logs, company)
    response = make_response(pdf_bytes)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'inline; filename={expense.expense_number}.pdf'
    return response


# ── Reports ───────────────────────────────────────────────────────────────────
REPORT_TYPES = [
    ('daily', 'Daily Expense Report'),
    ('monthly', 'Monthly Expense Report'),
    ('by_category', 'Expense by Category'),
    ('by_employee', 'Expense by Employee'),
    ('approved_vs_rejected', 'Approved vs Rejected'),
    ('payment_method', 'Payment Method Report'),
]


def _report_data(report_type, expenses, category_filter=None):
    approved = [e for e in expenses if e.status == 'approved']
    if report_type in ('daily', 'monthly'):
        granularity = 'daily' if report_type == 'daily' else 'monthly'
        labels, values = _trend(expenses, granularity)
        # NOT 'values' as a key: dicts have a .values() method that shadows
        # a same-named key under Jinja's dot-access, so `data.values` in the
        # template would silently resolve to that method instead of this
        # list and blow up tojson with "not JSON serializable".
        return {'labels': labels, 'totals': values, 'pairs': list(zip(labels, values))}
    if report_type == 'by_category':
        rows = {}
        for e in approved:
            rows.setdefault(e.category, {'count': 0, 'total': 0.0})
            rows[e.category]['count'] += 1
            rows[e.category]['total'] += e.amount
        return {'rows': sorted(
            [{'key': k, 'count': v['count'], 'total': round(v['total'], 2)} for k, v in rows.items()],
            key=lambda r: -r['total'])}
    if report_type == 'by_employee':
        rows = {}
        for e in approved:
            name = e.created_by.full_name if e.created_by else 'Unknown'
            rows.setdefault(name, {'count': 0, 'total': 0.0})
            rows[name]['count'] += 1
            rows[name]['total'] += e.amount
        return {'rows': sorted(
            [{'key': k, 'count': v['count'], 'total': round(v['total'], 2)} for k, v in rows.items()],
            key=lambda r: -r['total'])}
    if report_type == 'approved_vs_rejected':
        rej = [e for e in expenses if e.status == 'rejected']
        return {'approved_count': len(approved), 'approved_total': round(sum(e.amount for e in approved), 2),
                'rejected_count': len(rej), 'rejected_total': round(sum(e.amount for e in rej), 2)}
    if report_type == 'payment_method':
        rows = {}
        for e in approved:
            m = e.payment_method or 'cash'
            rows.setdefault(m, {'count': 0, 'total': 0.0})
            rows[m]['count'] += 1
            rows[m]['total'] += e.amount
        return {'rows': sorted(
            [{'key': k, 'count': v['count'], 'total': round(v['total'], 2)} for k, v in rows.items()],
            key=lambda r: -r['total'])}
    return {}


@expenses_bp.route('/reports')
@login_required
def reports():
    if not current_user.can_access('expenses'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    report_type = request.args.get('report_type', 'by_category')
    q, filters = _apply_filters(_scoped_query(), request.args)
    expenses = q.order_by(Expense.expense_date.desc()).all()
    data = _report_data(report_type, expenses)
    all_categories = ExpenseCategory.query.order_by(ExpenseCategory.label).all()
    category_labels = {c.key: c.label for c in all_categories}
    return render_template('expenses/reports.html', report_type=report_type, report_types=REPORT_TYPES,
                            data=data, category_labels=category_labels, **filters)


@expenses_bp.route('/reports/export/excel')
@login_required
def reports_export_excel():
    if not current_user.can_access('expenses'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    import pandas as pd, io
    report_type = request.args.get('report_type', 'by_category')
    q, filters = _apply_filters(_scoped_query(), request.args)
    expenses = q.order_by(Expense.expense_date.desc()).all()
    data = _report_data(report_type, expenses)
    rows = data.get('rows') or [{'Period': l, 'Total': v} for l, v in zip(data.get('labels', []), data.get('totals', []))]
    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        df.to_excel(w, index=False, sheet_name='Report')
    buf.seek(0)
    response = make_response(buf.read())
    response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    response.headers['Content-Disposition'] = f'attachment; filename=expense_report_{report_type}.xlsx'
    return response


@expenses_bp.route('/reports/export/pdf')
@login_required
def reports_export_pdf():
    if not current_user.can_access('expenses'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    from services.pdf_service import generate_expense_report_pdf
    from models.settings import Settings
    report_type = request.args.get('report_type', 'by_category')
    q, filters = _apply_filters(_scoped_query(), request.args)
    expenses = q.order_by(Expense.expense_date.desc()).all()
    data = _report_data(report_type, expenses)
    settings = Settings.get()
    company = {'name': settings.company_name, 'phone': settings.company_phone, 'address': settings.company_address}
    report_label = dict(REPORT_TYPES).get(report_type, report_type)
    pdf_bytes = generate_expense_report_pdf(report_label, data, company, filters['start'], filters['end'])
    response = make_response(pdf_bytes)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'inline; filename=expense_report_{report_type}.pdf'
    return response
