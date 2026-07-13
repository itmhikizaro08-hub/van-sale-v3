"""SMS Service - supports Arkesel and Hubtel."""
import os
import requests
from datetime import datetime
from app import db
from models.notification import SMSLog

PROVIDER = os.getenv('SMS_PROVIDER', 'arkesel')
ARKESEL_KEY = os.getenv('ARKESEL_API_KEY', '')
ARKESEL_SENDER = os.getenv('ARKESEL_SMS_NAME', 'VanSales')
HUBTEL_ID = os.getenv('HUBTEL_CLIENT_ID', '')
HUBTEL_SECRET = os.getenv('HUBTEL_CLIENT_SECRET', '')


def send_sms(phone: str, message: str, sms_type: str = 'custom',
             recipient_name: str = None) -> bool:
    """Send an SMS and log the result."""
    log = SMSLog(
        recipient_name=recipient_name,
        phone_number=phone,
        message=message,
        sms_type=sms_type,
        provider=PROVIDER,
        status='pending'
    )
    db.session.add(log)
    db.session.flush()

    from models.settings import Settings
    if not Settings.get().sms_enabled:
        log.status = 'disabled'
        log.provider_response = 'SMS notifications are turned off in Settings.'
        db.session.commit()
        return False

    success = False
    response_text = ''

    try:
        if PROVIDER == 'arkesel':
            success, response_text = _send_arkesel(phone, message)
        elif PROVIDER == 'hubtel':
            success, response_text = _send_hubtel(phone, message)
        else:
            response_text = 'Unknown provider'
    except Exception as e:
        response_text = str(e)

    log.status = 'sent' if success else 'failed'
    log.provider_response = response_text
    log.sent_at = datetime.utcnow() if success else None
    db.session.commit()
    return success


def _send_arkesel(phone: str, message: str):
    url = 'https://sms.arkesel.com/sms/api'
    params = {
        'action': 'send-sms',
        'api_key': ARKESEL_KEY,
        'to': phone,
        'from': ARKESEL_SENDER,
        'sms': message
    }
    r = requests.get(url, params=params, timeout=10)
    data = r.json()
    success = data.get('status') == 'success'
    return success, str(data)


def _send_hubtel(phone: str, message: str):
    url = f'https://smsc.hubtel.com/v1/messages/send'
    params = {
        'clientid': HUBTEL_ID,
        'clientsecret': HUBTEL_SECRET,
        'from': 'VanSales',
        'to': phone,
        'content': message
    }
    r = requests.get(url, params=params, timeout=10)
    success = r.status_code == 200
    return success, r.text


def send_invoice_sms(customer, sale):
    if not customer.phone:
        return False
    msg = (f"Thank you {customer.name}. Invoice {sale.invoice_number} "
           f"Amount GHS {sale.total_amount:.2f}. Balance: GHS {sale.balance_due:.2f}.")
    return send_sms(customer.phone, msg, sms_type='invoice_created', recipient_name=customer.name)


def send_payment_sms(customer, payment, sale=None):
    if not customer.phone:
        return False
    balance = (sale.balance_due if sale else customer.outstanding_balance)
    msg = (f"Payment of GHS {payment.amount:.2f} received. "
           f"Outstanding Balance: GHS {balance:.2f}. Thank you!")
    return send_sms(customer.phone, msg, sms_type='payment_received', recipient_name=customer.name)


def send_overdue_reminders():
    """Send overdue reminders to customers with outstanding balances."""
    from models.customer import Customer
    customers = Customer.query.filter(
        Customer.outstanding_balance > 0,
        Customer.status == 'active',
        Customer.phone.isnot(None)
    ).all()
    count = 0
    for c in customers:
        msg = (f"Dear {c.name}, you have an outstanding balance of "
               f"GHS {c.outstanding_balance:.2f}. Please make payment. Thank you.")
        if send_sms(c.phone, msg, sms_type='overdue_reminder', recipient_name=c.name):
            count += 1
    return count
