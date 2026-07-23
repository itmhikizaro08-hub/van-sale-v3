"""
Database migration helper — runs on every startup.
Safely adds new columns to existing tables without breaking existing data.

One-time historical data repairs (fixing rows left inconsistent by a past
bug, as opposed to structural schema changes) live in services/data_repairs.py
instead — this file is schema-only.
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

        # ── Recurring visit cycle on routes ─────────────────────────────────
        _add_column_if_missing(conn, engine, 'routes', 'visit_frequency_days', 'INTEGER')
        _add_column_if_missing(conn, engine, 'routes', 'visit_window_days', 'INTEGER')

        conn.commit()

        # ── One-time historical data repairs — see services/data_repairs.py
        # for what each one fixes and why. Kept in their own module, separate
        # from the structural ALTER TABLE work above.
        from services.data_repairs import (
            repair_sale_payment_status,
            repair_customer_outstanding_balance,
            repair_historical_tip_amounts,
            repair_tips_permissions,
        )
        repair_sale_payment_status(db)
        repair_customer_outstanding_balance(db)
        repair_historical_tip_amounts(db)
        repair_tips_permissions(db)

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
