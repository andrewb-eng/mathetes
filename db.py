"""Database connection and schema initialization."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "mathetes.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_connection() -> sqlite3.Connection:
    """Return a SQLite connection with sane defaults, creating data/ if needed."""
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # rows behave like dicts
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create the database file and run schema.sql. Idempotent."""
    schema_sql = SCHEMA_PATH.read_text()
    conn = get_connection()
    try:
        conn.executescript(schema_sql)
        conn.commit()
    finally:
        conn.close()
    print(f"DB ready at {DB_PATH}")


if __name__ == "__main__":
    init_db()