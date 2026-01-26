"""SQLite database connection and initialization."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from citation_snowball.config import DATABASE_FILE_NAME, get_project_dir

# Path to schema file
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_db_path(base_path: Path | None = None) -> Path:
    """Get the database file path."""
    return get_project_dir(base_path) / DATABASE_FILE_NAME


def init_database(db_path: Path) -> None:
    """Initialize database with schema."""
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_PATH.read_text())
        conn.commit()


@contextmanager
def get_connection(db_path: Path) -> Generator[sqlite3.Connection, None, None]:
    """Get a database connection with row factory."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


class Database:
    """Database manager for a project."""

    def __init__(self, base_path: Path | None = None):
        self.db_path = get_db_path(base_path)
        self._ensure_initialized()

    def _ensure_initialized(self) -> None:
        """Ensure database is initialized."""
        if not self.db_path.exists():
            init_database(self.db_path)

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get a database connection."""
        with get_connection(self.db_path) as conn:
            yield conn

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute a single SQL statement."""
        with self.connection() as conn:
            cursor = conn.execute(sql, params)
            conn.commit()
            return cursor

    def executemany(self, sql: str, params_list: list[tuple]) -> sqlite3.Cursor:
        """Execute SQL statement with multiple parameter sets."""
        with self.connection() as conn:
            cursor = conn.executemany(sql, params_list)
            conn.commit()
            return cursor

    def fetchone(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        """Execute and fetch one row."""
        with self.connection() as conn:
            cursor = conn.execute(sql, params)
            return cursor.fetchone()

    def fetchall(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        """Execute and fetch all rows."""
        with self.connection() as conn:
            cursor = conn.execute(sql, params)
            return cursor.fetchall()
