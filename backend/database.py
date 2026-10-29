"""SQLite access.

Three changes from the original worth knowing about:

1. The path comes from config, so the database can live on a mounted volume
   instead of inside the package directory. Previously it sat next to the
   source, which in a container means every image rebuild starts with an empty
   user table.

2. WAL mode and a busy timeout. The API writes from the request thread and the
   job worker writes from its own; the default rollback journal turns that into
   intermittent "database is locked" errors under exactly the load the app is
   for.

3. Connections are context-managed. The original closed by hand on the happy
   path only, so any exception between `get_connection()` and `close()` leaked
   the handle — and with SQLite a leaked write handle holds a lock.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from backend import config


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    """Yield a connection, committing on success and rolling back on error."""
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                failed_logins INTEGER NOT NULL DEFAULT 0,
                locked_until REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                video_path TEXT,
                clips_dir TEXT,
                basket_count INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )

        # Every authorised read of a job is "this id, belonging to this user".
        # Without the composite index that is a scan once a class's worth of
        # jobs accumulates.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_user ON jobs(user_id, created_at DESC)")

        # A database created before the lockout columns existed still has to
        # work. Doing it here keeps init_db the single schema entry point
        # rather than introducing a migration tool for two columns.
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
        if "failed_logins" not in existing:
            conn.execute("ALTER TABLE users ADD COLUMN failed_logins INTEGER NOT NULL DEFAULT 0")
        if "locked_until" not in existing:
            conn.execute("ALTER TABLE users ADD COLUMN locked_until REAL")
