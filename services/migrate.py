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

        # ── SMS provider config on settings (configurable via the UI) ──────
        _add_column_if_missing(conn, engine, 'settings', 'sms_provider', "VARCHAR(20) DEFAULT 'arkesel'")
        _add_column_if_missing(conn, engine, 'settings', 'arkesel_api_key', 'VARCHAR(255)')
        _add_column_if_missing(conn, engine, 'settings', 'arkesel_sender_name', "VARCHAR(20) DEFAULT 'VanSales'")
        _add_column_if_missing(conn, engine, 'settings', 'hubtel_client_id', 'VARCHAR(255)')
        _add_column_if_missing(conn, engine, 'settings', 'hubtel_client_secret', 'VARCHAR(255)')
        _add_column_if_missing(conn, engine, 'settings', 'at_username', "VARCHAR(100) DEFAULT 'sandbox'")
        _add_column_if_missing(conn, engine, 'settings', 'at_api_key', 'VARCHAR(255)')

        # ── Drop old broken unique constraint on van_stocks and recreate ───
        _fix_van_stocks_constraint(conn, engine)

        # ── Piece-selling: how many pieces make up one stocked unit ────────
        _add_column_if_missing(conn, engine, 'products', 'pieces_per_unit', 'INTEGER DEFAULT 1')

        # ── Piece-selling: widen quantity columns from INTEGER to FLOAT so a
        # sale/stock row can hold a fractional unit (e.g. 0.25 of a carton).
        # SQLite has no real column types (everything is dynamically typed,
        # so an "INTEGER" column already stores floats fine) — only Postgres
        # needs the actual ALTER COLUMN TYPE.
        _widen_quantity_columns_to_float(conn, engine)

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

        # ── Correct the originally-seeded 'tips' permissions, which granted
        # manager/sales_rep write access contradicting the module's own
        # documented read-only design ───────────────────────────────────────
        _repair_tips_permissions(db)

        log.info("Migrations applied successfully.")

    except Exception as e:
        log.warning(f"Migration warning (non-fatal): {e}")
    finally:
        conn.close()


def _add_column_if_missing(conn, engine, table, column, col_type):
    """Add a column to a table if it doesn't already exist.

    Inspects via `conn` (the same connection/transaction doing the ALTER),
    not `engine` (which opens a fresh connection). On Postgres, an ALTER
    TABLE holds a lock until commit — if a *different* connection tried to
    inspect that same table before this transaction commits, it would block
    waiting on its own uncommitted lock and hang forever. Inspecting through
    `conn` reads this transaction's own uncommitted state instead, so it
    never has to wait on itself. SQLite never hit this since it doesn't lock
    the same way, which is why this only ever surfaced against Postgres.
    """
    from sqlalchemy import text, inspect
    try:
        inspector = inspect(conn)
        tables = inspector.get_table_names()
        if table not in tables:
            return  # table doesn't exist yet — db.create_all() will make it
        existing = [c['name'] for c in inspector.get_columns(table)]
        if column not in existing:
            conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {col_type}'))
            log.info(f"Migration: added {table}.{column}")
    except Exception as e:
        log.debug(f"Column {table}.{column}: {e}")


def _widen_quantity_columns_to_float(conn, engine):
    """Postgres-only: widen quantity columns from INTEGER to DOUBLE PRECISION
    so piece-selling can store a fractional unit (e.g. 8.75 cartons). SQLite
    is skipped — its columns are dynamically typed, so an "INTEGER"-declared
    column already stores a float value without any schema change needed.
    Safe to re-run: ALTER COLUMN TYPE to the same type is a no-op on Postgres."""
    if engine.dialect.name != 'postgresql':
        return
    from sqlalchemy import text, inspect
    targets = [
        ('products', 'stock_quantity'),
        ('van_stocks', 'quantity'),
        ('sale_items', 'quantity'),
        ('inventory_movements', 'quantity'),
        ('inventory_movements', 'quantity_before'),
        ('inventory_movements', 'quantity_after'),
        ('stock_offload_items', 'quantity_declared'),
        ('stock_offload_items', 'quantity_received'),
    ]
    try:
        inspector = inspect(conn)
        tables = inspector.get_table_names()
        for table, column in targets:
            if table not in tables:
                continue
            conn.execute(text(
                f'ALTER TABLE {table} ALTER COLUMN {column} TYPE DOUBLE PRECISION'
            ))
        log.info("Migration: widened quantity columns to FLOAT for piece-selling.")
    except Exception as e:
        log.debug(f"widen quantity columns: {e}")


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
        # A failed query leaves the session's transaction aborted on Postgres
        # (unlike SQLite) — every later query in this request would fail too
        # unless we roll back here, e.g. on a fresh DB where 'sales' doesn't
        # exist yet (this runs before db.create_all()).
        db.session.rollback()
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
        db.session.rollback()
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
        db.session.rollback()
        log.debug(f"historical tip backfill skipped: {e}")


def _repair_tips_permissions(db):
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
        # Inspect via `conn`, not `engine` — see _add_column_if_missing's
        # docstring for why a separate connection can deadlock on Postgres.
        inspector = inspect(conn)
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
                quantity     FLOAT DEFAULT 0,
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
