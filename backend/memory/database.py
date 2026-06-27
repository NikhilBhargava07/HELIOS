## Provides Postgres connections, schema initialization, and JSON conversion.

import os
from datetime import date, datetime, timezone
from decimal import Decimal
from threading import Lock
from uuid import UUID

from backend.config import PROJECT_ROOT

SCHEMA_PATH = PROJECT_ROOT / "db" / "init.sql"
_schema_ready = False
_schema_lock = Lock()


## Return the required Postgres URL without embedding credentials in code.
def get_database_url():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL must be configured in .env")
    return database_url


## Open a dictionary-row Postgres connection.
def get_connection():
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(get_database_url(), row_factory=dict_row)


## Wrap values for JSONB insertion without importing psycopg in DynamoDB mode.
def jsonb(value):
    from psycopg.types.json import Jsonb

    return Jsonb(value)


## Recursively convert database-specific values into JSON-safe types.
def json_safe(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    return value


## Return the current timezone-aware UTC timestamp.
def utc_now():
    return datetime.now(timezone.utc)


## Apply the idempotent SQL schema once per application process.
def ensure_schema():
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
        _schema_ready = True
