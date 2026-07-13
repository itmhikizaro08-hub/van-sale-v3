"""
Database migration helper — runs on every startup.
Safely adds new columns to existing tables without breaking existing data.
"""
import logging
log = logging.getLogger(__name__)


def run_migrations(db):
    """Apply incremental schema changes to an existing database."""
    engine = db.engine
    conn = engine.connect()

    try:
        # ── Sprint B: Add sales_rep_id to van_stocks ──────────────────────
        _add_column_if_missing(conn, engine, 'van_stocks', 'sales_rep_id', 'INTEGER')

        # ── Sprint A: Add tip columns to sale_items ────────────────────────
        _add_column_if_missing(conn, engine, 'sale_items', 'official_price', 'FLOAT DEFAULT 0.0')
        _add_column_if_missing(conn, engine, 'sale_items', 'tip_amount',     'FLOAT DEFAULT 0.0')

        # ── reference_note on core tables ─────────────────────────────────
        _add_column_if_missing(conn, engine, 'sales',    'reference_note', 'VARCHAR(255)')
        _add_column_if_missing(conn, engine, 'payments', 'reference_note', 'VARCHAR(255)')
        _add_column_if_missing(conn, engine, 'payments', 'notes',          'TEXT')
        _add_column_if_missing(conn, engine, 'payments', 'status',         "VARCHAR(20) DEFAULT 'completed'")

        # ── Customer tier / wallet ─────────────────────────────────────────
        _add_column_if_missing(conn, engine, 'customers', 'tier', "VARCHAR(20) DEFAULT 'bronze'")

        # ── Company pricing / tip totals snapshot on sales ─────────────────
        _add_column_if_missing(conn, engine, 'sales', 'company_sales_total', 'FLOAT DEFAULT 0.0')
        _add_column_if_missing(conn, engine, 'sales', 'total_tips_amount',   'FLOAT DEFAULT 0.0')

        # ── Reference note on expenses ──────────────────────────────────────
        _add_column_if_missing(conn, engine, 'expenses', 'reference_note', 'VARCHAR(255)')

        # ── Supplier attribution on stock-in movements ──────────────────────
        _add_column_if_missing(conn, engine, 'inventory_movements', 'supplier_id', 'INTEGER')
        _add_column_if_missing(conn, engine, 'inventory_movements', 'reference_note', 'VARCHAR(255)')

        # ── Approval workflow on supplier payments ──────────────────────────
        _add_column_if_missing(conn, engine, 'supplier_payments', 'status', "VARCHAR(20) DEFAULT 'approved'")
        _add_column_if_missing(conn, engine, 'supplier_payments', 'approved_by_id', 'INTEGER')
        _add_column_if_missing(conn, engine, 'supplier_payments', 'approved_at', 'DATETIME')

        # ── Theme preference on users ────────────────────────────────────────
        _add_column_if_missing(conn, engine, 'users', 'theme_preference', "VARCHAR(10) DEFAULT 'light'")

        # ── Void tracking on payments ────────────────────────────────────────
        _add_column_if_missing(conn, engine, 'payments', 'voided_by_id', 'INTEGER')
        _add_column_if_missing(conn, engine, 'payments', 'voided_at', 'DATETIME')

        # ── Drop old broken unique constraint on van_stocks and recreate ───
        _fix_van_stocks_constraint(conn, engine)

        conn.commit()

        # ── Self-heal sales where payment_status drifted from balance_due ──
        # (e.g. amount_paid was ever set without a matching recalculate())
        _repair_sale_payment_status(db)

        # ── Self-heal customers where outstanding_balance drifted from the
        # actual sale/payment/note ledger ──────────────────────────────────
        _repair_customer_outstanding_balance(db)

        # ── Backfill official_price/tip_amount on sale items predating the
        # tip feature (best-effort, approved by the user) ──────────────────
        _repair_historical_tip_amounts(db)

        log.info("Migrations applied successfully.")

    except Exception as e:
        log.warning(f"Migration warning (non-fatal): {e}")
    finally:
        conn.close()


def _add_column_if_missing(conn, engine, table, column, col_type):
    """Add a column to a table if it doesn't already exist."""
    from sqlalchemy import text, inspect
    try:
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        if table not in tables:
            return  # table doesn't exist yet — db.create_all() will make it
        existing = [c['name'] for c in inspector.get_columns(table)]
        if column not in existing:
            conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {col_type}'))
            log.info(f"Migration: added {table}.{column}")
    except Exception as e:
        log.debug(f"Column {table}.{column}: {e}")


def _repair_sale_payment_status(db):
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
        log.debug(f"payment_status repair skipped: {e}")


def _repair_customer_outstanding_balance(db):
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
        log.debug(f"outstanding_balance repair skipped: {e}")


def _repair_historical_tip_amounts(db):
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
        log.debug(f"historical tip backfill skipped: {e}")


def _fix_van_stocks_constraint(conn, engine):
    """
    SQLite doesn't support DROP CONSTRAINT. The only way to fix a broken
    unique constraint is to recreate the table. We do this safely:
    1. Check if the old constraint name 'uq_van_product' exists
    2. If it does, SQLite already has the right columns (since it was
       created fresh) — SQLAlchemy will have named it 'uq_van_rep_product'
    For existing DBs with the old constraint, we just drop and recreate.
    """
    from sqlalchemy import text, inspect
    try:
        inspector = inspect(engine)
        if 'van_stocks' not in inspector.get_table_names():
            return

        # Get existing columns
        cols = [c['name'] for c in inspector.get_columns('van_stocks')]

        # If sales_rep_id column is now present but old bad constraint exists,
        # we need to rebuild the table. SQLite approach: rename, recreate, copy.
        if 'sales_rep_id' in cols:
            # Check if the table was already migrated (has the new constraint name)
            # by trying a safe probe. If we get here, the column exists — good.
            return

        # sales_rep_id not in existing columns — add it via rename trick
        conn.execute(text('ALTER TABLE van_stocks RENAME TO van_stocks_old'))
        conn.execute(text('''
            CREATE TABLE van_stocks (
                id           INTEGER PRIMARY KEY,
                van_id       INTEGER NOT NULL REFERENCES vans(id),
                sales_rep_id INTEGER REFERENCES users(id),
                product_id   INTEGER NOT NULL REFERENCES products(id),
                quantity     INTEGER DEFAULT 0,
                updated_at   DATETIME,
                UNIQUE (van_id, sales_rep_id, product_id)
            )
        '''))
        conn.execute(text('''
            INSERT INTO van_stocks (id, van_id, sales_rep_id, product_id, quantity, updated_at)
            SELECT id, van_id, NULL, product_id, quantity, updated_at
            FROM van_stocks_old
        '''))
        conn.execute(text('DROP TABLE van_stocks_old'))
        log.info("Migration: rebuilt van_stocks table with sales_rep_id column")

    except Exception as e:
        log.debug(f"van_stocks constraint fix: {e}")
