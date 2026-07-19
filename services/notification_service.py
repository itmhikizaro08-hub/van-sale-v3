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
    return count


def _add_notification(title, message, ntype, icon='fa-bell', link=None):
    # Avoid duplicates for same title created today
    existing = Notification.query.filter(
        Notification.title == title,
        Notification.is_read == False
    ).first()
    if not existing:
        db.session.add(Notification(title=title, message=message,
                                    notification_type=ntype, icon=icon, link=link))
        db.session.commit()
        return True
    return False


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
    'planned' a day later, the rep never checked in and it was missed."""
    from models.van import CustomerVisit
    cutoff = datetime.utcnow() - timedelta(hours=24)
    visits = CustomerVisit.query.filter(
        CustomerVisit.status == 'planned',
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
