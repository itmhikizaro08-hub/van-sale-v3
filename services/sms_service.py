"""SMS Service - supports Arkesel and Hubtel."""
import os
import requests
from datetime import datetime
from app import db
from models.notification import SMSLog


def _config():
    """SMS provider config — Settings (set via the UI) wins, falling back to
    env vars so a fresh install with no Settings row yet still works."""
    from models.settings import Settings
    s = Settings.get()
    return {
        'provider': s.sms_provider or os.getenv('SMS_PROVIDER', 'arkesel'),
        'arkesel_key': s.arkesel_api_key or os.getenv('ARKESEL_API_KEY', ''),
        'arkesel_sender': s.arkesel_sender_name or os.getenv('ARKESEL_SMS_NAME', 'VanSales'),
        'hubtel_id': s.hubtel_client_id or os.getenv('HUBTEL_CLIENT_ID', ''),
        'hubtel_secret': s.hubtel_client_secret or os.getenv('HUBTEL_CLIENT_SECRET', ''),
    }


def send_sms(phone: str, message: str, sms_type: str = 'custom',
             recipient_name: str = None) -> bool:
    """Send an SMS and log the result."""
    cfg = _config()
    log = SMSLog(
        recipient_name=recipient_name,
        phone_number=phone,
        message=message,
        sms_type=sms_type,
        provider=cfg['provider'],
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
        if cfg['provider'] == 'arkesel':
            if not cfg['arkesel_key']:
                raise ValueError('No Arkesel API key configured — add one in Settings.')
            success, response_text = _send_arkesel(phone, message, cfg)
        elif cfg['provider'] == 'hubtel':
            if not cfg['hubtel_id'] or not cfg['hubtel_secret']:
                raise ValueError('Hubtel client ID/secret not configured — add them in Settings.')
            success, response_text = _send_hubtel(phone, message, cfg)
        else:
            response_text = 'Unknown provider'
    except Exception as e:
        response_text = str(e)

    log.status = 'sent' if success else 'failed'
    log.provider_response = response_text
    log.sent_at = datetime.utcnow() if success else None
    db.session.commit()
    return success


def _send_arkesel(phone: str, message: str, cfg: dict):
    url = 'https://sms.arkesel.com/sms/api'
    params = {
        'action': 'send-sms',
        'api_key': cfg['arkesel_key'],
        'to': phone,
        'from': cfg['arkesel_sender'],
        'sms': message
    }
    r = requests.get(url, params=params, timeout=10)
    data = r.json()
    success = data.get('status') == 'success'
    return success, str(data)


def _send_hubtel(phone: str, message: str, cfg: dict):
    url = f'https://smsc.hubtel.com/v1/messages/send'
    params = {
        'clientid': cfg['hubtel_id'],
        'clientsecret': cfg['hubtel_secret'],
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
