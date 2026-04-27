"""
Left panel — pill-based tag browser organized into categories.

Structure:
  [◉ All Files]          ← always-on filter-clear chip
  ▼ CATEGORY ── [+]      ← collapsible section header
    [#tag ×] [#tag ×]    ← selectable, deletable pills (wrapping flow)
  ─ UNCATEGORIZED ─ [+]
    [#standalone ×]
  ─ META ─────────── [+]
    [§key ×]
  [+ Category]  [+ Tag]  [+ Meta]   ← bottom action bar
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QInputDialog, QMessageBox, QSizePolicy, QLayout,
    QLayoutItem,
)
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QPoint, QSize

from teletag.core.tags import Tag, get_tags_for_library, build_tag_tree, create_tag, delete_tag
from teletag.core.library import Library

_PILL_COLORS = [
    ("#2a1f42", "#a277ff"),
    ("#152e28", "#61ffca"),
    ("#2e2010", "#ffca85"),
    ("#2e1530", "#f694ff"),
    ("#2e1515", "#ff6767"),
    ("#152033", "#82e2ff"),
    ("#1a2e10", "#c3e88d"),
    ("#2e2a10", "#ffe073"),
]


def _pill_colors(name: str) -> tuple[str, str]:
    return _PILL_COLORS[hash(name) % len(_PILL_COLORS)]


# ---------------------------------------------------------------------------
# Flow layout
# ---------------------------------------------------------------------------

class _FlowLayout(QLayout):
    """Left-to-right wrapping layout."""

    def __init__(self, parent=None, h_spacing: int = 4, v_spacing: int = 4) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._h = h_spacing
        self._v = v_spacing

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), dry=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, dry=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect: QRect, dry: bool) -> int:
        m = self.contentsMargins()
        left = rect.x() + m.left()
        top = rect.y() + m.top()
        right = rect.right() - m.right()
        x, y, row_h = left, top, 0

        for item in self._items:
            w = item.widget()
            if w and not w.isVisible():
                continue
            hint = item.sizeHint()
            next_x = x + hint.width()
            if next_x > right and x > left:
                x = left
                y += row_h + self._v
                next_x = x + hint.width()
                row_h = 0
            if not dry:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x + self._h
            row_h = max(row_h, hint.height())

        return y + row_h - rect.y() + m.bottom()


# ---------------------------------------------------------------------------
# Tag chip (selectable + deletable pill)
# ---------------------------------------------------------------------------

class _TagChip(QWidget):
    clicked = pyqtSignal(int)
    delete_requested = pyqtSignal(int)

    def __init__(self, tag: Tag, parent=None) -> None:
        super().__init__(parent)
        self._tag = tag
        self._selected = False
        self._bg, self._fg = _pill_colors(tag.name)

        row = QHBoxLayout(self)
        row.setContentsMargins(5, 1, 2, 1)
        row.setSpacing(2)

        prefix = "§" if tag.tag_type == "meta" else "#"
        count = f" ({tag.file_count})" if tag.file_count else ""
        self._lbl = QLabel(f"{prefix} {tag.name}{count}")
        self._lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(self._lbl)

        self._del = QPushButton("×")
        self._del.setFixedSize(13, 13)
        self._del.setFlat(True)
        self._del.setCursor(Qt.CursorShape.PointingHandCursor)
        self._del.clicked.connect(lambda: self.delete_requested.emit(self._tag.id))
        row.addWidget(self._del)

        self.setFixedHeight(20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._apply_style(hover=False)

    def _apply_style(self, hover: bool) -> None:
        if self._selected:
            self.setStyleSheet(
                f"QWidget {{ background: {self._fg}; border-left: 2px solid {self._fg}; }}"
            )
            self._lbl.setStyleSheet(
                "background: transparent; border: none; color: #0d0d14;"
                " font-size: 10px; font-weight: 700; padding: 0 2px 0 0;"
            )
        else:
            self.setStyleSheet(
                f"QWidget {{ background: {self._bg}; border-left: 2px solid {self._fg}; }}"
            )
            self._lbl.setStyleSheet(
                f"background: transparent; border: none; color: {self._fg};"
                " font-size: 10px; font-weight: 700; padding: 0 2px 0 0;"
            )
        del_color = "#ff6767" if hover else "#3a3a4a"
        self._del.setStyleSheet(
            f"background: transparent; border: none; color: {del_color};"
            " font-size: 11px; font-weight: 700; padding: 0;"
        )

    def enterEvent(self, e) -> None:
        self._apply_style(hover=True)
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self._apply_style(hover=False)
        super().leaveEvent(e)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._tag.id)
        super().mousePressEvent(e)

    def set_selected(self, val: bool) -> None:
        self._selected = val
        self._apply_style(hover=False)

    @property
    def tag_id(self) -> int:
        return self._tag.id


# ---------------------------------------------------------------------------
# Section (category header + flowing chips)
# ---------------------------------------------------------------------------

class _Section(QWidget):
    tag_clicked = pyqtSignal(int)
    tag_delete_requested = pyqtSignal(int)
    add_tag_requested = pyqtSignal(int, str)   # (category_id | -1, tag_type)

    def __init__(
        self,
        title: str,
        category_id: int = -1,
        tag_type: str = "tag",
        collapsible: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._category_id = category_id
        self._tag_type = tag_type
        self._chips: list[_TagChip] = []
        self._collapsed = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 2)
        outer.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────
        hdr_widget = QWidget()
        hdr_row = QHBoxLayout(hdr_widget)
        hdr_row.setContentsMargins(6, 3, 4, 3)
        hdr_row.setSpacing(4)

        if collapsible:
            self._arrow_btn = QPushButton("▼")
            self._arrow_btn.setFixedSize(14, 14)
            self._arrow_btn.setFlat(True)
            self._arrow_btn.setStyleSheet(
                "color: #6d6d7a; font-size: 9px; background: transparent; border: none; padding: 0;"
            )
            self._arrow_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._arrow_btn.clicked.connect(self._toggle_collapse)
            hdr_row.addWidget(self._arrow_btn)
        else:
            self._arrow_btn = None

        title_lbl = QPushButton(title.upper())
        title_lbl.setFlat(True)
        title_lbl.setStyleSheet(
            "color: #6d6d7a; font-size: 10px; font-weight: 600; letter-spacing: 0.8px;"
            " background: transparent; border: none; text-align: left; padding: 0;"
        )
        if collapsible:
            title_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
            title_lbl.clicked.connect(self._toggle_collapse)
        hdr_row.addWidget(title_lbl, 1)

        add_btn = QPushButton("+")
        add_btn.setFixedSize(18, 18)
        add_btn.setFlat(True)
        add_btn.setStyleSheet(
            "color: #6d6d7a; font-size: 14px; font-weight: 400; background: transparent; border: none; padding: 0;"
            "QPushButton:hover { color: #edecee; }"
        )
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.clicked.connect(
            lambda: self.add_tag_requested.emit(self._category_id, self._tag_type)
        )
        hdr_row.addWidget(add_btn)

        # Thin separator line above header
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background: #252433; border: none; max-height: 1px;")
        outer.addWidget(sep)
        outer.addWidget(hdr_widget)

        # ── Flow container ────────────────────────────────────────────
        self._flow_host = QWidget()
        self._flow_host.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )
        self._flow = _FlowLayout(self._flow_host, h_spacing=4, v_spacing=4)
        self._flow.setContentsMargins(8, 4, 4, 6)
        outer.addWidget(self._flow_host)

    def _toggle_collapse(self) -> None:
        self._collapsed = not self._collapsed
        self._flow_host.setVisible(not self._collapsed)
        if self._arrow_btn:
            self._arrow_btn.setText("▶" if self._collapsed else "▼")

    def populate(self, tags: list[Tag], selected_id: int) -> None:
        # Clear old chips
        while self._flow.count():
            item = self._flow.takeAt(0)
            if item:
                w = item.widget()
                if w:
                    w.setParent(None)
        self._chips.clear()

        for tag in tags:
            chip = _TagChip(tag, parent=self._flow_host)
            chip.set_selected(tag.id == selected_id)
            chip.clicked.connect(self.tag_clicked)
            chip.delete_requested.connect(self.tag_delete_requested)
            self._flow.addWidget(chip)
            self._chips.append(chip)

        self._flow_host.updateGeometry()

    def update_selection(self, selected_id: int) -> None:
        for chip in self._chips:
            chip.set_selected(chip.tag_id == selected_id)


# ---------------------------------------------------------------------------
# TagPanel
# ---------------------------------------------------------------------------

class TagPanel(QWidget):
    tag_selected = pyqtSignal(int)   # tag_id; -1 = show all
    tags_changed = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._library: Library | None = None
        self._selected_tag_id: int = -1
        self._sections: list[_Section] = []
        self.setMinimumWidth(180)
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # "All Files" chip
        self._all_btn = QPushButton("◉  All Files")
        self._all_btn.setCheckable(True)
        self._all_btn.setChecked(True)
        self._all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._all_btn.setStyleSheet(
            "QPushButton {"
            "  background: #21202e; color: #a277ff;"
            "  border: none; border-bottom: 1px solid #292736;"
            "  border-left: 3px solid #a277ff;"
            "  text-align: left; padding: 8px 12px;"
            "  font-size: 12px; font-weight: 700;"
            "}"
            "QPushButton:checked {"
            "  background: #2a1f42; color: #a277ff;"
            "}"
            "QPushButton:hover { background: #252433; }"
        )
        self._all_btn.clicked.connect(self._on_all_clicked)
        outer.addWidget(self._all_btn)

        # Scrollable tag sections
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)
        self._content_layout.addStretch(1)

        scroll.setWidget(self._content)
        outer.addWidget(scroll, 1)

        # Bottom action bar
        bar = QWidget()
        bar.setStyleSheet("background: #1b1a23; border-top: 1px solid #292736;")
        bar_row = QHBoxLayout(bar)
        bar_row.setContentsMargins(6, 4, 6, 4)
        bar_row.setSpacing(4)

        for label, slot in [
            ("+ Category", self._on_add_category),
            ("+ Tag", lambda: self._on_add_tag(-1, "tag")),
            ("+ Meta", lambda: self._on_add_tag(-1, "meta")),
        ]:
            btn = QPushButton(label)
            btn.setStyleSheet(
                "QPushButton { background: #21202e; color: #6d6d7a; border: 1px solid #292736;"
                " padding: 3px 6px; font-size: 10px; font-weight: 600; }"
                "QPushButton:hover { color: #edecee; border-color: #a277ff; }"
            )
            btn.clicked.connect(slot)
            bar_row.addWidget(btn)

        outer.addWidget(bar)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_library(self, library: Library) -> None:
        self._library = library
        self.refresh()

    def refresh(self) -> None:
        # Remove existing sections
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item:
                w = item.widget()
                if w:
                    w.setParent(None)
        self._sections.clear()

        if self._library is None:
            self._content_layout.addStretch(1)
            return

        tags = get_tags_for_library(self._library.db_path, self._library.id)
        forest = build_tag_tree(tags)

        categories  = [t for t in forest if t.tag_type == "category"]
        orphan_tags = [t for t in forest if t.tag_type == "tag"]
        meta_tags   = [t for t in forest if t.tag_type == "meta"]

        def _make_section(title, tag_list, cat_id=-1, ttype="tag", collapsible=True):
            sec = _Section(title, category_id=cat_id, tag_type=ttype, collapsible=collapsible)
            sec.populate(tag_list, self._selected_tag_id)
            sec.tag_clicked.connect(self._on_tag_clicked)
            sec.tag_delete_requested.connect(self._on_delete_tag)
            sec.add_tag_requested.connect(self._on_add_tag)
            self._content_layout.addWidget(sec)
            self._sections.append(sec)

        for cat in categories:
            _make_section(cat.name, cat.children, cat_id=cat.id, ttype="tag", collapsible=True)

        if orphan_tags:
            _make_section("Uncategorized", orphan_tags, collapsible=False)

        if meta_tags:
            _make_section("Meta", meta_tags, ttype="meta", collapsible=False)

        self._content_layout.addStretch(1)
        self._all_btn.setChecked(self._selected_tag_id == -1)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _on_all_clicked(self) -> None:
        self._selected_tag_id = -1
        for sec in self._sections:
            sec.update_selection(-1)
        self._all_btn.setChecked(True)
        self.tag_selected.emit(-1)

    def _on_tag_clicked(self, tag_id: int) -> None:
        if self._selected_tag_id == tag_id:
            self._selected_tag_id = -1
            self.tag_selected.emit(-1)
        else:
            self._selected_tag_id = tag_id
            self.tag_selected.emit(tag_id)
        for sec in self._sections:
            sec.update_selection(self._selected_tag_id)
        self._all_btn.setChecked(self._selected_tag_id == -1)

    def _on_add_category(self) -> None:
        if self._library is None:
            return
        name, ok = QInputDialog.getText(self, "New Category", "Category name:")
        if not ok or not name.strip():
            return
        create_tag(self._library.db_path, self._library.id, name.strip(), tag_type="category")
        self.refresh()
        self.tags_changed.emit()

    def _on_add_tag(self, category_id: int, tag_type: str) -> None:
        if self._library is None:
            return
        prompt = "Meta tag name:" if tag_type == "meta" else "Tag name:"
        name, ok = QInputDialog.getText(self, "New Tag", prompt)
        if not ok or not name.strip():
            return
        parent_id = category_id if category_id != -1 else None
        create_tag(
            self._library.db_path, self._library.id,
            name.strip(), parent_id=parent_id, tag_type=tag_type,
        )
        self.refresh()
        self.tags_changed.emit()

    def _on_delete_tag(self, tag_id: int) -> None:
        if self._library is None:
            return
        reply = QMessageBox.question(
            self, "Delete tag",
            "Delete this tag and all its descendants?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if self._selected_tag_id == tag_id:
            self._selected_tag_id = -1
            self.tag_selected.emit(-1)
        delete_tag(self._library.db_path, tag_id)
        self.refresh()
        self.tags_changed.emit()
