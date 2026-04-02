"""
Database schema definition and migration runner.

All DDL lives here. Call `ensure_schema(db_path)` once when a library is
opened; it is idempotent and handles forward migrations via a `schema_version`
user_version pragma.
"""

import sqlite3
import logging
from pathlib import Path

from teletag.db.connection import get_connection

logger = logging.getLogger(__name__)

# Bump this integer whenever a new migration is added.
CURRENT_VERSION = 1

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_CREATE_LIBRARIES = """
CREATE TABLE IF NOT EXISTS libraries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    root_path   TEXT    NOT NULL UNIQUE
);
"""

_CREATE_FILES = """
CREATE TABLE IF NOT EXISTS files (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    library_id      INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
    relative_path   TEXT    NOT NULL,
    xxhash          TEXT    NOT NULL,
    duration        REAL,               -- seconds
    resolution      TEXT,               -- e.g. "1920x1080"
    codec           TEXT,
    thumbnail_path  TEXT,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(library_id, relative_path)
);
"""

_CREATE_TAGS = """
CREATE TABLE IF NOT EXISTS tags (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    library_id  INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
    name        TEXT    NOT NULL,
    parent_id   INTEGER REFERENCES tags(id) ON DELETE SET NULL,
    UNIQUE(library_id, name, parent_id)
);
"""

_CREATE_TAG_CLOSURE = """
CREATE TABLE IF NOT EXISTS tag_closure (
    ancestor_id     INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    descendant_id   INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    depth           INTEGER NOT NULL,
    PRIMARY KEY (ancestor_id, descendant_id)
);
"""

_CREATE_FILE_TAGS = """
CREATE TABLE IF NOT EXISTS file_tags (
    file_id     INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    tag_id      INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (file_id, tag_id)
);
"""

_CREATE_ENCODE_JOBS = """
CREATE TABLE IF NOT EXISTS encode_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id         INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    preset          TEXT    NOT NULL,   -- hap | dxv | h264 | prores | webm
    output_width    INTEGER,
    output_height   INTEGER,
    scale_mode      TEXT,               -- resize | fit | fill | stretch
    status          TEXT    NOT NULL DEFAULT 'queued',  -- queued|running|done|error
    output_path     TEXT,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
"""

_CREATE_WATCH_FOLDERS = """
CREATE TABLE IF NOT EXISTS watch_folders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    library_id      INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
    path            TEXT    NOT NULL UNIQUE,
    auto_tag_ids    TEXT    DEFAULT '[]',  -- JSON array of tag ids
    enabled         INTEGER NOT NULL DEFAULT 1
);
"""

# ---------------------------------------------------------------------------
# Indexes
# ---------------------------------------------------------------------------

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_files_xxhash       ON files(xxhash);",
    "CREATE INDEX IF NOT EXISTS idx_files_library_id   ON files(library_id);",
    "CREATE INDEX IF NOT EXISTS idx_file_tags_file_id  ON file_tags(file_id);",
    "CREATE INDEX IF NOT EXISTS idx_file_tags_tag_id   ON file_tags(tag_id);",
    "CREATE INDEX IF NOT EXISTS idx_closure_ancestor   ON tag_closure(ancestor_id);",
    "CREATE INDEX IF NOT EXISTS idx_closure_descendant ON tag_closure(descendant_id);",
]

# ---------------------------------------------------------------------------
# Migration list — append new (version, sql) tuples to extend the schema.
# ---------------------------------------------------------------------------

_MIGRATIONS: list[tuple[int, str]] = [
    # Version 1 — initial schema (all tables + indexes created above via
    # CREATE TABLE IF NOT EXISTS, so migrations here are for ALTER TABLE etc.)
    (1, "SELECT 1;"),  # no-op placeholder; initial tables created unconditionally
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ensure_schema(db_path: Path) -> None:
    """
    Create tables and run any pending migrations for the database at *db_path*.
    Safe to call multiple times.
    """
    conn = get_connection(db_path)
    _create_tables(conn)
    _run_migrations(conn)


def _create_tables(conn: sqlite3.Connection) -> None:
    with conn:
        for ddl in [
            _CREATE_LIBRARIES,
            _CREATE_FILES,
            _CREATE_TAGS,
            _CREATE_TAG_CLOSURE,
            _CREATE_FILE_TAGS,
            _CREATE_ENCODE_JOBS,
            _CREATE_WATCH_FOLDERS,
        ]:
            conn.execute(ddl)
        for idx_sql in _INDEXES:
            conn.execute(idx_sql)


def _run_migrations(conn: sqlite3.Connection) -> None:
    current: int = conn.execute("PRAGMA user_version").fetchone()[0]
    if current >= CURRENT_VERSION:
        return

    for version, sql in _MIGRATIONS:
        if version > current:
            logger.info("Applying DB migration to version %d", version)
            with conn:
                conn.executescript(sql)
                conn.execute(f"PRAGMA user_version={version}")

    logger.info("DB schema up-to-date at version %d", CURRENT_VERSION)
