"""
DB connection manager.

Every connection enables WAL mode so concurrent reads from the UI thread
never block writes from the ingest/watcher threads.
"""

import sqlite3
import threading
from pathlib import Path


# One connection per thread, per database path.
_local = threading.local()


def get_connection(db_path: Path) -> sqlite3.Connection:
    """
    Return a thread-local SQLite connection to *db_path*.

    WAL mode, foreign keys, and row-factory are configured on first open.
    """
    key = str(db_path.resolve())
    connections: dict = getattr(_local, "connections", {})
    if key not in connections:
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")   # safe with WAL
        connections[key] = conn
        _local.connections = connections
    return connections[key]


def close_all() -> None:
    """Close every thread-local connection (call on app shutdown)."""
    connections: dict = getattr(_local, "connections", {})
    for conn in connections.values():
        try:
            conn.close()
        except Exception:
            pass
    _local.connections = {}
