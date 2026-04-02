"""
Library management — add, list, open.

A "library" is any folder on disk. When opened, a hidden `.teletag/`
sub-folder is created inside it containing `metadata.db`.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from teletag.db.connection import get_connection
from teletag.db.schema import ensure_schema

logger = logging.getLogger(__name__)

TELETAG_DIR = ".teletag"
DB_NAME = "metadata.db"
THUMBS_DIR = "thumbs"


@dataclass
class Library:
    id: int
    name: str
    root_path: Path

    @property
    def teletag_dir(self) -> Path:
        return self.root_path / TELETAG_DIR

    @property
    def db_path(self) -> Path:
        return self.teletag_dir / DB_NAME

    @property
    def thumbs_dir(self) -> Path:
        return self.teletag_dir / THUMBS_DIR


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _open_db(library: Library) -> None:
    """Ensure the .teletag directory exists and the schema is initialised."""
    library.teletag_dir.mkdir(parents=True, exist_ok=True)
    library.thumbs_dir.mkdir(parents=True, exist_ok=True)
    ensure_schema(library.db_path)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def add_library(name: str, root_path: Path) -> Library:
    """
    Register a new library.  If root_path is already registered its existing
    record is returned instead of raising an error.
    """
    root_path = root_path.resolve()
    library = Library(id=-1, name=name, root_path=root_path)
    _open_db(library)

    conn = get_connection(library.db_path)
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO libraries (name, root_path) VALUES (?, ?)",
            (name, str(root_path)),
        )
        row = conn.execute(
            "SELECT id, name, root_path FROM libraries WHERE root_path = ?",
            (str(root_path),),
        ).fetchone()

    lib = Library(id=row["id"], name=row["name"], root_path=Path(row["root_path"]))
    logger.info("Library '%s' opened at %s (id=%d)", lib.name, lib.root_path, lib.id)
    return lib


def list_libraries(db_path: Path) -> list[Library]:
    """Return all libraries stored in a given DB."""
    conn = get_connection(db_path)
    rows = conn.execute("SELECT id, name, root_path FROM libraries").fetchall()
    return [Library(id=r["id"], name=r["name"], root_path=Path(r["root_path"])) for r in rows]


def get_library(db_path: Path, library_id: int) -> Library | None:
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT id, name, root_path FROM libraries WHERE id = ?", (library_id,)
    ).fetchone()
    if row is None:
        return None
    return Library(id=row["id"], name=row["name"], root_path=Path(row["root_path"]))
