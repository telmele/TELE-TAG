"""
Staging area / Watch-folder inbox panel.

Files arriving in watch folders land here with a "needs tagging" indicator.
The user can tag them directly and then move/copy them into the main library.
"""

import shutil
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QHBoxLayout, QPushButton, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor

from teletag.core.library import Library
from teletag.core.ingest import ingest_single


class InboxItem(QListWidgetItem):
    def __init__(self, abs_path: str) -> None:
        super().__init__()
        self.abs_path = abs_path
        name = Path(abs_path).name
        self.setText(f"🔴  {name}")
        self.setToolTip(abs_path)
        self.setForeground(QColor("#f0c060"))


class InboxPanel(QWidget):
    """Dedicated inbox view for watch folder staging area."""

    file_promoted = pyqtSignal(str)   # abs_path promoted to library

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._library: Library | None = None
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel("Inbox")
        font = QFont()
        font.setBold(True)
        font.setPointSize(11)
        title.setFont(font)
        header.addWidget(title)

        self._badge = QLabel("0")
        self._badge.setStyleSheet(
            "background:#e05050; color:white; border-radius:9px; "
            "min-width:18px; max-width:18px; min-height:18px; max-height:18px; "
            "font-size:11px; font-weight:bold;"
        )
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.hide()
        header.addWidget(self._badge)
        header.addStretch()
        layout.addLayout(header)

        self._hint = QLabel("Files arriving in watch folders will appear here.")
        self._hint.setStyleSheet("color: #666; font-style: italic; font-size: 11px;")
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        layout.addWidget(self._list)

        # Action buttons
        btn_row = QHBoxLayout()
        self._btn_promote = QPushButton("Move to library")
        self._btn_promote.setToolTip("Move selected file into the library root folder")
        self._btn_promote.setEnabled(False)
        self._btn_promote.clicked.connect(self._promote_selected)
        btn_row.addWidget(self._btn_promote)

        self._btn_copy = QPushButton("Copy to library")
        self._btn_copy.setToolTip("Copy selected file into the library root folder, keep original")
        self._btn_copy.setEnabled(False)
        self._btn_copy.clicked.connect(lambda: self._promote_selected(copy=True))
        btn_row.addWidget(self._btn_copy)

        layout.addLayout(btn_row)

        self._list.itemSelectionChanged.connect(self._on_selection_changed)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def set_library(self, library: Library) -> None:
        self._library = library

    def add_file(self, abs_path: str) -> None:
        """Called when watchdog detects a new file in a watch folder."""
        # Avoid duplicates.
        for i in range(self._list.count()):
            item = self._list.item(i)
            if isinstance(item, InboxItem) and item.abs_path == abs_path:
                return
        self._list.addItem(InboxItem(abs_path))
        self._update_badge()

    def clear_file(self, abs_path: str) -> None:
        for i in range(self._list.count() - 1, -1, -1):
            item = self._list.item(i)
            if isinstance(item, InboxItem) and item.abs_path == abs_path:
                self._list.takeItem(i)
        self._update_badge()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _update_badge(self) -> None:
        n = self._list.count()
        if n > 0:
            self._badge.setText(str(n))
            self._badge.show()
            self._hint.hide()
        else:
            self._badge.hide()
            self._hint.show()

    def _on_selection_changed(self) -> None:
        has_sel = bool(self._list.selectedItems())
        self._btn_promote.setEnabled(has_sel)
        self._btn_copy.setEnabled(has_sel)

    def _promote_selected(self, copy: bool = False) -> None:
        if self._library is None:
            return
        items = self._list.selectedItems()
        if not items or not isinstance(items[0], InboxItem):
            return

        src = Path(items[0].abs_path)
        dst = self._library.root_path / src.name

        if dst.exists():
            reply = QMessageBox.question(
                self, "File exists",
                f"'{src.name}' already exists in the library. Overwrite?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        try:
            if copy:
                shutil.copy2(src, dst)
            else:
                shutil.move(str(src), dst)
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))
            return

        # Ingest the promoted file.
        ingest_single(self._library, dst)

        self.clear_file(str(src))
        self.file_promoted.emit(str(dst))
