from flask import Blueprint, render_template, make_response, current_app, jsonify, request, flash, redirect, url_for
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from models.sale import Sale
from models.settings import Settings
from services.pdf_service import generate_invoice_pdf

invoices_bp = Blueprint('invoices', __name__)


def _net_balances(sales):
    """Map sale.id -> net balance/status info, accounting for applied credit
    notes — those reduce the customer's account-wide outstanding_balance, not
    a Sale's own stored balance_due/payment_status (see routes/invoices.py's
    view(), which this mirrors), so anywhere that displays a sale's payment
    state needs this instead of the raw column to avoid showing "Unpaid" on
    an invoice a return has already fully settled."""
    from models.notes import CreditNote
    sale_ids = [s.id for s in sales]
    credit_by_sale = {}
    if sale_ids:
        for cn in CreditNote.query.filter(CreditNote.sale_id.in_(sale_ids), CreditNote.status == 'applied').all():
            # A cash-refunded return already paid the customer real money
            # back out of the till (routes/returns.py's _record_cash_refund)
            # — its CreditNote exists for the paper trail, not to ALSO
            # reduce what's still owed on the invoice. Only count
            # credit-type refunds (or a manually-issued note with no
            # return_order at all — routes/notes.py) toward the reduction,
            # or a cash refund on a partially-paid invoice would understate
            # the real remaining balance.
            if cn.return_order and cn.return_order.refund_method == 'cash':
                continue
            credit_by_sale[cn.sale_id] = credit_by_sale.get(cn.sale_id, 0) + cn.amount

    badges = {'unpaid': 'bg-danger', 'partial': 'bg-warning text-dark', 'paid': 'bg-success'}
    result = {}
    for s in sales:
        credit_total = round(credit_by_sale.get(s.id, 0), 2)
        net_balance_due = round(max(0, s.balance_due - credit_total), 2)
        if net_balance_due <= 0:
            status = 'paid'
        elif s.amount_paid > 0 or credit_total > 0:
            status = 'partial'
        else:
            status = 'unpaid'
        result[s.id] = {
            'net_balance_due': net_balance_due, 'credit_total': credit_total,
            'net_payment_status': status, 'net_payment_badge': badges.get(status, 'bg-secondary'),
        }
    return result


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
    # total_outstanding stays balance_due-derived (real money owed, not a
    # revenue figure) but net of applied credit notes via _net_balances —
    # see that function's docstring. The per-invoice "Total" column below
    # is unaffected either way (it's each invoice's real total, not a
    # company-revenue KPI).
    total_sales_amount = round(sum(s.company_sales_total or 0 for s in sales), 2)
    net = _net_balances(sales)
    total_outstanding = round(sum(net[s.id]['net_balance_due'] for s in sales), 2)

    return render_template('invoices/index.html', sales=sales, start=start, end=end,
        total_sales_amount=total_sales_amount, total_outstanding=total_outstanding, net=net)


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
    # Credit notes reduce the customer's account-wide balance, not this
    # Sale's own stored balance_due/payment_status (those track real
    # cash movement via amount_paid) — but the invoice still needs to show
    # its true net position, or it looks like money is still owed on a sale
    # that's already been fully settled by a return, "Record Payment" button
    # included. See _net_balances() above.
    from models.notes import CreditNote
    credit_notes = CreditNote.query.filter_by(sale_id=sale_id, status='applied').all()
    net = _net_balances([sale])[sale.id]
    return render_template('invoices/view.html', sale=sale, company=company,
        credit_notes=credit_notes, credit_total=net['credit_total'],
        net_balance_due=net['net_balance_due'], net_payment_status=net['net_payment_status'],
        net_payment_badge=net['net_payment_badge'])


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
    # Net of applied credit notes — see _net_balances() above and view()'s
    # comment. Without this the PDF would print a stale, overstated balance
    # that contradicts the invoice view page for the same sale.
    net = _net_balances([sale])[sale.id]
    try:
        pdf_bytes = generate_invoice_pdf(sale, company, net_balance_due=net['net_balance_due'],
                                          net_payment_status=net['net_payment_status'],
                                          credit_total=net['credit_total'])
        response = make_response(pdf_bytes)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename={sale.invoice_number}.pdf'
        return response
    except Exception as e:
        flash(f'PDF error: {e}', 'danger')
        return redirect(url_for('invoices.view', sale_id=sale_id))
