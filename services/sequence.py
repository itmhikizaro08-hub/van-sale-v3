"""Auto-incrementing sequence numbers for documents."""
from app import db
from models.sale import Sale
from models.payment import Payment


def next_invoice_number():
    from models.settings import Settings
    last = Sale.query.order_by(Sale.id.desc()).first()
    n = (last.id + 1) if last else 1
    prefix = Settings.get().invoice_prefix or 'INV-'
    return f'{prefix}{n:06d}'


def next_payment_number():
    last = Payment.query.order_by(Payment.id.desc()).first()
    n = (last.id + 1) if last else 1
    return f'PAY-{n:06d}'


def next_return_number():
    from models.notification import Return
    last = Return.query.order_by(Return.id.desc()).first()
    n = (last.id + 1) if last else 1
    return f'RET-{n:05d}'


def next_expense_number():
    from models.notification import Expense
    last = Expense.query.order_by(Expense.id.desc()).first()
    n = (last.id + 1) if last else 1
    return f'EXP-{n:05d}'


def next_loading_sheet_number():
    try:
        from models.van_management import LoadingSheet
        last = LoadingSheet.query.order_by(LoadingSheet.id.desc()).first()
        n = (last.id + 1) if last else 1
    except Exception:
        n = 1
    return f'LS-{n:05d}'


def next_return_order_number():
    try:
        from models.v4_models import ReturnOrder
        last = ReturnOrder.query.order_by(ReturnOrder.id.desc()).first()
        n = (last.id + 1) if last else 1
    except Exception:
        n = 1
    return f'RO-{n:05d}'


def next_credit_note_number():
    try:
        from models.v4_models import CreditNote
        last = CreditNote.query.order_by(CreditNote.id.desc()).first()
        n = (last.id + 1) if last else 1
    except Exception:
        n = 1
    return f'CN-{n:05d}'


def next_debit_note_number():
    try:
        from models.v4_models import DebitNote
        last = DebitNote.query.order_by(DebitNote.id.desc()).first()
        n = (last.id + 1) if last else 1
    except Exception:
        n = 1
    return f'DN-{n:05d}'


def next_stock_offload_number():
    from models.van_management import StockOffload
    last = StockOffload.query.order_by(StockOffload.id.desc()).first()
    n = (last.id + 1) if last else 1
    return f'SO-{n:05d}'


def next_supplier_payment_number():
    from models.notification import SupplierPayment
    last = SupplierPayment.query.order_by(SupplierPayment.id.desc()).first()
    n = (last.id + 1) if last else 1
    return f'SPAY-{n:05d}'
