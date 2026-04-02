"""
File system watcher — monitors library roots and watch folders using watchdog.

Emits Qt signals so the UI thread can refresh without polling.
"""

import logging
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal
from watchdog.events import FileSystemEventHandler, FileSystemEvent
from watchdog.observers import Observer

from teletag.core.library import Library
from teletag.core.ingest import ingest_single, VIDEO_EXTENSIONS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Qt signal carrier
# ---------------------------------------------------------------------------

class WatcherSignals(QObject):
    """Signals emitted by the background watchdog handler."""
    file_added = pyqtSignal(int, str)     # (library_id, abs_path)
    file_deleted = pyqtSignal(int, str)   # (library_id, relative_path)
    file_moved = pyqtSignal(int, str, str)  # (library_id, old_rel, new_rel)
    inbox_file_added = pyqtSignal(str)    # abs_path — watch-folder new file


# ---------------------------------------------------------------------------
# Watchdog event handler
# ---------------------------------------------------------------------------

class _LibraryHandler(FileSystemEventHandler):
    def __init__(self, library: Library, signals: WatcherSignals) -> None:
        super().__init__()
        self._library = library
        self._signals = signals

    def _is_video(self, path: str) -> bool:
        return Path(path).suffix.lower() in VIDEO_EXTENSIONS

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory or not self._is_video(event.src_path):
            return
        abs_path = Path(event.src_path)
        file_id = ingest_single(self._library, abs_path)
        if file_id is not None:
            self._signals.file_added.emit(self._library.id, str(abs_path))

    def on_deleted(self, event: FileSystemEvent) -> None:
        if event.is_directory or not self._is_video(event.src_path):
            return
        try:
            rel = str(Path(event.src_path).relative_to(self._library.root_path))
        except ValueError:
            return
        from teletag.db.connection import get_connection
        conn = get_connection(self._library.db_path)
        with conn:
            conn.execute(
                "DELETE FROM files WHERE library_id = ? AND relative_path = ?",
                (self._library.id, rel),
            )
        self._signals.file_deleted.emit(self._library.id, rel)

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        try:
            old_rel = str(Path(event.src_path).relative_to(self._library.root_path))
            new_rel = str(Path(event.dest_path).relative_to(self._library.root_path))
        except ValueError:
            return
        from teletag.db.connection import get_connection
        conn = get_connection(self._library.db_path)
        with conn:
            conn.execute(
                "UPDATE files SET relative_path = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                "WHERE library_id = ? AND relative_path = ?",
                (new_rel, self._library.id, old_rel),
            )
        self._signals.file_moved.emit(self._library.id, old_rel, new_rel)


class _WatchFolderHandler(FileSystemEventHandler):
    def __init__(self, signals: WatcherSignals) -> None:
        super().__init__()
        self._signals = signals

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        if Path(event.src_path).suffix.lower() in VIDEO_EXTENSIONS:
            self._signals.inbox_file_added.emit(str(event.src_path))


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class FileWatcher:
    """
    Manages a single watchdog Observer with multiple watched paths.
    Call `start()` once; use `watch_library()` and `watch_folder()` to add paths.
    """

    def __init__(self, signals: WatcherSignals) -> None:
        self._signals = signals
        self._observer = Observer()
        self._started = False

    def watch_library(self, library: Library) -> None:
        handler = _LibraryHandler(library, self._signals)
        self._observer.schedule(handler, str(library.root_path), recursive=True)
        logger.info("Watching library: %s", library.root_path)

    def watch_folder(self, path: Path) -> None:
        handler = _WatchFolderHandler(self._signals)
        self._observer.schedule(handler, str(path), recursive=False)
        logger.info("Watching inbox folder: %s", path)

    def start(self) -> None:
        if not self._started:
            self._observer.start()
            self._started = True

    def stop(self) -> None:
        if self._started:
            self._observer.stop()
            self._observer.join()
            self._started = False
