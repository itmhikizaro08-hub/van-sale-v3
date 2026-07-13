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
    start = request.args.get('start', (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end   = request.args.get('end',   datetime.utcnow().strftime('%Y-%m-%d'))
    sales = Sale.query.filter(
        Sale.status == 'completed',
        Sale.sale_date >= start,
        Sale.sale_date <= end + ' 23:59:59'
    ).order_by(Sale.sale_date.desc()).limit(200).all()

    total_sales_amount = round(sum(s.total_amount for s in sales), 2)
    total_outstanding = round(sum(s.balance_due for s in sales), 2)

    return render_template('invoices/index.html', sales=sales, start=start, end=end,
        total_sales_amount=total_sales_amount, total_outstanding=total_outstanding)


@invoices_bp.route('/<int:sale_id>')
@login_required
def view(sale_id):
    sale = Sale.query.get_or_404(sale_id)
    s = Settings.get()
    company = {
        'name': s.company_name,
        'address': s.company_address,
        'phone': s.company_phone,
        'email': s.company_email,
    }
    return render_template('invoices/view.html', sale=sale, company=company)


@invoices_bp.route('/<int:sale_id>/pdf')
@login_required
def pdf(sale_id):
    sale = Sale.query.get_or_404(sale_id)
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
