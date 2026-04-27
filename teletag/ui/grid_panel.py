"""
Center panel — thumbnail grid + table/list view, togglable.

Grid view: cards with thumbnail, filename, tag pills.
Table view: sortable rows with configurable columns (right-click header).
Right-click opens context menu on either view.
"""

from pathlib import Path
from itertools import groupby

from PyQt6.QtWidgets import (
    QWidget, QScrollArea, QGridLayout, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame, QMenu, QRubberBand, QSizePolicy, QMessageBox, QCheckBox,
    QComboBox, QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QHeaderView,
)
from PyQt6.QtCore import (
    Qt, pyqtSignal, QMimeData, QUrl, QPoint, QRect, QSize, QTimer,
    QSettings, QItemSelectionModel,
)
from PyQt6.QtGui import QDrag, QCursor, QPainter, QColor, QBrush, QFont

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

# Table column definitions: (key, label, default_visible)
_TABLE_COLS = [
    ("name",       "Name",       True),
    ("duration",   "Duration",   True),
    ("resolution", "Resolution", True),
    ("codec",      "Codec",      True),
    ("tags",       "Tags",       True),
    ("path",       "Path",       False),
    ("added",      "Added",      False),
]
_TABLE_COL_IDX: dict[str, int] = {k: i for i, (k, *_) in enumerate(_TABLE_COLS)}

_RES_BUCKETS = [
    ("SD",  0,    576),
    ("HD",  577,  899),
    ("FHD", 900,  1199),
    ("2K",  1200, 1599),
    ("4K",  1600, 4319),
    ("8K+", 4320, 99999),
]


def _res_height(res_str: str) -> int | None:
    try:
        return int(res_str.split("x", 1)[1])
    except (IndexError, ValueError):
        return None


def _fmt_duration(secs: float | None) -> str:
    if not secs:
        return "—"
    m, s = divmod(int(secs), 60)
    return f"{m}:{s:02d}"


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
            if rect.width() > 5 or rect.height() > 5:
                self.rubber_selected.emit(rect, event.modifiers())
        super().mouseReleaseEvent(event)


