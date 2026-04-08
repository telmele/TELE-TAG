"""
Center panel — lazy-loading thumbnail grid with drag-out support.

Each card shows: thumbnail, filename, tag pills.
Right-click opens a context menu for dragging HAP/DXV transcodes.
"""

from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QScrollArea, QGridLayout, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame, QMenu, QRubberBand, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal, QMimeData, QUrl, QPoint, QRect, QSize, QTimer
from PyQt6.QtGui import QDrag, QCursor, QPainter

from teletag.db.connection import get_connection
from teletag.core.library import Library
from teletag.core.tags import get_descendant_ids
from teletag.ui.widgets.thumbnail import ThumbnailWidget
from teletag.ui.widgets.tag_pill import TagPill
from teletag.ui.widgets.video_preview import VideoPreviewPopup
from teletag.ui.theme import card_style

_CARD_W = 220
_CARD_SPACING = 12


class _ElidedLabel(QLabel):
    """Single-line label that draws '…' when text overflows its width."""

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(parent)
        self._full = text
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        m = self.contentsMargins()
        available = self.width() - m.left() - m.right()
        elided = self.fontMetrics().elidedText(
            self._full, Qt.TextElideMode.ElideRight, available
        )
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(self.contentsRect(), self.alignment(), elided)


_HOVER_DELAY_MS = 400   # delay before preview pops up


class VideoCard(QFrame):
    """Single card in the grid."""

    clicked     = pyqtSignal(int, object)   # file_id, Qt.KeyboardModifiers
    hover_enter = pyqtSignal(int, str)      # file_id, abs_path
    hover_leave = pyqtSignal(int)           # file_id

    def __init__(self, file_row: dict, tags: list, parent=None) -> None:
        super().__init__(parent)
        self._file = file_row
        self._abs_path = str(Path(file_row["root_path"]) / file_row["relative_path"])
        self._selected = False
        self._setup_ui(tags)
        self.setFixedWidth(_CARD_W)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)

        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(_HOVER_DELAY_MS)
        self._hover_timer.timeout.connect(
            lambda: self.hover_enter.emit(self._file["id"], self._abs_path)
        )

    def _setup_ui(self, tags: list) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 6)
        layout.setSpacing(0)

        self.thumb = ThumbnailWidget(self._file.get("thumbnail_path"))
        layout.addWidget(self.thumb)

        rel = self._file["relative_path"]
        name = _ElidedLabel(Path(rel).name)
        name.setStyleSheet("font-size: 11px; padding: 5px 8px 2px 8px;")
        layout.addWidget(name)
        self.setToolTip(rel)

        # Tag pills
        pills_layout = QHBoxLayout()
        pills_layout.setSpacing(4)
        pills_layout.setContentsMargins(8, 4, 8, 0)
        for tag in tags[:4]:
            pills_layout.addWidget(TagPill(tag["name"]))
        if len(tags) > 4:
            pills_layout.addWidget(QLabel(f"+{len(tags)-4}"))
        pills_layout.addStretch()
        layout.addLayout(pills_layout)

        self._apply_style()

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._apply_style()

    def _apply_style(self) -> None:
        self.setStyleSheet(card_style(self._selected))

    def enterEvent(self, event) -> None:  # type: ignore[override]
        self._hover_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self._hover_timer.stop()
        # When the preview popup appears over the thumbnail, Windows sends a
        # spurious WM_MOUSELEAVE to this card even though the cursor hasn't
        # actually left its bounds.  Only emit hover_leave when the cursor
        # is genuinely outside the card.
        if not self.rect().contains(self.mapFromGlobal(QCursor.pos())):
            self.hover_leave.emit(self._file["id"])
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._file["id"], event.modifiers())
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


class _GridContainer(QWidget):
    """
    The inner widget that holds cards.
    Handles rubber-band drag-selection on empty space between cards.
    Emits rubber_selected(QRect, modifiers) when a meaningful drag finishes.
    """

    rubber_selected = pyqtSignal(object, object)   # QRect, Qt.KeyboardModifiers

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rb = QRubberBand(QRubberBand.Shape.Rectangle, self)
        self._origin: QPoint | None = None

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.position().toPoint()
            self._rb.setGeometry(QRect(self._origin, QSize(0, 0)))
            self._rb.show()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._origin and (event.buttons() & Qt.MouseButton.LeftButton):
            self._rb.setGeometry(
                QRect(self._origin, event.position().toPoint()).normalized()
            )
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton and self._origin is not None:
            rect = QRect(self._origin, event.position().toPoint()).normalized()
            self._rb.hide()
            self._origin = None
            # Only treat as rubber-band if the user actually dragged a few pixels.
            if rect.width() > 5 or rect.height() > 5:
                self.rubber_selected.emit(rect, event.modifiers())
        super().mouseReleaseEvent(event)


