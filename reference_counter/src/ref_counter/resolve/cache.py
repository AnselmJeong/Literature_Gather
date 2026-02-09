from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


class ResolutionCache:
    def __init__(self, cache_dir: Path | None = None):
        root = cache_dir or (Path.home() / ".ref_counter" / "cache")
        root.mkdir(parents=True, exist_ok=True)
        self.db_path = root / "openalex.db"
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def get(self, key: str) -> dict | None:
        now = datetime.now(timezone.utc)
        with self._connect() as conn:
            row = conn.execute("SELECT value, expires_at FROM cache WHERE key = ?", (key,)).fetchone()
            if not row:
                return None
            value, expires_at = row
            if datetime.fromisoformat(expires_at) < now:
                conn.execute("DELETE FROM cache WHERE key = ?", (key,))
                conn.commit()
                return None
            return json.loads(value)

    def set(self, key: str, value: dict, ttl_days: int = 7) -> None:
        expires_at = (datetime.now(timezone.utc) + timedelta(days=ttl_days)).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cache(key, value, expires_at) VALUES(?,?,?)",
                (key, json.dumps(value), expires_at),
            )
            conn.commit()
