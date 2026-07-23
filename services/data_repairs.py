"""One-time historical data repairs — distinct from services/migrate.py's
ongoing schema migrations.

Each function here fixes rows left inconsistent by a specific past bug or
schema change (drifted payment_status, drifted outstanding_balance, tip
amounts predating the tip feature, a bad permissions seed). They're
idempotent (only touch rows still at the broken value) so it's safe for
run_migrations() to call all of them on every boot, but they are NOT
"migrations" in the schema sense — nothing here alters table structure.
Kept separate from migrate.py so a reader doesn't have to untangle
"structural change that runs every boot" from "historical fix that already
ran once and just hasn't been removed yet."
"""
import logging
log = logging.getLogger(__name__)


def repair_sale_payment_status(db):
    """Self-heal: payment_status can drift out of sync with balance_due if
    amount_paid was ever set without a matching recalculate() call (an older
    code path, or a raw data import). Recompute from the trusted balance_due/
    amount_paid fields and fix any mismatch, so 'Paid' always reflects a
    zero balance without needing to touch every sale by hand."""
    try:
        from models.sale import Sale
        fixed = 0
        for sale in Sale.query.all():
            correct = 'paid' if sale.balance_due <= 0 else ('partial' if sale.amount_paid > 0 else 'unpaid')
            if sale.payment_status != correct:
                sale.payment_status = correct
                fixed += 1
        if fixed:
            db.session.commit()
            log.info(f"Repaired payment_status on {fixed} sale(s).")
    except Exception as e:
        # A failed query leaves the session's transaction aborted on Postgres
        # (unlike SQLite) — every later query in this request would fail too
        # unless we roll back here, e.g. on a fresh DB where 'sales' doesn't
        # exist yet (this runs before db.create_all()).
        db.session.rollback()
        log.debug(f"payment_status repair skipped: {e}")


def repair_customer_outstanding_balance(db):
    """Self-heal: Customer.outstanding_balance is a running total nudged by
    many call sites (sale creation, payments, void/edit, debit/credit notes,
    returns — see services/statements.py's docstring for the full list). If
    any of those ever ran twice, got interrupted mid-commit, or a payment was
    ever removed outside the app's own void()/delete() flow, the stored total
    drifts from reality. services.statements.customer_statement_rows() already
    replays every one of those events from scratch as the trusted ledger for
    the Statement page — reuse it here as the source of truth and correct any
    mismatch, so 'Outstanding' always matches what the ledger actually says
    without needing to patch each customer by hand."""
    try:
        from models.customer import Customer
        from services.statements import customer_statement_rows
        fixed = 0
        for customer in Customer.query.all():
            _, _, closing = customer_statement_rows(customer, '2000-01-01', '2999-12-31')
            if abs((customer.outstanding_balance or 0) - closing) > 0.01:
                customer.outstanding_balance = closing
                fixed += 1
        if fixed:
            db.session.commit()
            log.info(f"Repaired outstanding_balance on {fixed} customer(s).")
    except Exception as e:
        db.session.rollback()
        log.debug(f"outstanding_balance repair skipped: {e}")


def repair_historical_tip_amounts(db):
    """One-time backfill: official_price/tip_amount on sale_items were added
    to the schema after sales already existed, so old rows got the column
    default of 0 — which makes tip_amount (= unit_price - official_price)
    always compute as 0 regardless of what was actually charged. There's no
    recorded history of the true company price at sale time for those rows
    (PricingAuditLog only starts capturing it going forward), so this
    approximates official_price using the product's CURRENT selling_price —
    reasonable only because the affected sales are all recent. Only touches
    rows still at the unset default of 0, so later runs are a no-op."""
    try:
        from models.sale import Sale, SaleItem
        fixed_items = 0
        fixed_sales = set()
        for item in SaleItem.query.filter(SaleItem.official_price == 0).all():
            if not item.product or not item.product.selling_price:
                continue
            official = item.product.selling_price
            item.official_price = official
            item.tip_amount = round(max(0, item.unit_price - official), 2)
            fixed_items += 1
            fixed_sales.add(item.sale_id)
        if fixed_items:
            db.session.flush()
            for sale in Sale.query.filter(Sale.id.in_(fixed_sales)).all():
                sale.recalculate()
            db.session.commit()
            log.info(f"Backfilled official_price/tip_amount on {fixed_items} historical "
                     f"sale item(s) across {len(fixed_sales)} sale(s).")
    except Exception as e:
        db.session.rollback()
        log.debug(f"historical tip backfill skipped: {e}")


def repair_tips_permissions(db):
    """One-time correction: the 'tips' RolePermission rows were originally
    seeded granting manager/sales_rep write+approve access, contradicting
    routes/tips.py's own documented design (manager and sales_rep are
    read-only for tips; only admin may edit/delete). Once seeded, the DB
    table is authoritative over the ROLE_PERMISSIONS dict in code (see
    load_role_permissions()), so fixing the dict alone never takes effect
    on a database that already ran the old seed. Only corrects rows still
    at that exact original (buggy) value, so it never overwrites a
    permission an admin has since deliberately changed via Settings."""
    try:
        from models.user import RolePermission
        fixed = 0
        original_bad = {
            'manager':   {'can_write': True, 'can_approve': True},
            'sales_rep': {'can_write': True, 'can_approve': False},
        }
        for role, bad in original_bad.items():
            row = RolePermission.query.filter_by(role=role, module='tips').first()
            if row and row.can_write == bad['can_write'] and row.can_approve == bad['can_approve']:
                row.can_write = False
                row.can_approve = False
                fixed += 1
        if fixed:
            db.session.commit()
            log.info(f"Repaired tips permissions on {fixed} role(s).")
    except Exception as e:
        db.session.rollback()
        log.debug(f"tips permission repair skipped: {e}")
