"""Auto-generate system notifications for alerts."""
from app import db
from models.notification import Notification
from models.product import Product
from models.customer import Customer
from models.van import Driver
from datetime import date, datetime, timedelta


def check_all_notifications():
    count = 0
    count += _check_low_stock()
    count += _check_outstanding()
    count += _check_license_expiry()
    count += _check_missed_visits()
    count += check_due_scheduled_orders()
    return count


def _add_notification(title, message, ntype, icon='fa-bell', link=None):
    """Create a new alert, or refresh an existing unresolved one's message.

    Dedup is by title, but the underlying value (stock count, balance,
    expiry status) keeps changing while an alert sits unresolved — without
    refreshing the message, staff would keep seeing whatever number was true
    the first time the alert fired, no matter how stale it's since become.
    Always commits (even when just updating) so any other pending change a
    caller made this call (e.g. flipping a visit's status) is flushed too.
    """
    existing = Notification.query.filter(
        Notification.title == title,
        Notification.is_read == False
    ).first()
    if existing:
        existing.message = message
        db.session.commit()
        return False
    db.session.add(Notification(title=title, message=message,
                                notification_type=ntype, icon=icon, link=link))
    db.session.commit()
    return True


def _check_low_stock():
    products = Product.query.filter(
        Product.stock_quantity <= Product.reorder_level,
        Product.status == 'active'
    ).all()
    count = 0
    for p in products:
        if _add_notification(
            f'Low Stock: {p.product_name}',
            f'{p.product_name} has only {p.stock_quantity} units remaining (reorder level: {p.reorder_level}).',
            'low_stock', 'fa-box-open', '/inventory'
        ):
            count += 1
    return count


def _check_outstanding():
    customers = Customer.query.filter(Customer.outstanding_balance > 500).all()
    count = 0
    for c in customers:
        if _add_notification(
            f'Outstanding Balance: {c.name}',
            f'{c.name} has an outstanding balance of GHS {c.outstanding_balance:.2f}.',
            'outstanding_account', 'fa-exclamation-triangle', f'/customers/{c.id}'
        ):
            count += 1
    return count


def _check_license_expiry():
    drivers = Driver.query.filter_by(status='active').all()
    count = 0
    today = date.today()
    for d in drivers:
        if d.license_expiry and d.license_expiry <= today + timedelta(days=30):
            status = 'EXPIRED' if d.license_expiry < today else f'expires {d.license_expiry}'
            if _add_notification(
                f'License Alert: {d.name}',
                f"Driver {d.name}'s license {status}.",
                'license_expiry', 'fa-id-card', '/drivers'
            ):
                count += 1
    return count


def _check_missed_visits():
    """A visit is logged 'planned' the moment it's scheduled (visit_date is
    the creation time, not a future date - see visits.add()); if it's still
    'planned' with no check-in a day later, the rep never showed up and it
    was missed. A visit that has been checked in but not yet checked out
    stays 'planned' too (status only flips to 'completed' at checkout) -
    exclude those, they're in progress, not missed."""
    from models.van import CustomerVisit
    cutoff = datetime.utcnow() - timedelta(hours=24)
    visits = CustomerVisit.query.filter(
        CustomerVisit.status == 'planned',
        CustomerVisit.check_in_time.is_(None),
        CustomerVisit.visit_date < cutoff
    ).all()
    count = 0
    for v in visits:
        v.status = 'missed'
        customer = Customer.query.get(v.customer_id)
        name = customer.name if customer else f'Customer #{v.customer_id}'
        if _add_notification(
            f'Missed Visit: {name}',
            f"A visit to {name} planned for {v.visit_date.strftime('%d %b %Y')} was never checked in.",
            'missed_visit', 'fa-calendar-times', '/visits/'
        ):
            count += 1
    return count


def check_due_scheduled_orders():
    """SMS the assigned rep for every pending scheduled order whose due date
    has arrived (or passed, if nobody used the app on the exact day). Guarded
    by sms_sent_at so each order only ever triggers one SMS, no matter how
    many times this runs. Also drops an in-app notification either way, so a
    failed send (bad phone number, SMS provider down) is still visible to a
    human rather than silently vanishing."""
    from models.scheduled_order import ScheduledOrder
    from services.sms_service import send_sms

    orders = ScheduledOrder.query.filter(
        ScheduledOrder.status == 'pending',
        ScheduledOrder.due_date <= date.today(),
        ScheduledOrder.sms_sent_at.is_(None)
    ).all()
    count = 0
    for o in orders:
        item_summary = ', '.join(
            f'{i.quantity:g} x {i.product.product_name}' for i in o.items if i.product
        ) or 'see order for details'
        message = (f"Reminder: supply due today for {o.customer.name} "
                   f"(order {o.order_number}): {item_summary}.")

        sent = False
        if o.rep and o.rep.phone:
            sent = send_sms(o.rep.phone, message, sms_type='scheduled_order_reminder',
                             recipient_name=o.rep.full_name)
        o.sms_sent_at = datetime.utcnow()
        db.session.commit()

        rep_desc = o.rep.full_name if o.rep else 'no rep assigned'
        if sent:
            status_text = f'SMS sent to {rep_desc}.'
        elif o.rep and o.rep.phone:
            status_text = f'SMS FAILED to send to {rep_desc} — check SMS Center for the error.'
        else:
            status_text = f'No SMS sent — {rep_desc} (no phone number on file).'
        if _add_notification(
            f'Order Due: {o.customer.name} ({o.order_number})',
            f'Scheduled order {o.order_number} for {o.customer.name} is due. {status_text}',
            'info', 'fa-calendar-check', f'/scheduled-orders/{o.id}'
        ):
            count += 1
    return count
