"""Restore business data from a backup produced by services/backup.py.

Two restore modes, chosen by the admin at restore time:
- wipe: delete every row in every restorable table (children first, the
  reverse of backup_tables()' FK-safe order), then insert every row from the
  uploaded file. Destructive and irreversible.
- merge: insert only rows whose primary key isn't already present; existing
  rows are left untouched and nothing is ever deleted.

Only tables returned by backup.backup_tables() are ever touched — a sheet or
CSV named e.g. "users" in an uploaded file is silently ignored, so a
tampered or hand-edited upload can't be used to smuggle in a write to a
security-sensitive table that was never part of a real backup.
"""
import io
import math
import zipfile
import pandas as pd
from app import db
from services.backup import backup_tables


def restorable_tables():
    return {t.name: t for t in backup_tables()}


def read_upload(file_storage):
    """Return {table_name: DataFrame} from an uploaded .xlsx or .zip backup file.

    Unrecognized sheets/CSVs (tables not in restorable_tables()) are dropped.
    """
    filename = (file_storage.filename or '').lower()
    data = file_storage.read()
    tables = restorable_tables()
    result = {}
    if filename.endswith('.xlsx'):
        sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, engine='openpyxl')
        by_prefix = {name[:31]: name for name in tables}
        for sheet_name, df in sheets.items():
            table_name = by_prefix.get(sheet_name)
            if table_name:
                result[table_name] = df
    elif filename.endswith('.zip'):
        zf = zipfile.ZipFile(io.BytesIO(data))
        for name in zf.namelist():
            if not name.endswith('.csv'):
                continue
            table_name = name[:-4]
            if table_name in tables:
                result[table_name] = pd.read_csv(io.BytesIO(zf.read(name)))
    else:
        raise ValueError('Unsupported file type — upload the .xlsx or .zip file produced by Backup Data.')
    return result


def _coerce_value(value, col_type):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    type_name = col_type.__class__.__name__
    if type_name in ('DateTime', 'TIMESTAMP', 'Date'):
        ts = pd.to_datetime(value)
        return ts.to_pydatetime() if type_name != 'Date' else ts.date()
    if type_name == 'Boolean':
        if isinstance(value, str):
            return value.strip().lower() in ('1', 'true', 't', 'yes')
        return bool(value)
    if type_name in ('Integer', 'SmallInteger', 'BigInteger'):
        return int(value)
    if type_name in ('Float', 'Numeric'):
        f = float(value)
        return None if math.isnan(f) else f
    return value


def _rows_from_df(table, df):
    cols = {c.name: c for c in table.columns}
    keep_cols = [c for c in df.columns if c in cols]
    rows = []
    for _, row in df[keep_cols].iterrows():
        rows.append({name: _coerce_value(row[name], cols[name].type) for name in keep_cols})
    return rows


def _reset_sequences(tables):
    """After bulk inserts with explicit PKs, Postgres SERIAL sequences must be
    advanced past the highest inserted id or the next ORM-generated insert
    will collide. No-op on SQLite (rowid-based, not sequence-based)."""
    bind = db.session.get_bind()
    if bind.dialect.name != 'postgresql':
        return
    for table in tables:
        for col in table.primary_key.columns:
            if col.type.__class__.__name__ not in ('Integer', 'BigInteger', 'SmallInteger'):
                continue
            seq = db.session.execute(
                db.text("SELECT pg_get_serial_sequence(:t, :c)"),
                {'t': table.name, 'c': col.name},
            ).scalar()
            if not seq:
                continue
            db.session.execute(db.text(
                f"SELECT setval('{seq}', COALESCE((SELECT MAX({col.name}) FROM {table.name}), 1), "
                f"(SELECT MAX({col.name}) FROM {table.name}) IS NOT NULL)"
            ))
    db.session.commit()


def restore_wipe(dataframes):
    order = backup_tables()
    summary = {'wiped': [], 'inserted': {}}
    try:
        for table in reversed(order):
            db.session.execute(table.delete())
            summary['wiped'].append(table.name)
        for table in order:
            df = dataframes.get(table.name)
            if df is None or df.empty:
                summary['inserted'][table.name] = 0
                continue
            rows = _rows_from_df(table, df)
            if rows:
                db.session.execute(table.insert(), rows)
            summary['inserted'][table.name] = len(rows)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    _reset_sequences(order)
    return summary


def restore_merge(dataframes):
    order = backup_tables()
    summary = {'inserted': {}, 'skipped_existing': {}}
    try:
        for table in order:
            df = dataframes.get(table.name)
            if df is None or df.empty:
                summary['inserted'][table.name] = 0
                summary['skipped_existing'][table.name] = 0
                continue
            pk_cols = list(table.primary_key.columns)
            rows = _rows_from_df(table, df)
            if len(pk_cols) == 1:
                pk_name = pk_cols[0].name
                existing_ids = {r[0] for r in db.session.execute(db.select(table.c[pk_name]))}
                new_rows = [r for r in rows if r.get(pk_name) not in existing_ids]
                skipped = len(rows) - len(new_rows)
            else:
                new_rows = rows
                skipped = 0
            if new_rows:
                db.session.execute(table.insert(), new_rows)
            summary['inserted'][table.name] = len(new_rows)
            summary['skipped_existing'][table.name] = skipped
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    _reset_sequences(order)
    return summary
