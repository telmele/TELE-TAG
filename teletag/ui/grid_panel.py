"""
Center panel — lazy-loading thumbnail grid with drag-out support.

Each card shows: thumbnail, filename, tag pills.
Right-click opens a context menu for dragging HAP/DXV transcodes.
"""

from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QScrollArea, QGridLayout, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame, QMenu,
)
from PyQt6.QtCore import Qt, pyqtSignal, QMimeData, QUrl, QPoint
from PyQt6.QtGui import QDrag

from teletag.db.connection import get_connection
from teletag.core.library import Library
from teletag.core.tags import get_descendant_ids
from teletag.ui.widgets.thumbnail import ThumbnailWidget
from teletag.ui.widgets.tag_pill import TagPill

_CARD_W = 220
_CARD_SPACING = 12


class VideoCard(QFrame):
    """Single card in the grid."""

    clicked = pyqtSignal(int)   # file_id

    def __init__(self, file_row: dict, tags: list, parent=None) -> None:
        super().__init__(parent)
        self._file = file_row
        self._abs_path = str(Path(file_row["root_path"]) / file_row["relative_path"])
        self._setup_ui(tags)
        self.setFixedWidth(_CARD_W)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)

    def _setup_ui(self, tags: list) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.thumb = ThumbnailWidget(self._file.get("thumbnail_path"))
        layout.addWidget(self.thumb)

        name = QLabel(Path(self._file["relative_path"]).name)
        name.setWordWrap(True)
        name.setStyleSheet("font-size: 11px;")
        layout.addWidget(name)

        # Tag pills
        pills_layout = QHBoxLayout()
        pills_layout.setSpacing(2)
        pills_layout.setContentsMargins(0, 0, 0, 0)
        for tag in tags[:4]:
            pills_layout.addWidget(TagPill(tag["name"]))
        if len(tags) > 4:
            pills_layout.addWidget(QLabel(f"+{len(tags)-4}"))
        pills_layout.addStretch()
        layout.addLayout(pills_layout)

        self.setStyleSheet("""
            VideoCard {
                background: #1e1e2e;
                border: 1px solid #333;
                border-radius: 6px;
            }
            VideoCard:hover {
                border: 1px solid #6a8fd8;
            }
        """)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._file["id"])
            self._drag_start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if event.buttons() & Qt.MouseButton.LeftButton:
            drag = QDrag(self)
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(self._abs_path)])
            drag.setMimeData(mime)
            drag.exec(Qt.DropAction.CopyAction)

    def _context_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)
        menu.addAction("Drag original").triggered.connect(
            lambda: self._start_drag(self._abs_path)
        )
        # TODO: query encode_jobs for HAP/DXV transcodes and offer to drag those.
        menu.exec(self.mapToGlobal(pos))

    def _start_drag(self, path: str) -> None:
        drag = QDrag(self)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(path)])
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)


class GridPanel(QWidget):
    """Scrollable grid of VideoCards."""

    file_selected = pyqtSignal(int)   # file_id

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._library: Library | None = None
        self._active_tag_id: int = -1
        self._search_text: str = ""
        self._setup_ui()

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(self._scroll)

        self._container = QWidget()
        self._grid = QGridLayout(self._container)
        self._grid.setSpacing(_CARD_SPACING)
        self._grid.setContentsMargins(8, 8, 8, 8)
        self._scroll.setWidget(self._container)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def set_library(self, library: Library) -> None:
        self._library = library
        self._active_tag_id = -1
        self.refresh()

    def set_tag_filter(self, tag_id: int) -> None:
        self._active_tag_id = tag_id
        self.refresh()

    def set_search(self, text: str) -> None:
        self._search_text = text.strip().lower()
        self.refresh()

    def refresh(self) -> None:
        # Clear existing cards.
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        if self._library is None:
            return

        files = self._query_files()
        cols = max(1, self._scroll.viewport().width() // (_CARD_W + _CARD_SPACING))

        for i, (file_row, tags) in enumerate(files):
            card = VideoCard(file_row, tags)
            card.clicked.connect(self.file_selected.emit)
            self._grid.addWidget(card, i // cols, i % cols)

        # Padding item
        self._grid.setRowStretch(self._grid.rowCount(), 1)

    def _query_files(self) -> list[tuple[dict, list]]:
        lib = self._library
        conn = get_connection(lib.db_path)

        # Resolve tag filter into descendant ids.
        if self._active_tag_id > 0:
            tag_ids = get_descendant_ids(lib.db_path, self._active_tag_id)
            if not tag_ids:
                return []
            placeholders = ",".join("?" * len(tag_ids))
            rows = conn.execute(
                f"""
                SELECT f.*, l.root_path
                FROM files f
                JOIN libraries l ON l.id = f.library_id
                WHERE f.library_id = ?
                  AND f.id IN (
                      SELECT file_id FROM file_tags WHERE tag_id IN ({placeholders})
                  )
                ORDER BY f.relative_path
                """,
                [lib.id] + tag_ids,
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT f.*, l.root_path
                FROM files f
                JOIN libraries l ON l.id = f.library_id
                WHERE f.library_id = ?
                ORDER BY f.relative_path
                """,
                (lib.id,),
            ).fetchall()

        result = []
        for row in rows:
            file_dict = dict(row)
            if self._search_text and self._search_text not in file_dict["relative_path"].lower():
                continue
            tags = conn.execute(
                """
                SELECT t.name FROM tags t
                JOIN file_tags ft ON ft.tag_id = t.id
                WHERE ft.file_id = ?
                """,
                (file_dict["id"],),
            ).fetchall()
            result.append((file_dict, [dict(t) for t in tags]))

        return result

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self.refresh()