class GridPanel(QWidget):
    """Scrollable grid of VideoCards."""

    file_selected       = pyqtSignal(int)   # file_id (single, backwards compat)
    selection_changed   = pyqtSignal(list)  # list[int] file_ids
    fullscreen_requested = pyqtSignal(int)  # file_id

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._library: Library | None = None
        self._active_tag_id: int = -1
        self._search_text: str = ""
        self._selected_ids: set[int] = set()
        self._cards: dict[int, VideoCard] = {}
        self._card_order: list[int] = []
        self._anchor_id: int | None = None

        self._preview = VideoPreviewPopup()
        self._preview_file_id: int | None = None
        self._preview.clicked.connect(self._on_preview_clicked)
        self._hide_preview_timer = QTimer(self)
        self._hide_preview_timer.setSingleShot(True)
        self._hide_preview_timer.setInterval(120)
        self._hide_preview_timer.timeout.connect(self._preview.hide_preview)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._setup_ui()

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(self._scroll)

        self._container = _GridContainer()
        self._container.rubber_selected.connect(self._on_rubber_selected)
        self._grid = QGridLayout(self._container)
        self._grid.setSpacing(_CARD_SPACING)
        self._grid.setContentsMargins(8, 8, 8, 8)
        self._scroll.setWidget(self._container)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def set_library(self, library: Library) -> None:
        self._preview.hide_preview()
        self._library = library
        self._active_tag_id = -1
        self._selected_ids.clear()
        self._anchor_id = None
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
        self._cards.clear()
        self._card_order.clear()

        if self._library is None:
            return

        files = self._query_files()
        cols = max(1, self._scroll.viewport().width() // (_CARD_W + _CARD_SPACING))
        self._card_order = []

        for i, (file_row, tags) in enumerate(files):
            card = VideoCard(file_row, tags)
            fid = file_row["id"]
            self._card_order.append(fid)
            card.set_selected(fid in self._selected_ids)
            card.clicked.connect(self._on_card_clicked)
            card.hover_enter.connect(self._on_card_hover_enter)
            card.hover_leave.connect(self._on_card_hover_leave)
            self._cards[fid] = card
            self._grid.addWidget(card, i // cols, i % cols)

        # Padding item
        self._grid.setRowStretch(self._grid.rowCount(), 1)

    def _on_card_clicked(self, file_id: int, modifiers) -> None:
        ctrl  = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)

        if shift and self._anchor_id is not None and self._anchor_id in self._card_order:
            # Range select from anchor to clicked card (inclusive).
            a = self._card_order.index(self._anchor_id)
            b = self._card_order.index(file_id) if file_id in self._card_order else a
            lo, hi = min(a, b), max(a, b)
            range_ids = set(self._card_order[lo : hi + 1])
            if ctrl:
                # Extend existing selection with the range.
                self._selected_ids |= range_ids
            else:
                # Replace selection with the range.
                self._selected_ids = range_ids
            for fid, card in self._cards.items():
                card.set_selected(fid in self._selected_ids)
            # Do not move the anchor on shift-click.

        elif ctrl:
            # Toggle individual card; set anchor.
            if file_id in self._selected_ids:
                self._selected_ids.discard(file_id)
                if file_id in self._cards:
                    self._cards[file_id].set_selected(False)
            else:
                self._selected_ids.add(file_id)
                if file_id in self._cards:
                    self._cards[file_id].set_selected(True)
            self._anchor_id = file_id

        else:
            # Plain click — exclusive select; set anchor.
            for fid, card in self._cards.items():
                card.set_selected(fid == file_id)
            self._selected_ids = {file_id}
            self._anchor_id = file_id
            self.file_selected.emit(file_id)

        self.setFocus()
        self.selection_changed.emit(sorted(self._selected_ids))

    # ------------------------------------------------------------------
    # Hover preview
    # ------------------------------------------------------------------

    def _on_card_hover_enter(self, file_id: int, abs_path: str) -> None:
        self._hide_preview_timer.stop()
        card = self._cards.get(file_id)
        if card is None:
            return
        self._preview_file_id = file_id
        # Position the popup exactly over the card's thumbnail widget
        thumb = card.thumb
        self._preview.show_for(
            abs_path,
            thumb.mapToGlobal(QPoint(0, 0)),
            thumb.size(),
        )

    def _on_card_hover_leave(self, _file_id: int) -> None:
        self._hide_preview_timer.start()

    def _on_preview_clicked(self) -> None:
        if self._preview_file_id is not None:
            self._on_card_clicked(self._preview_file_id, Qt.KeyboardModifier.NoModifier)

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Space and self._selected_ids:
            fid = (
                self._anchor_id
                if self._anchor_id in self._selected_ids
                else next(iter(self._selected_ids))
            )
            self._hide_preview_timer.stop()
            self._preview.hide_preview()
            self.fullscreen_requested.emit(fid)
        else:
            super().keyPressEvent(event)

    def _on_rubber_selected(self, rect: QRect, modifiers) -> None:
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        hit_ids = {
            fid for fid, card in self._cards.items()
            if rect.intersects(card.geometry())
        }
        if not hit_ids:
            return
        if ctrl:
            self._selected_ids |= hit_ids
        else:
            self._selected_ids = hit_ids
        # Rubber-band resets the shift-click anchor to the last hit card.
        self._anchor_id = self._card_order[
            max(self._card_order.index(fid) for fid in hit_ids)
        ] if hit_ids else None
        for fid, card in self._cards.items():
            card.set_selected(fid in self._selected_ids)
        self.selection_changed.emit(sorted(self._selected_ids))

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
