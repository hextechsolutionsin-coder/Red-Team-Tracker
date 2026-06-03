"""
Integration-test conftest: SQLite compatibility patches.

The ORM models use PostgreSQL-specific DEFAULT expressions (gen_random_uuid(),
NOW(), TRUE, 'planned') in column `server_default` declarations.  SQLite's
DEFAULT clause accepts only literals and simple expressions — not function calls
with parentheses or boolean literals.

This conftest patches the SQLAlchemy metadata at import time (before any fixture
runs) so that `create_all` succeeds against the aiosqlite in-memory engine.

Strategy
--------
1. Walk every column in Base.metadata and null out any `server_default` whose
   SQL text contains a PostgreSQL-only token.
2. Register Python-level UDFs on every new SQLite connection so that
   gen_random_uuid() and char_length() work in DML (INSERT / SELECT).

Note: test helpers supply explicit values for all required fields (UUIDs,
timestamps, booleans) so the missing server defaults are never needed at
INSERT time in the integration tests.
"""

from __future__ import annotations

import uuid

from sqlalchemy import event
from sqlalchemy.engine import Engine


# ---------------------------------------------------------------------------
# Step 1 — Register SQLite UDFs so that DML works after table creation
# ---------------------------------------------------------------------------


def _register_udf(dbapi_conn, _record):
    """Add gen_random_uuid / char_length as Python UDFs into every SQLite conn."""
    try:
        dbapi_conn.create_function("gen_random_uuid", 0, lambda: str(uuid.uuid4()))
        dbapi_conn.create_function("char_length", 1, lambda s: len(s) if s is not None else None)
    except Exception:  # noqa: BLE001
        pass  # Already registered or not a real sqlite3 connection


@event.listens_for(Engine, "connect")
def _engine_connect(dbapi_conn, record):
    module = type(dbapi_conn).__module__
    if "sqlite" in module.lower():
        _register_udf(dbapi_conn, record)


# ---------------------------------------------------------------------------
# Step 2 — Strip PG-specific server_defaults before metadata.create_all runs
# ---------------------------------------------------------------------------

# Patterns that are NOT valid in SQLite DEFAULT clauses
_PG_TOKENS = frozenset({
    "GEN_RANDOM_UUID",
    "NOW()",
    "TRUE",
    "FALSE",
    "'PLANNED'",
    "'OPEN'",
    "'ACTIVE'",
    "'COMPLETED'",
    "'ARCHIVED'",
})


def _is_pg_default(server_default) -> bool:
    """Return True if this server_default contains PostgreSQL-only syntax."""
    if server_default is None:
        return False
    from sqlalchemy.sql.elements import TextClause

    # FetchedValue (no SQL expression) — keep as-is
    clause = getattr(server_default, "arg", None)
    if clause is None:
        return False
    text_val = ""
    if isinstance(clause, TextClause):
        text_val = clause.text.strip().upper()
    elif isinstance(clause, str):
        text_val = clause.strip().upper()
    return any(tok in text_val for tok in _PG_TOKENS)


def _patch_metadata():
    """
    Walk Base.metadata and remove PG-specific server_defaults.

    For UUID primary key columns using gen_random_uuid(), adds a Python-side
    ColumnDefault so INSERT statements in tests work without a server default.
    For NOT NULL timestamp columns, adds a Python-side ColumnDefault that calls
    datetime.now(utc).

    Returns a restore list of (column, original_server_default) tuples.
    """
    # Import here so the env vars are set first (conftest.py sets them before
    # importing any app modules)
    from app.database import Base
    import uuid as _uuid
    from datetime import datetime, timezone
    from sqlalchemy.schema import ColumnDefault

    def _gen_uuid():
        return _uuid.uuid4()

    def _now():
        return datetime.now(tz=timezone.utc)

    restore = []
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if _is_pg_default(col.server_default):
                restore.append((col, col.server_default))
                col.server_default = None

                # Add a Python-side ColumnDefault for UUID primary key columns
                # so INSERT without an explicit value gets a generated UUID.
                if col.primary_key and col.default is None:
                    col_type_str = type(col.type).__name__.upper()
                    if "UUID" in col_type_str:
                        col.default = ColumnDefault(_gen_uuid)

                # Add Python-side ColumnDefault for NOT NULL timestamp columns
                # (last_activity, created_at, updated_at)
                elif not col.primary_key and col.nullable is False and col.default is None:
                    col_type_str = type(col.type).__name__.upper()
                    if "TIMESTAMP" in col_type_str or "DATETIME" in col_type_str:
                        col.default = ColumnDefault(_now)

    return restore


# Run the patch at import time — this happens once when pytest collects this
# conftest before any fixtures execute.
_RESTORE_LIST = _patch_metadata()
