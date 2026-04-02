"""
Tag management — create, delete, rename, hierarchical queries.

The closure table `tag_closure` stores (ancestor_id, descendant_id, depth)
for every ancestor/descendant pair so that a single SELECT can return all
files tagged with any descendant of a given tag.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from teletag.db.connection import get_connection

logger = logging.getLogger(__name__)


@dataclass
class Tag:
    id: int
    library_id: int
    name: str
    parent_id: int | None
    file_count: int = 0
    children: list["Tag"] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------

def create_tag(db_path: Path, library_id: int, name: str, parent_id: int | None = None) -> Tag:
    """Insert a tag and populate the closure table."""
    conn = get_connection(db_path)
    with conn:
        cur = conn.execute(
            "INSERT INTO tags (library_id, name, parent_id) VALUES (?, ?, ?)",
            (library_id, name, parent_id),
        )
        tag_id = cur.lastrowid

        # Self-row in closure table.
        conn.execute(
            "INSERT INTO tag_closure (ancestor_id, descendant_id, depth) VALUES (?, ?, 0)",
            (tag_id, tag_id),
        )

        # Inherit all ancestors of parent.
        if parent_id is not None:
            conn.execute(
                """
                INSERT INTO tag_closure (ancestor_id, descendant_id, depth)
                SELECT ancestor_id, ?, depth + 1
                FROM tag_closure
                WHERE descendant_id = ?
                """,
                (tag_id, parent_id),
            )

    return Tag(id=tag_id, library_id=library_id, name=name, parent_id=parent_id)


def delete_tag(db_path: Path, tag_id: int) -> None:
    """
    Delete a tag and its descendants from both `tags` and `tag_closure`.
    `file_tags` rows are removed via ON DELETE CASCADE.
    """
    conn = get_connection(db_path)
    with conn:
        # Collect all descendants (inclusive).
        rows = conn.execute(
            "SELECT descendant_id FROM tag_closure WHERE ancestor_id = ?",
            (tag_id,),
        ).fetchall()
        ids = [r["descendant_id"] for r in rows]
        placeholders = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM tags WHERE id IN ({placeholders})", ids)


def rename_tag(db_path: Path, tag_id: int, new_name: str) -> None:
    conn = get_connection(db_path)
    with conn:
        conn.execute("UPDATE tags SET name = ? WHERE id = ?", (new_name, tag_id))


def assign_tag(db_path: Path, file_id: int, tag_id: int) -> None:
    conn = get_connection(db_path)
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO file_tags (file_id, tag_id) VALUES (?, ?)",
            (file_id, tag_id),
        )


def remove_tag(db_path: Path, file_id: int, tag_id: int) -> None:
    conn = get_connection(db_path)
    with conn:
        conn.execute(
            "DELETE FROM file_tags WHERE file_id = ? AND tag_id = ?",
            (file_id, tag_id),
        )


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------

def get_tags_for_library(db_path: Path, library_id: int) -> list[Tag]:
    """Return all tags for *library_id* with file counts, unsorted."""
    conn = get_connection(db_path)
    rows = conn.execute(
        """
        SELECT t.id, t.library_id, t.name, t.parent_id,
               COUNT(DISTINCT ft.file_id) AS file_count
        FROM tags t
        LEFT JOIN tag_closure tc ON tc.ancestor_id = t.id
        LEFT JOIN file_tags ft ON ft.tag_id = tc.descendant_id
        WHERE t.library_id = ?
        GROUP BY t.id
        """,
        (library_id,),
    ).fetchall()
    return [
        Tag(
            id=r["id"],
            library_id=r["library_id"],
            name=r["name"],
            parent_id=r["parent_id"],
            file_count=r["file_count"],
        )
        for r in rows
    ]


def build_tag_tree(tags: list[Tag]) -> list[Tag]:
    """
    Build a forest (list of root Tags with .children populated) from a flat list.
    """
    by_id = {t.id: t for t in tags}
    roots: list[Tag] = []
    for tag in tags:
        if tag.parent_id is None or tag.parent_id not in by_id:
            roots.append(tag)
        else:
            by_id[tag.parent_id].children.append(tag)
    return roots


def get_tags_for_file(db_path: Path, file_id: int) -> list[Tag]:
    conn = get_connection(db_path)
    rows = conn.execute(
        """
        SELECT t.id, t.library_id, t.name, t.parent_id
        FROM tags t
        JOIN file_tags ft ON ft.tag_id = t.id
        WHERE ft.file_id = ?
        """,
        (file_id,),
    ).fetchall()
    return [Tag(id=r["id"], library_id=r["library_id"], name=r["name"], parent_id=r["parent_id"]) for r in rows]


def get_descendant_ids(db_path: Path, tag_id: int) -> list[int]:
    """Return tag_id plus all descendant ids via the closure table."""
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT descendant_id FROM tag_closure WHERE ancestor_id = ?",
        (tag_id,),
    ).fetchall()
    return [r["descendant_id"] for r in rows]
