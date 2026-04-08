"""
Keyboard shortcuts reference dialog.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QDialogButtonBox, QHeaderView,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


_SHORTCUTS: list[tuple[str, str, str]] = [
    # (category, key, description)
    ("Library",    "Ctrl+L",       "Add a new library"),
    ("Library",    "Ctrl+R",       "Rescan current library"),
    ("Library",    "Ctrl+,",       "Open Preferences"),
    ("Navigation", "Ctrl+F",       "Focus search bar"),
    ("Selection",  "Click",              "Select a file and show its details"),
    ("Selection",  "Ctrl+Click",         "Toggle file in / out of multi-selection"),
    ("Selection",  "Shift+Click",        "Select range from last click to here"),
    ("Selection",  "Ctrl+Shift+Click",   "Add range to existing selection"),
    ("Tags",       "Click pill",        "Remove a tag from the selected file"),
    ("Preview",    "Hover card",        "Show floating video preview (400 ms delay)"),
    ("Preview",    "Space",             "Open selected file in fullscreen player"),
    ("Player",     "Space / Esc / F",   "Close fullscreen player"),
    ("Player",     "P",                 "Pause / resume"),
    ("Player",     "← / →",             "Seek −10 s / +10 s"),
]


class ShortcutsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.setMinimumSize(520, 320)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        table = QTableWidget(len(_SHORTCUTS), 3)
        table.setHorizontalHeaderLabels(["Category", "Shortcut", "Description"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)

        bold = QFont()
        bold.setBold(True)

        for row, (category, key, desc) in enumerate(_SHORTCUTS):
            key_item = QTableWidgetItem(key)
            key_item.setFont(bold)
            for col, item in enumerate([
                QTableWidgetItem(category),
                key_item,
                QTableWidgetItem(desc),
            ]):
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                table.setItem(row, col, item)

        layout.addWidget(table)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
