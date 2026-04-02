"""
Right panel — file detail view.

Shows: metadata table, assigned tags, tag assignment widget, re-encode button.
"""

from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFrame,
    QHBoxLayout, QPushButton, QComboBox, QGridLayout,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from teletag.db.connection import get_connection
from teletag.core.library import Library
from teletag.core.tags import get_tags_for_library, get_tags_for_file, assign_tag, remove_tag
from teletag.ui.widgets.tag_pill import TagPill


class DetailPanel(QWidget):
    encode_requested = pyqtSignal(int)  # file_id
    tags_changed = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._library: Library | None = None
        self._file_id: int | None = None
        self._setup_ui()
        self.setMinimumWidth(220)
        self.setMaximumWidth(320)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QLabel("File Details")
        font = QFont()
        font.setBold(True)
        font.setPointSize(11)
        title.setFont(font)
        layout.addWidget(title)

        self._meta_frame = QFrame()
        self._meta_frame.setFrameShape(QFrame.Shape.StyledPanel)
        meta_layout = QGridLayout(self._meta_frame)
        meta_layout.setSpacing(4)

        self._meta_labels: dict[str, QLabel] = {}
        for row, key in enumerate(["Name", "Duration", "Resolution", "Codec", "Path"]):
            lbl_key = QLabel(key + ":")
            lbl_key.setStyleSheet("color: #888; font-size: 11px;")
            lbl_val = QLabel("—")
            lbl_val.setWordWrap(True)
            lbl_val.setStyleSheet("font-size: 11px;")
            meta_layout.addWidget(lbl_key, row, 0, Qt.AlignmentFlag.AlignTop)
            meta_layout.addWidget(lbl_val, row, 1, Qt.AlignmentFlag.AlignTop)
            self._meta_labels[key] = lbl_val

        layout.addWidget(self._meta_frame)

        # Tags section
        tags_title = QLabel("Tags")
        tags_title.setStyleSheet("font-weight: bold;")
        layout.addWidget(tags_title)

        self._tags_container = QWidget()
        self._tags_layout = QHBoxLayout(self._tags_container)
        self._tags_layout.setContentsMargins(0, 0, 0, 0)
        self._tags_layout.setSpacing(4)
        self._tags_layout.addStretch()
        layout.addWidget(self._tags_container)

        # Add tag row
        add_row = QHBoxLayout()
        self._tag_combo = QComboBox()
        self._tag_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        add_row.addWidget(self._tag_combo)
        btn_add = QPushButton("Add")
        btn_add.clicked.connect(self._on_add_tag)
        add_row.addWidget(btn_add)
        layout.addLayout(add_row)

        # Re-encode button
        self._encode_btn = QPushButton("Re-encode…")
        self._encode_btn.setEnabled(False)
        self._encode_btn.clicked.connect(self._on_encode)
        layout.addWidget(self._encode_btn)

        layout.addStretch()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def set_library(self, library: Library) -> None:
        self._library = library
        self._file_id = None
        self._encode_btn.setEnabled(False)
        self._refresh_tag_combo()
        self._clear_meta()

    def show_file(self, file_id: int) -> None:
        if self._library is None:
            return
        self._file_id = file_id
        conn = get_connection(self._library.db_path)
        row = conn.execute(
            "SELECT * FROM files WHERE id = ?", (file_id,)
        ).fetchone()
        if row is None:
            return

        d = dict(row)
        name = Path(d["relative_path"]).name
        dur = f"{d['duration']:.1f}s" if d.get("duration") else "—"
        self._meta_labels["Name"].setText(name)
        self._meta_labels["Duration"].setText(dur)
        self._meta_labels["Resolution"].setText(d.get("resolution") or "—")
        self._meta_labels["Codec"].setText(d.get("codec") or "—")
        self._meta_labels["Path"].setText(d.get("relative_path") or "—")

        self._encode_btn.setEnabled(True)
        self._refresh_tags()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _clear_meta(self) -> None:
        for lbl in self._meta_labels.values():
            lbl.setText("—")

    def _refresh_tags(self) -> None:
        # Remove all pill widgets (leave stretch).
        while self._tags_layout.count() > 1:
            item = self._tags_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        if self._file_id is None or self._library is None:
            return

        tags = get_tags_for_file(self._library.db_path, self._file_id)
        for tag in tags:
            pill = TagPill(tag.name)
            pill.setCursor(Qt.CursorShape.PointingHandCursor)
            pill.setToolTip("Click to remove")
            tid = tag.id
            pill.mousePressEvent = lambda _ev, t=tid: self._remove_tag(t)  # type: ignore
            self._tags_layout.insertWidget(self._tags_layout.count() - 1, pill)

    def _refresh_tag_combo(self) -> None:
        self._tag_combo.clear()
        if self._library is None:
            return
        tags = get_tags_for_library(self._library.db_path, self._library.id)
        for tag in tags:
            self._tag_combo.addItem(tag.name, tag.id)

    def _on_add_tag(self) -> None:
        if self._file_id is None or self._library is None:
            return
        tag_id = self._tag_combo.currentData()
        if tag_id is None:
            return
        assign_tag(self._library.db_path, self._file_id, tag_id)
        self._refresh_tags()
        self.tags_changed.emit()

    def _remove_tag(self, tag_id: int) -> None:
        if self._file_id is None or self._library is None:
            return
        remove_tag(self._library.db_path, self._file_id, tag_id)
        self._refresh_tags()
        self.tags_changed.emit()

    def _on_encode(self) -> None:
        if self._file_id is not None:
            self.encode_requested.emit(self._file_id)
