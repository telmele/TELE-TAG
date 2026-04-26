"""
Center panel — thumbnail grid with drag-out support.

Each card shows: thumbnail, filename, tag pills.
Right-click opens a context menu (delete, clear tags, add tag, drag).
Space bar opens the selected card fullscreen.
"""

from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QScrollArea, QGridLayout, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame, QMenu, QRubberBand, QSizePolicy, QMessageBox, QCheckBox,
    QComboBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QMimeData, QUrl, QPoint, QRect, QSize, QTimer
from PyQt6.QtGui import QDrag, QCursor, QPainter

import subprocess
import sys

from teletag.db.connection import get_connection
from teletag.core.library import Library
from teletag.core.tags import get_descendant_ids, get_tags_for_library, assign_tag
from teletag.core.ingest import extract_thumbnail
from teletag.ui.widgets.thumbnail import ThumbnailWidget
from teletag.ui.widgets.tag_pill import TagPill
from teletag.ui.theme import card_style

_CARD_W = 220
_CARD_SPACING = 12


def reveal_in_explorer(path: str) -> None:
    """Select *path* in the OS file manager."""
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", path])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    else:
        subprocess.Popen(["xdg-open", str(Path(path).parent)])


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



class VideoCard(QFrame):
    """Single card in the grid."""

    clicked                 = pyqtSignal(int, object)   # file_id, Qt.KeyboardModifiers
    context_menu_requested  = pyqtSignal(int, object)   # file_id, global QPoint

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

        # Tag pills — keep reference so update_tags() can repopulate
        self._pills_layout = QHBoxLayout()
        self._pills_layout.setSpacing(4)
        self._pills_layout.setContentsMargins(8, 4, 8, 0)
        self._fill_pills(tags)
        layout.addLayout(self._pills_layout)

        self._apply_style()

    def _fill_pills(self, tags: list) -> None:
        for tag in tags[:4]:
            self._pills_layout.addWidget(TagPill(tag["name"]))
        if len(tags) > 4:
            self._pills_layout.addWidget(QLabel(f"+{len(tags)-4}"))
        self._pills_layout.addStretch()

    def update_tags(self, tags: list) -> None:
        """Replace tag pills without rebuilding the whole card."""
        while self._pills_layout.count():
            item = self._pills_layout.takeAt(0)
            w = item.widget() if item else None
            if w:
                w.deleteLater()
        self._fill_pills(tags)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._apply_style()

    def _apply_style(self) -> None:
        self.setStyleSheet(card_style(self._selected))

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
        self.context_menu_requested.emit(self._file["id"], self.mapToGlobal(pos))

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

    file_selected          = pyqtSignal(int)   # file_id (single, backwards compat)
    selection_changed      = pyqtSignal(list)  # list[int] file_ids
    fullscreen_requested   = pyqtSignal(int)   # file_id
    tags_changed           = pyqtSignal()      # any tag assignment/removal/file deletion
    add_to_convert_queue   = pyqtSignal(list)  # list[int] file_ids

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._library: Library | None = None
        self._active_tag_id: int = -1
        self._search_text: str = ""
        self._selected_ids: set[int] = set()
        self._cards: dict[int, VideoCard] = {}
        self._card_order: list[int] = []
        self._anchor_id: int | None = None
        self._last_cols: int = 0

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._setup_ui()

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Filter bar ────────────────────────────────────────────────
        self._filter_bar = QWidget()
        self._filter_bar.setStyleSheet(
            "background: #16161f; border-bottom: 1px solid #2a2938;"
        )
        fb = QHBoxLayout(self._filter_bar)
        fb.setContentsMargins(8, 4, 8, 4)
        fb.setSpacing(8)

        def _flbl(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setStyleSheet("font-size: 11px; color: #6d6d7a; background: transparent;")
            return lbl

        fb.addWidget(_flbl("Resolution:"))
        self._res_combo = QComboBox()
        self._res_combo.setMinimumWidth(110)
        self._res_combo.addItem("Any", "")
        self._res_combo.currentIndexChanged.connect(self.refresh)
        fb.addWidget(self._res_combo)

        fb.addWidget(_flbl("Codec:"))
        self._codec_combo = QComboBox()
        self._codec_combo.setMinimumWidth(90)
        self._codec_combo.addItem("Any", "")
        self._codec_combo.currentIndexChanged.connect(self.refresh)
        fb.addWidget(self._codec_combo)

        fb.addWidget(_flbl("Tag:"))
        self._ftag_combo = QComboBox()
        self._ftag_combo.setMinimumWidth(110)
        self._ftag_combo.addItem("Any", -1)
        self._ftag_combo.currentIndexChanged.connect(self.refresh)
        fb.addWidget(self._ftag_combo)

        fb.addStretch()
        outer.addWidget(self._filter_bar)

        # ── Grid scroll area ──────────────────────────────────────────
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
        self._library = library
        self._active_tag_id = -1
        self._selected_ids.clear()
        self._anchor_id = None
        self._last_cols = 0  # force rebuild on next showEvent/resizeEvent
        self._populate_filters()
        self.refresh()

    def refresh_filters(self) -> None:
        """Repopulate filter combos from DB (call when tags/files change externally)."""
        self._populate_filters()

    def _populate_filters(self) -> None:
        if self._library is None:
            return
        conn = get_connection(self._library.db_path)

        def _reload(combo: QComboBox, rows: list, key: str, none_data) -> None:
            prev = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Any", none_data)
            for row in rows:
                val = row[0]
                if val:
                    combo.addItem(str(val), val if key != "tag" else row[1])
            idx = combo.findData(prev)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            combo.blockSignals(False)

        res_rows = conn.execute(
            "SELECT DISTINCT resolution FROM files WHERE library_id = ? AND resolution IS NOT NULL ORDER BY resolution",
            (self._library.id,),
        ).fetchall()
        _reload(self._res_combo, [(r[0], r[0]) for r in res_rows], "res", "")

        codec_rows = conn.execute(
            "SELECT DISTINCT codec FROM files WHERE library_id = ? AND codec IS NOT NULL ORDER BY codec",
            (self._library.id,),
        ).fetchall()
        _reload(self._codec_combo, [(r[0], r[0]) for r in codec_rows], "codec", "")

        tag_rows = conn.execute(
            """
            SELECT t.name, t.id FROM tags t
            WHERE t.library_id = ?
            ORDER BY t.name
            """,
            (self._library.id,),
        ).fetchall()
        _reload(self._ftag_combo, [(r[0], r[1]) for r in tag_rows], "tag", -1)

    def set_tag_filter(self, tag_id: int) -> None:
        self._active_tag_id = tag_id
        self.refresh()

    def set_search(self, text: str) -> None:
        self._search_text = text.strip().lower()
        self.refresh()

    def refresh(self) -> None:
        # Clear existing cards.
        # Clear old column stretches before rebuild.
        for c in range(self._grid.columnCount()):
            self._grid.setColumnStretch(c, 0)

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
        self._last_cols = cols
        self._card_order = []

        for i, (file_row, tags) in enumerate(files):
            card = VideoCard(file_row, tags)
            fid = file_row["id"]
            self._card_order.append(fid)
            card.set_selected(fid in self._selected_ids)
            card.clicked.connect(self._on_card_clicked)
            card.context_menu_requested.connect(self._on_card_context_menu)
            self._cards[fid] = card
            self._grid.addWidget(card, i // cols, i % cols)

        # Stretch column absorbs leftover horizontal space so cards stay left-aligned.
        self._grid.setColumnStretch(cols, 1)
        # Stretch row absorbs leftover vertical space.
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
    # Keyboard
    # ------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Space and self._selected_ids:
            fid = (
                self._anchor_id
                if self._anchor_id in self._selected_ids
                else next(iter(self._selected_ids))
            )
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

    # ------------------------------------------------------------------
    # Context menu (right-click)
    # ------------------------------------------------------------------

    def _on_card_context_menu(self, file_id: int, global_pos) -> None:
        # If the right-clicked card is not in the current selection, select only it.
        if file_id not in self._selected_ids:
            for fid, card in self._cards.items():
                card.set_selected(fid == file_id)
            self._selected_ids = {file_id}
            self._anchor_id = file_id
            self.selection_changed.emit([file_id])

        target_ids = list(self._selected_ids)
        n = len(target_ids)
        card = self._cards.get(file_id)

        menu = QMenu(self)

        # Drag original
        if card is not None:
            menu.addAction("Drag original").triggered.connect(
                lambda: card._start_drag(card._abs_path)
            )
            menu.addAction("Show in Explorer").triggered.connect(
                lambda: reveal_in_explorer(card._abs_path)
            )

        # Convert
        convert_label = f"Add {n} file{'s' if n > 1 else ''} to Convert Queue"
        menu.addAction(convert_label).triggered.connect(
            lambda: self.add_to_convert_queue.emit(list(target_ids))
        )

        menu.addSeparator()

        # Regenerate thumbnail
        regen_label = f"Regenerate thumbnail{'s' if n > 1 else ''}"
        menu.addAction(regen_label).triggered.connect(
            lambda: self._regenerate_thumbnails(list(target_ids))
        )

        menu.addSeparator()

        # Delete
        delete_label = f"Delete {n} file{'s' if n > 1 else ''} from library\u2026"
        menu.addAction(delete_label).triggered.connect(
            lambda: self._delete_files(list(target_ids))
        )

        menu.addSeparator()

        # Clear tags
        menu.addAction("Clear all tags").triggered.connect(
            lambda: self._clear_tags(list(target_ids))
        )

        # Add tag submenu
        if self._library is not None:
            tags = get_tags_for_library(self._library.db_path, self._library.id)
            if tags:
                tag_menu = menu.addMenu("Add tag")
                for tag in sorted(tags, key=lambda t: t.name):
                    tid = tag.id
                    tag_menu.addAction(tag.name).triggered.connect(
                        lambda checked=False, t=tid: self._add_tag_to_files(list(target_ids), t)
                    )

        menu.exec(global_pos)

    def _delete_files(self, file_ids: list[int]) -> None:
        if self._library is None:
            return
        n = len(file_ids)

        msg = QMessageBox(self)
        msg.setWindowTitle("Remove from library")
        msg.setText(f"Remove {n} file{'s' if n > 1 else ''} from the library?")
        msg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        cb = QCheckBox("Also delete from disk")
        msg.setCheckBox(cb)

        if msg.exec() != QMessageBox.StandardButton.Yes:
            return

        delete_from_disk = cb.isChecked()

        conn = get_connection(self._library.db_path)
        placeholders = ",".join("?" * len(file_ids))

        if delete_from_disk:
            rows = conn.execute(
                f"SELECT relative_path FROM files WHERE id IN ({placeholders})",
                file_ids,
            ).fetchall()
            paths_to_delete = [
                self._library.root_path / row["relative_path"] for row in rows
            ]

        with conn:
            conn.execute(f"DELETE FROM files WHERE id IN ({placeholders})", file_ids)

        if delete_from_disk:
            for p in paths_to_delete:
                p.unlink(missing_ok=True)

        self._selected_ids -= set(file_ids)
        self._anchor_id = None
        self.selection_changed.emit(sorted(self._selected_ids))
        self.refresh()
        self.tags_changed.emit()

    def _regenerate_thumbnails(self, file_ids: list[int]) -> None:
        if self._library is None:
            return
        conn = get_connection(self._library.db_path)
        placeholders = ",".join("?" * len(file_ids))
        rows = conn.execute(
            f"SELECT id, relative_path, xxhash FROM files WHERE id IN ({placeholders})",
            file_ids,
        ).fetchall()

        for row in rows:
            abs_path = self._library.root_path / row["relative_path"]
            thumb_path = self._library.thumbs_dir / (row["xxhash"] + ".jpg")
            success = extract_thumbnail(abs_path, thumb_path)
            with conn:
                conn.execute(
                    "UPDATE files SET thumbnail_path = ? WHERE id = ?",
                    (str(thumb_path) if success else None, row["id"]),
                )

        self.refresh()

    def _clear_tags(self, file_ids: list[int]) -> None:
        if self._library is None:
            return
        conn = get_connection(self._library.db_path)
        placeholders = ",".join("?" * len(file_ids))
        with conn:
            conn.execute(f"DELETE FROM file_tags WHERE file_id IN ({placeholders})", file_ids)
        self.update_cards_tags(file_ids)
        self._populate_filters()
        self.tags_changed.emit()

    def _add_tag_to_files(self, file_ids: list[int], tag_id: int) -> None:
        if self._library is None:
            return
        for fid in file_ids:
            assign_tag(self._library.db_path, fid, tag_id)
        self.update_cards_tags(file_ids)
        self._populate_filters()
        self.tags_changed.emit()

    def update_cards_tags(self, file_ids: list[int]) -> None:
        """Refresh only the tag pills on the given cards — no full rebuild."""
        if self._library is None:
            return
        conn = get_connection(self._library.db_path)
        for fid in file_ids:
            card = self._cards.get(fid)
            if card is None:
                continue
            tags = conn.execute(
                """
                SELECT t.name FROM tags t
                JOIN file_tags ft ON ft.tag_id = t.id
                WHERE ft.file_id = ?
                """,
                (fid,),
            ).fetchall()
            card.update_tags([dict(t) for t in tags])

    def _query_files(self) -> list[tuple[dict, list]]:
        lib = self._library
        conn = get_connection(lib.db_path)

        conditions: list[str] = ["f.library_id = ?"]
        params: list = [lib.id]

        # Left-panel hierarchical tag filter.
        if self._active_tag_id > 0:
            tag_ids = get_descendant_ids(lib.db_path, self._active_tag_id)
            if not tag_ids:
                return []
            ph = ",".join("?" * len(tag_ids))
            conditions.append(
                f"f.id IN (SELECT file_id FROM file_tags WHERE tag_id IN ({ph}))"
            )
            params.extend(tag_ids)

        # Filter-bar tag filter (flat, with descendants).
        ftag_id = self._ftag_combo.currentData()
        if ftag_id and ftag_id > 0:
            ftag_ids = get_descendant_ids(lib.db_path, ftag_id)
            if not ftag_ids:
                return []
            ph2 = ",".join("?" * len(ftag_ids))
            conditions.append(
                f"f.id IN (SELECT file_id FROM file_tags WHERE tag_id IN ({ph2}))"
            )
            params.extend(ftag_ids)

        # Resolution filter.
        res_val = self._res_combo.currentData()
        if res_val:
            conditions.append("f.resolution = ?")
            params.append(res_val)

        # Codec filter.
        codec_val = self._codec_combo.currentData()
        if codec_val:
            conditions.append("f.codec = ?")
            params.append(codec_val)

        where = " AND ".join(conditions)
        rows = conn.execute(
            f"""
            SELECT f.*, l.root_path
            FROM files f
            JOIN libraries l ON l.id = f.library_id
            WHERE {where}
            ORDER BY f.relative_path
            """,
            params,
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

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        # Recompute layout now that the window has real dimensions.
        new_cols = max(1, self._scroll.viewport().width() // (_CARD_W + _CARD_SPACING))
        if new_cols != self._last_cols:
            self.refresh()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        new_cols = max(1, self._scroll.viewport().width() // (_CARD_W + _CARD_SPACING))
        if new_cols != self._last_cols:
            self.refresh()
