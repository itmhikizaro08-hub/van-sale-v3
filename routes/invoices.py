from flask import Blueprint, render_template, make_response, current_app, jsonify, request, flash, redirect, url_for
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from models.sale import Sale
from models.settings import Settings
from services.pdf_service import generate_invoice_pdf

invoices_bp = Blueprint('invoices', __name__)


@invoices_bp.route('/')
@login_required
def index():
    if not current_user.can_access('invoices'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    start = request.args.get('start', (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end   = request.args.get('end',   datetime.utcnow().strftime('%Y-%m-%d'))
    q = Sale.query.filter(
        Sale.status == 'completed',
        Sale.sale_date >= start,
        Sale.sale_date <= end + ' 23:59:59'
    )
    if current_user.scope('invoices') == 'own':
        q = q.filter_by(sales_rep_id=current_user.id)
    sales = q.order_by(Sale.sale_date.desc()).limit(200).all()

    # company_sales_total, not total_amount — same convention as
    # reports/profit_loss.py, reports/sales.py's Gross/Net Sales, and the
    # dashboards: a rep's tip markup on top of the official price belongs
    # to the rep, not the company, so this aggregate must exclude it.
    # total_outstanding stays total_amount-derived (via balance_due) since
    # it's real money still owed on the invoice, not a revenue figure; the
    # per-invoice "Total" column below is unaffected either, for the same
    # reason (it's each invoice's real total, not a company-revenue KPI).
    total_sales_amount = round(sum(s.company_sales_total or 0 for s in sales), 2)
    total_outstanding = round(sum(s.balance_due for s in sales), 2)

    return render_template('invoices/index.html', sales=sales, start=start, end=end,
        total_sales_amount=total_sales_amount, total_outstanding=total_outstanding)


@invoices_bp.route('/<int:sale_id>')
@login_required
def view(sale_id):
    sale = Sale.query.get_or_404(sale_id)
    if not current_user.can_access('invoices'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    if current_user.scope('invoices') == 'own' and sale.sales_rep_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('invoices.index'))
    s = Settings.get()
    company = {
        'name': s.company_name,
        'address': s.company_address,
        'phone': s.company_phone,
        'email': s.company_email,
    }
    # Credit notes are applied at the customer's account-wide balance, not
    # against this specific Sale's own total_amount/balance_due — so without
    # this, viewing an invoice that had part of it returned gives no clue a
    # credit was ever issued against it.
    from models.notes import CreditNote
    credit_notes = CreditNote.query.filter_by(sale_id=sale_id, status='applied').all()
    credit_total = round(sum(cn.amount for cn in credit_notes), 2)
    return render_template('invoices/view.html', sale=sale, company=company,
        credit_notes=credit_notes, credit_total=credit_total)


@invoices_bp.route('/<int:sale_id>/pdf')
@login_required
def pdf(sale_id):
    sale = Sale.query.get_or_404(sale_id)
    if not current_user.can_access('invoices'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    if current_user.scope('invoices') == 'own' and sale.sales_rep_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('invoices.index'))
    s = Settings.get()
    company = {
        'name': s.company_name or 'Van Sales V4',
        'address': s.company_address or '',
        'phone': s.company_phone or '',
        'email': s.company_email or '',
    }
    try:
        pdf_bytes = generate_invoice_pdf(sale, company)
        response = make_response(pdf_bytes)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename={sale.invoice_number}.pdf'
        return response
    except Exception as e:
        flash(f'PDF error: {e}', 'danger')
        return redirect(url_for('invoices.view', sale_id=sale_id))
