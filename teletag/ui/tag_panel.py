"""
Left panel — hierarchical tag tree with file counts.

Clicking a tag emits `tag_selected(tag_id)` so the grid can filter.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem,
    QPushButton, QHBoxLayout, QInputDialog, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QBrush

from teletag.core.tags import Tag, get_tags_for_library, build_tag_tree, create_tag, delete_tag
from teletag.core.library import Library

# Same palette as TagPill — (background, accent/text)
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


def _tag_colors(name: str) -> tuple[str, str]:
    return _PILL_COLORS[hash(name) % len(_PILL_COLORS)]


class TagPanel(QWidget):
    tag_selected = pyqtSignal(int)   # tag_id; -1 = show all
    tags_changed = pyqtSignal()      # tag tree was modified

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._library: Library | None = None
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        title = QLabel("Tags")
        font = QFont()
        font.setBold(True)
        font.setPointSize(11)
        title.setFont(font)
        layout.addWidget(title)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setAnimated(True)
        self._tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._tree)

        # Buttons row
        btn_row = QHBoxLayout()
        btn_add = QPushButton("+ Add")
        btn_add.setToolTip("Create a new tag (optionally as child of selected)")
        btn_add.clicked.connect(self._on_add_tag)

        btn_del = QPushButton("Delete")
        btn_del.setToolTip("Delete selected tag and all its descendants")
        btn_del.clicked.connect(self._on_delete_tag)

        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_del)
        layout.addLayout(btn_row)

        self.setMinimumWidth(180)
        self.setMaximumWidth(280)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_library(self, library: Library) -> None:
        self._library = library
        self.refresh()

    def refresh(self) -> None:
        if self._library is None:
            self._tree.clear()
            return
        tags = get_tags_for_library(self._library.db_path, self._library.id)
        forest = build_tag_tree(tags)
        self._tree.clear()

        # "All files" root item
        all_item = QTreeWidgetItem(["All files"])
        all_item.setData(0, Qt.ItemDataRole.UserRole, -1)
        self._tree.addTopLevelItem(all_item)

        for root_tag in forest:
            item = self._make_item(root_tag)
            self._tree.addTopLevelItem(item)

        self._tree.expandAll()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_item(self, tag: Tag) -> QTreeWidgetItem:
        label = f"{tag.name}  ({tag.file_count})" if tag.file_count else tag.name
        item = QTreeWidgetItem([f"# {label}"])
        item.setData(0, Qt.ItemDataRole.UserRole, tag.id)
        bg, fg = _tag_colors(tag.name)
        item.setForeground(0, QBrush(QColor(fg)))
        item.setBackground(0, QBrush(QColor(bg)))
        for child in tag.children:
            item.addChild(self._make_item(child))
        return item

    def _selected_tag_id(self) -> int | None:
        items = self._tree.selectedItems()
        if not items:
            return None
        return items[0].data(0, Qt.ItemDataRole.UserRole)

    def _on_item_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        tag_id = item.data(0, Qt.ItemDataRole.UserRole)
        self.tag_selected.emit(tag_id)

    def _on_add_tag(self) -> None:
        if self._library is None:
            return
        parent_id = self._selected_tag_id()
        if parent_id == -1:
            parent_id = None

        name, ok = QInputDialog.getText(self, "New tag", "Tag name:")
        if not ok or not name.strip():
            return
        create_tag(self._library.db_path, self._library.id, name.strip(), parent_id)
        self.refresh()
        self.tags_changed.emit()

    def _on_delete_tag(self) -> None:
        if self._library is None:
            return
        tag_id = self._selected_tag_id()
        if tag_id is None or tag_id == -1:
            return
        reply = QMessageBox.question(
            self, "Delete tag",
            "Delete this tag and all its descendants?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            delete_tag(self._library.db_path, tag_id)
            self.refresh()
            self.tags_changed.emit()
