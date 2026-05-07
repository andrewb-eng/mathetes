"""Database connection and schema initialization."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "mathetes.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_connection():
    """Return a SQLite connection with sane defaults."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # rows behave like dicts
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create the database file and run schema.sql. Idempotent."""
    DB_PATH.parent.mkdir(exist_ok=True)
    schema_sql = SCHEMA_PATH.read_text()
    with get_connection() as conn:
        conn.executescript(schema_sql)
    print(f"DB ready at {DB_PATH}")


if __name__ == "__main__":
    init_db()