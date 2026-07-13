"""Auto-record a customer visit whenever a rep sells to or collects payment
from a customer — a sale or payment in the field implies the rep was there,
so it shouldn't require a separate "Mark Visited" tap to count."""
from datetime import date, datetime
from app import db
from models.van import CustomerVisit


def record_auto_visit(customer_id, rep_id, outcome, force_outcome=False):
    """Find or create today's visit for this customer+rep and mark it completed."""
    today = date.today()
    visit = CustomerVisit.query.filter_by(
        customer_id=customer_id, sales_rep_id=rep_id
    ).filter(db.func.date(CustomerVisit.visit_date) == today).first()

    if visit:
        if visit.status != 'completed':
            visit.status = 'completed'
        visit.check_in_time = visit.check_in_time or datetime.utcnow()
        if force_outcome or not visit.outcome:
            visit.outcome = outcome
    else:
        visit = CustomerVisit(
            customer_id=customer_id,
            sales_rep_id=rep_id,
            visit_date=datetime.utcnow(),
            check_in_time=datetime.utcnow(),
            status='completed',
            outcome=outcome
        )
        db.session.add(visit)

    return visit