class GridPanel(QWidget):
    """Scrollable grid + table view of library files."""

    file_selected          = pyqtSignal(int)
    selection_changed      = pyqtSignal(list)
    fullscreen_requested   = pyqtSignal(int)
    tags_changed           = pyqtSignal()
    add_to_convert_queue   = pyqtSignal(list)

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
        self._view_mode: str = QSettings().value("grid_panel/view_mode", "grid")
        self._group_by_folder: bool = QSettings().value("grid_panel/group_by_folder", False, type=bool)
        self._col_visibility: dict[str, bool] = self._load_col_visibility()

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

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
        self._res_btn_widget = QWidget()
        self._res_btn_layout = QHBoxLayout(self._res_btn_widget)
        self._res_btn_layout.setContentsMargins(0, 0, 0, 0)
        self._res_btn_layout.setSpacing(3)
        self._res_buttons: dict[str, QPushButton] = {}
        self._active_res_bucket: str | None = None
        fb.addWidget(self._res_btn_widget)

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

        # View toggle buttons
        self._btn_grid = QPushButton("⊞ Grid")
        self._btn_table = QPushButton("≡ List")
        for btn in (self._btn_grid, self._btn_table):
            btn.setCheckable(True)
            btn.setFixedHeight(22)
            btn.setStyleSheet("font-size: 11px; padding: 0 10px;")
        self._btn_grid.setChecked(self._view_mode == "grid")
        self._btn_table.setChecked(self._view_mode == "table")
        self._btn_grid.clicked.connect(lambda: self._switch_view("grid"))
        self._btn_table.clicked.connect(lambda: self._switch_view("table"))
        fb.addWidget(self._btn_grid)
        fb.addWidget(self._btn_table)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("background: #2a2938; max-width: 1px; margin: 3px 2px;")
        fb.addWidget(sep)

        self._btn_folders = QPushButton("📁 Folders")
        self._btn_folders.setCheckable(True)
        self._btn_folders.setChecked(self._group_by_folder)
        self._btn_folders.setFixedHeight(22)
        self._btn_folders.setStyleSheet("font-size: 11px; padding: 0 10px;")
        self._btn_folders.clicked.connect(self._toggle_folder_grouping)
        fb.addWidget(self._btn_folders)

        outer.addWidget(self._filter_bar)

        # ── Stacked view (grid | table) ───────────────────────────────
        self._stack = QStackedWidget()
        outer.addWidget(self._stack)

        # Page 0 — Grid
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._container = _GridContainer()
        self._container.rubber_selected.connect(self._on_rubber_selected)
        self._grid = QGridLayout(self._container)
        self._grid.setSpacing(_CARD_SPACING)
        self._grid.setContentsMargins(8, 8, 8, 8)
        self._scroll.setWidget(self._container)
        self._stack.addWidget(self._scroll)

        # Page 1 — Table
        self._table = QTableWidget()
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSortingEnabled(True)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionsMovable(True)
        self._table.horizontalHeader().setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._table.horizontalHeader().customContextMenuRequested.connect(
            self._on_header_ctx_menu
        )
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_table_right_click)
        self._table.doubleClicked.connect(self._on_table_double_clicked)
        self._table.selectionModel().selectionChanged.connect(
            self._on_table_selection_changed
        )
        self._init_table_columns()
        self._stack.addWidget(self._table)

        self._stack.setCurrentIndex(0 if self._view_mode == "grid" else 1)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def set_library(self, library: Library) -> None:
        self._library = library
        self._active_tag_id = -1
        self._active_res_bucket = None
        self._selected_ids.clear()
        self._anchor_id = None
        self._last_cols = 0
        self._populate_filters()
        self.refresh()

    def refresh_filters(self) -> None:
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

        heights = []
        for row in conn.execute(
            "SELECT DISTINCT resolution FROM files WHERE library_id = ? AND resolution IS NOT NULL",
            (self._library.id,),
        ).fetchall():
            h = _res_height(row[0])
            if h is not None:
                heights.append(h)

        active_labels = {"Any"}
        for label, lo, hi in _RES_BUCKETS:
            if any(lo <= h <= hi for h in heights):
                active_labels.add(label)

        current_labels = set(self._res_buttons.keys())
        if active_labels != current_labels:
            while self._res_btn_layout.count():
                item = self._res_btn_layout.takeAt(0)
                if item.widget():
                    item.widget().setParent(None)
            self._res_buttons.clear()
            for label in ["Any"] + [b[0] for b in _RES_BUCKETS if b[0] in active_labels]:
                btn = QPushButton(label)
                btn.setCheckable(True)
                btn.setFixedHeight(22)
                btn.setStyleSheet("font-size: 11px; padding: 0 8px;")
                btn.clicked.connect(lambda _checked=False, l=label: self._on_res_btn(l))
                self._res_btn_layout.addWidget(btn)
                self._res_buttons[label] = btn
            self._res_btn_widget.updateGeometry()

        if self._active_res_bucket not in self._res_buttons:
            self._active_res_bucket = None
        self._sync_res_buttons()

        codec_rows = conn.execute(
            "SELECT DISTINCT codec FROM files WHERE library_id = ? AND codec IS NOT NULL ORDER BY codec",
            (self._library.id,),
        ).fetchall()
        _reload(self._codec_combo, [(r[0], r[0]) for r in codec_rows], "codec", "")

        tag_rows = conn.execute(
            "SELECT t.name, t.id FROM tags t WHERE t.library_id = ? ORDER BY t.name",
            (self._library.id,),
        ).fetchall()
        _reload(self._ftag_combo, [(r[0], r[1]) for r in tag_rows], "tag", -1)

    def _on_res_btn(self, label: str) -> None:
        self._active_res_bucket = None if label == "Any" else label
        self._sync_res_buttons()
        self.refresh()

    def _sync_res_buttons(self) -> None:
        active = self._active_res_bucket or "Any"
        for label, btn in self._res_buttons.items():
            btn.setChecked(label == active)

    def set_tag_filter(self, tag_id: int) -> None:
        self._active_tag_id = tag_id
        self.refresh()

    def set_search(self, text: str) -> None:
        self._search_text = text.strip().lower()
        self.refresh()

    def refresh(self) -> None:
        if self._view_mode == "table":
            self._populate_table()
        else:
            self._populate_grid()

    # ------------------------------------------------------------------
    # Grid view
    # ------------------------------------------------------------------

    def _populate_grid(self) -> None:
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

        def _folder_key(entry: tuple) -> str:
            p = str(Path(entry[0]["relative_path"]).parent)
            return "(root)" if p == "." else p

        def _add_card(file_row: dict, tags: list, grow: int, gcol: int) -> None:
            card = VideoCard(file_row, tags)
            fid = file_row["id"]
            self._card_order.append(fid)
            card.set_selected(fid in self._selected_ids)
            card.clicked.connect(self._on_card_clicked)
            card.context_menu_requested.connect(self._on_card_context_menu)
            self._cards[fid] = card
            self._grid.addWidget(card, grow, gcol)

        if self._group_by_folder:
            grow, gcol = 0, 0
            for folder, group_iter in groupby(files, key=_folder_key):
                group_list = list(group_iter)
                if gcol > 0:
                    grow += 1
                    gcol = 0
                hdr = QLabel(f"  📁  {folder}")
                hdr.setFixedHeight(28)
                hdr.setStyleSheet(
                    "background: #21202e; color: #6d6d7a; font-size: 11px;"
                    " font-weight: 600; letter-spacing: 0.4px;"
                    " border-bottom: 1px solid #292736; padding-left: 4px;"
                )
                self._grid.addWidget(hdr, grow, 0, 1, cols)
                grow += 1
                for file_row, tags in group_list:
                    _add_card(file_row, tags, grow, gcol)
                    gcol += 1
                    if gcol >= cols:
                        gcol = 0
                        grow += 1
                if gcol > 0:
                    grow += 1
                    gcol = 0
        else:
            for i, (file_row, tags) in enumerate(files):
                _add_card(file_row, tags, i // cols, i % cols)

        self._grid.setColumnStretch(cols, 1)
        self._grid.setRowStretch(self._grid.rowCount(), 1)

    def _on_card_clicked(self, file_id: int, modifiers) -> None:
        ctrl  = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)

        if shift and self._anchor_id is not None and self._anchor_id in self._card_order:
            a = self._card_order.index(self._anchor_id)
            b = self._card_order.index(file_id) if file_id in self._card_order else a
            lo, hi = min(a, b), max(a, b)
            range_ids = set(self._card_order[lo : hi + 1])
            if ctrl:
                self._selected_ids |= range_ids
            else:
                self._selected_ids = range_ids
            for fid, card in self._cards.items():
                card.set_selected(fid in self._selected_ids)
        elif ctrl:
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
            for fid, card in self._cards.items():
                card.set_selected(fid == file_id)
            self._selected_ids = {file_id}
            self._anchor_id = file_id
            self.file_selected.emit(file_id)

        self.setFocus()
        self.selection_changed.emit(sorted(self._selected_ids))

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
        self._anchor_id = self._card_order[
            max(self._card_order.index(fid) for fid in hit_ids)
        ] if hit_ids else None
        for fid, card in self._cards.items():
            card.set_selected(fid in self._selected_ids)
        self.selection_changed.emit(sorted(self._selected_ids))

    # ------------------------------------------------------------------
    # Table view
    # ------------------------------------------------------------------

    def _init_table_columns(self) -> None:
        self._table.setColumnCount(len(_TABLE_COLS))
        self._table.setHorizontalHeaderLabels([lbl for _, lbl, _ in _TABLE_COLS])
        hdr = self._table.horizontalHeader()
        for key, _, default in _TABLE_COLS:
            col = _TABLE_COL_IDX[key]
            hidden = not self._col_visibility.get(key, default)
            self._table.setColumnHidden(col, hidden)
        # Initial column widths
        hdr.resizeSection(_TABLE_COL_IDX["name"],       200)
        hdr.resizeSection(_TABLE_COL_IDX["duration"],    65)
        hdr.resizeSection(_TABLE_COL_IDX["resolution"],  90)
        hdr.resizeSection(_TABLE_COL_IDX["codec"],       80)
        hdr.resizeSection(_TABLE_COL_IDX["tags"],       160)
        hdr.resizeSection(_TABLE_COL_IDX["added"],       90)

    def _populate_table(self) -> None:
        if self._library is None:
            self._table.setRowCount(0)
            return

        files = self._query_files()
        self._card_order = [fd["id"] for fd, _ in files]

        def _folder_key(entry: tuple) -> str:
            p = str(Path(entry[0]["relative_path"]).parent)
            return "(root)" if p == "." else p

        # Build flat row list — optionally inserting folder header rows
        row_data: list[tuple] = []
        if self._group_by_folder:
            for folder, group_iter in groupby(files, key=_folder_key):
                row_data.append(("folder", folder))
                row_data.extend(("file", fd, tgs) for fd, tgs in group_iter)
        else:
            row_data.extend(("file", fd, tgs) for fd, tgs in files)

        _folder_bg = QBrush(QColor("#21202e"))
        _folder_fg = QBrush(QColor("#6d6d7a"))
        _folder_font = QFont()
        _folder_font.setBold(True)
        _folder_font.setPointSize(9)
        _no_flags = Qt.ItemFlag.ItemIsEnabled   # selectable=False

        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(row_data))

        for row_idx, entry in enumerate(row_data):
            if entry[0] == "folder":
                folder_name = entry[1]
                for col in range(len(_TABLE_COLS)):
                    cell = QTableWidgetItem(f"  📁  {folder_name}" if col == 0 else "")
                    cell.setFlags(_no_flags)
                    cell.setBackground(_folder_bg)
                    cell.setForeground(_folder_fg)
                    cell.setFont(_folder_font)
                    self._table.setItem(row_idx, col, cell)
                self._table.setRowHeight(row_idx, 24)
            else:
                _, file_dict, tags = entry
                fid = file_dict["id"]
                vals = {
                    "name":       Path(file_dict["relative_path"]).name,
                    "duration":   _fmt_duration(file_dict.get("duration")),
                    "resolution": file_dict.get("resolution") or "—",
                    "codec":      file_dict.get("codec") or "—",
                    "tags":       ", ".join(t["name"] for t in tags),
                    "path":       file_dict["relative_path"],
                    "added":      (file_dict.get("created_at") or "")[:10],
                }
                for key, _, _ in _TABLE_COLS:
                    col = _TABLE_COL_IDX[key]
                    cell = QTableWidgetItem(vals[key])
                    cell.setData(Qt.ItemDataRole.UserRole, fid)
                    cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self._table.setItem(row_idx, col, cell)

        # Sorting only makes sense in flat mode
        self._table.setSortingEnabled(not self._group_by_folder)
        self._table.resizeRowsToContents()

        # Restore selection without re-emitting signals
        sel = self._table.selectionModel()
        self._table.blockSignals(True)
        sel.clearSelection()
        sel_flags = (
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows
        )
        for row_idx in range(self._table.rowCount()):
            cell = self._table.item(row_idx, 0)
            if cell and cell.data(Qt.ItemDataRole.UserRole) in self._selected_ids:
                sel.select(self._table.model().index(row_idx, 0), sel_flags)
        self._table.blockSignals(False)

    def _on_table_selection_changed(self) -> None:
        fids: set[int] = set()
        for idx in self._table.selectionModel().selectedRows():
            item = self._table.item(idx.row(), 0)
            if item:
                fid = item.data(Qt.ItemDataRole.UserRole)
                if fid is not None:
                    fids.add(fid)
        self._selected_ids = fids
        self._anchor_id = next(iter(fids)) if fids else None
        self.selection_changed.emit(sorted(fids))
        if len(fids) == 1:
            self.file_selected.emit(next(iter(fids)))

    def _on_table_double_clicked(self, index) -> None:
        item = self._table.item(index.row(), 0)
        if item:
            fid = item.data(Qt.ItemDataRole.UserRole)
            if fid is not None:
                self.fullscreen_requested.emit(fid)

    def _on_table_right_click(self, pos: QPoint) -> None:
        item = self._table.itemAt(pos)
        if item is None:
            return
        fid = item.data(Qt.ItemDataRole.UserRole)
        if fid is None:
            return
        if fid not in self._selected_ids:
            self._table.clearSelection()
            self._table.selectRow(item.row())
            # _on_table_selection_changed fires and updates _selected_ids
        self._on_card_context_menu(fid, self._table.mapToGlobal(pos))

    def _on_header_ctx_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)
        for key, label, default in _TABLE_COLS:
            act = menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(self._col_visibility.get(key, default))
            act.toggled.connect(lambda checked, k=key: self._toggle_column(k, checked))
        menu.exec(self._table.horizontalHeader().mapToGlobal(pos))

    def _toggle_column(self, key: str, visible: bool) -> None:
        self._col_visibility[key] = visible
        self._table.setColumnHidden(_TABLE_COL_IDX[key], not visible)
        self._save_col_visibility()

    def _switch_view(self, mode: str) -> None:
        self._view_mode = mode
        self._btn_grid.setChecked(mode == "grid")
        self._btn_table.setChecked(mode == "table")
        self._stack.setCurrentIndex(0 if mode == "grid" else 1)
        QSettings().setValue("grid_panel/view_mode", mode)
        self.refresh()

    def _toggle_folder_grouping(self) -> None:
        self._group_by_folder = self._btn_folders.isChecked()
        QSettings().setValue("grid_panel/group_by_folder", self._group_by_folder)
        self.refresh()

    def _load_col_visibility(self) -> dict[str, bool]:
        result = {k: d for k, _, d in _TABLE_COLS}
        stored = QSettings().value("grid_panel/visible_columns")
        if stored:
            items = stored if isinstance(stored, list) else [stored]
            for entry in items:
                if "=" in entry:
                    k, v = entry.split("=", 1)
                    if k in result:
                        result[k] = v == "1"
        return result

    def _save_col_visibility(self) -> None:
        data = [f"{k}={'1' if v else '0'}" for k, v in self._col_visibility.items()]
        QSettings().setValue("grid_panel/visible_columns", data)

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

    # ------------------------------------------------------------------
    # Context menu (shared between grid and table)
    # ------------------------------------------------------------------

    def _on_card_context_menu(self, file_id: int, global_pos) -> None:
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

        if card is not None:
            menu.addAction("Drag original").triggered.connect(
                lambda: card._start_drag(card._abs_path)
            )
            menu.addAction("Show in Explorer").triggered.connect(
                lambda: reveal_in_explorer(card._abs_path)
            )
        elif self._library is not None:
            conn = get_connection(self._library.db_path)
            row = conn.execute(
                "SELECT relative_path FROM files WHERE id = ?", (file_id,)
            ).fetchone()
            if row:
                abs_path = str(self._library.root_path / row["relative_path"])
                menu.addAction("Show in Explorer").triggered.connect(
                    lambda: reveal_in_explorer(abs_path)
                )

        convert_label = f"Add {n} file{'s' if n > 1 else ''} to Convert Queue"
        menu.addAction(convert_label).triggered.connect(
            lambda: self.add_to_convert_queue.emit(list(target_ids))
        )

        menu.addSeparator()

        regen_label = f"Regenerate thumbnail{'s' if n > 1 else ''}"
        menu.addAction(regen_label).triggered.connect(
            lambda: self._regenerate_thumbnails(list(target_ids))
        )

        menu.addSeparator()

        delete_label = f"Delete {n} file{'s' if n > 1 else ''} from library…"
        menu.addAction(delete_label).triggered.connect(
            lambda: self._delete_files(list(target_ids))
        )

        menu.addSeparator()

        menu.addAction("Clear all tags").triggered.connect(
            lambda: self._clear_tags(list(target_ids))
        )

        if self._library is not None:
            tags = get_tags_for_library(self._library.db_path, self._library.id)
            assignable = [t for t in tags if t.tag_type == "tag"]
            if assignable:
                tag_menu = menu.addMenu("Add tag")
                for tag in sorted(assignable, key=lambda t: t.name):
                    tid = tag.id
                    tag_menu.addAction(tag.name).triggered.connect(
                        lambda checked=False, t=tid: self._add_tag_to_files(list(target_ids), t)
                    )

        menu.exec(global_pos)

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def _query_files(self) -> list[tuple[dict, list]]:
        lib = self._library
        conn = get_connection(lib.db_path)

        conditions: list[str] = ["f.library_id = ?"]
        params: list = [lib.id]

        if self._active_tag_id > 0:
            tag_ids = get_descendant_ids(lib.db_path, self._active_tag_id)
            if not tag_ids:
                return []
            ph = ",".join("?" * len(tag_ids))
            conditions.append(
                f"f.id IN (SELECT file_id FROM file_tags WHERE tag_id IN ({ph}))"
            )
            params.extend(tag_ids)

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

        if self._active_res_bucket:
            bucket = next((b for b in _RES_BUCKETS if b[0] == self._active_res_bucket), None)
            if bucket:
                _, lo, hi = bucket
                conditions.append(
                    "CAST(SUBSTR(f.resolution, INSTR(f.resolution,'x')+1) AS INTEGER) BETWEEN ? AND ?"
                )
                params.extend([lo, hi])

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

    # ------------------------------------------------------------------
    # Resize / show
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        new_cols = max(1, self._scroll.viewport().width() // (_CARD_W + _CARD_SPACING))
        if new_cols != self._last_cols:
            self.refresh()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        new_cols = max(1, self._scroll.viewport().width() // (_CARD_W + _CARD_SPACING))
        if new_cols != self._last_cols:
            self.refresh()
