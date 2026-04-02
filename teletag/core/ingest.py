"""
Ingest pipeline — scan folder → hash → ffprobe metadata → thumbnail.

Runs entirely in a worker thread; communicates progress back to the UI via
Qt signals (pass a QObject with signals, or use a simple callback).
"""

import json
import logging
import subprocess
from pathlib import Path
from typing import Callable

import xxhash

from teletag.db.connection import get_connection
from teletag.core.library import Library

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".mxf", ".m4v",
    ".flv", ".wmv", ".mpg", ".mpeg", ".ts", ".m2ts", ".hap",
}

THUMB_SECOND = 1  # seek to this timestamp for thumbnail extraction


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def hash_file(path: Path, chunk: int = 1 << 20) -> str:
    """Return the xxHash (xxh64) hex digest of *path*."""
    h = xxhash.xxh64()
    with open(path, "rb") as fh:
        while data := fh.read(chunk):
            h.update(data)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# FFprobe metadata
# ---------------------------------------------------------------------------

def probe_file(path: Path) -> dict:
    """
    Run ffprobe on *path* and return a dict with keys:
        duration  (float | None)
        resolution (str | None)  e.g. "1920x1080"
        codec     (str | None)
    """
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_streams", "-show_format",
                str(path),
            ],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
    except Exception as exc:
        logger.warning("ffprobe failed for %s: %s", path, exc)
        return {"duration": None, "resolution": None, "codec": None}

    duration = None
    resolution = None
    codec = None

    fmt = data.get("format", {})
    try:
        duration = float(fmt.get("duration") or 0) or None
    except (ValueError, TypeError):
        pass

    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            w = stream.get("width")
            h = stream.get("height")
            if w and h:
                resolution = f"{w}x{h}"
            codec = stream.get("codec_name")
            break

    return {"duration": duration, "resolution": resolution, "codec": codec}


# ---------------------------------------------------------------------------
# Thumbnail
# ---------------------------------------------------------------------------

def extract_thumbnail(src: Path, out_path: Path, seek: float = THUMB_SECOND) -> bool:
    """
    Extract a single frame from *src* at *seek* seconds and save as JPEG.
    Returns True on success.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", str(seek),
                "-i", str(src),
                "-frames:v", "1",
                "-vf", "scale=320:-1",
                "-q:v", "5",
                str(out_path),
            ],
            capture_output=True, timeout=30,
        )
        return out_path.exists()
    except Exception as exc:
        logger.warning("Thumbnail extraction failed for %s: %s", src, exc)
        return False


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _upsert_file(
    library: Library,
    relative_path: str,
    file_hash: str,
    meta: dict,
    thumb_path: str | None,
) -> int:
    """Insert or update a file row; return its id."""
    conn = get_connection(library.db_path)
    with conn:
        conn.execute(
            """
            INSERT INTO files
                (library_id, relative_path, xxhash, duration, resolution, codec, thumbnail_path)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(library_id, relative_path) DO UPDATE SET
                xxhash         = excluded.xxhash,
                duration       = excluded.duration,
                resolution     = excluded.resolution,
                codec          = excluded.codec,
                thumbnail_path = excluded.thumbnail_path,
                updated_at     = strftime('%Y-%m-%dT%H:%M:%fZ','now')
            """,
            (
                library.id,
                relative_path,
                file_hash,
                meta["duration"],
                meta["resolution"],
                meta["codec"],
                thumb_path,
            ),
        )
        row = conn.execute(
            "SELECT id FROM files WHERE library_id = ? AND relative_path = ?",
            (library.id, relative_path),
        ).fetchone()
    return row["id"]


def _delete_missing(library: Library, found_paths: set[str]) -> None:
    """Remove DB rows for files that are no longer present on disk."""
    conn = get_connection(library.db_path)
    rows = conn.execute(
        "SELECT id, relative_path FROM files WHERE library_id = ?",
        (library.id,),
    ).fetchall()
    to_delete = [r["id"] for r in rows if r["relative_path"] not in found_paths]
    if to_delete:
        with conn:
            placeholders = ",".join("?" * len(to_delete))
            conn.execute(f"DELETE FROM files WHERE id IN ({placeholders})", to_delete)
        logger.info("Removed %d stale file records", len(to_delete))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def scan_library(
    library: Library,
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> int:
    """
    Walk *library.root_path*, ingest every new/changed video file.

    *progress_cb(current, total, filename)* is called for each file if provided.
    Returns the number of files processed.
    """
    root = library.root_path
    teletag_dir = library.teletag_dir

    video_files = [
        p for p in root.rglob("*")
        if p.is_file()
        and p.suffix.lower() in VIDEO_EXTENSIONS
        and not str(p).startswith(str(teletag_dir))
    ]

    total = len(video_files)
    found_rel: set[str] = set()

    for idx, abs_path in enumerate(video_files, start=1):
        rel_path = str(abs_path.relative_to(root))
        found_rel.add(rel_path)

        if progress_cb:
            progress_cb(idx, total, abs_path.name)

        try:
            file_hash = hash_file(abs_path)
        except OSError as exc:
            logger.warning("Cannot read %s: %s", abs_path, exc)
            continue

        # Check if already up-to-date.
        conn = get_connection(library.db_path)
        existing = conn.execute(
            "SELECT id, xxhash FROM files WHERE library_id = ? AND relative_path = ?",
            (library.id, rel_path),
        ).fetchone()

        if existing and existing["xxhash"] == file_hash:
            continue  # no change

        meta = probe_file(abs_path)

        thumb_name = file_hash + ".jpg"
        thumb_path = library.thumbs_dir / thumb_name
        if not thumb_path.exists():
            extract_thumbnail(abs_path, thumb_path)

        thumb_rel = str(thumb_path) if thumb_path.exists() else None
        _upsert_file(library, rel_path, file_hash, meta, thumb_rel)
        logger.debug("Ingested: %s", rel_path)

    _delete_missing(library, found_rel)
    return total


def ingest_single(library: Library, abs_path: Path) -> int | None:
    """
    Ingest one file immediately (called from the file watcher).
    Returns the DB file id, or None on failure.
    """
    root = library.root_path
    try:
        rel_path = str(abs_path.relative_to(root))
    except ValueError:
        logger.warning("File %s is outside library root %s", abs_path, root)
        return None

    try:
        file_hash = hash_file(abs_path)
    except OSError as exc:
        logger.warning("Cannot read %s: %s", abs_path, exc)
        return None

    meta = probe_file(abs_path)

    thumb_name = file_hash + ".jpg"
    thumb_path = library.thumbs_dir / thumb_name
    if not thumb_path.exists():
        extract_thumbnail(abs_path, thumb_path)

    thumb_rel = str(thumb_path) if thumb_path.exists() else None
    return _upsert_file(library, rel_path, file_hash, meta, thumb_rel)
