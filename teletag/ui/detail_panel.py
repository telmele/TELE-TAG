"""
Right panel — file detail view (display only).

Shows metadata and assigned tags for the selected file(s).
Tag assignment is done via the grid context menu or the Convert panel.
"""

from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFrame,
    QHBoxLayout, QGridLayout, QSlider, QPushButton,
)
from PyQt6.QtCore import Qt, QUrl, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget

from teletag.db.connection import get_connection
from teletag.core.library import Library
from teletag.core.tags import get_tags_for_library, get_tags_for_file
from teletag.ui.widgets.tag_pill import TagPill
from teletag.ui.grid_panel import reveal_in_explorer


class _PathLabel(QLabel):
    """A read-only label that underlines on hover and opens Explorer on click."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._path: str = ""
        self.setWordWrap(True)
        self.setStyleSheet("font-size: 11px;")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_path(self, abs_path: str, display: str = "") -> None:
        self._path = abs_path
        self.setText(display or abs_path or "—")
        self.setStyleSheet("font-size: 11px;")

    def enterEvent(self, event) -> None:  # type: ignore[override]
        if self._path:
            self.setStyleSheet("font-size: 11px; text-decoration: underline;")
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self.setStyleSheet("font-size: 11px;")
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton and self._path:
            reveal_in_explorer(self._path)
        super().mousePressEvent(event)


class _MiniPlayer(QWidget):
    """Compact inline video player for the detail panel."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        self._video = QVideoWidget()
        self._video.setFixedHeight(120)
        self._video.setStyleSheet("background: #0d0d14;")
        layout.addWidget(self._video)

        controls = QHBoxLayout()
        controls.setSpacing(4)
        controls.setContentsMargins(0, 0, 0, 0)

        self._play_btn = QPushButton("▶")
        self._play_btn.setFixedSize(24, 24)
        self._play_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #c0c0d0; border: none; font-size: 12px; }"
            "QPushButton:hover { color: #ffffff; }"
        )
        self._play_btn.clicked.connect(self._toggle_play)
        controls.addWidget(self._play_btn)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, 1000)
        self._slider.setStyleSheet(
            "QSlider::groove:horizontal { height: 3px; background: #2a2938; border-radius: 1px; }"
            "QSlider::sub-page:horizontal { background: #6a8fd8; border-radius: 1px; }"
            "QSlider::handle:horizontal { width: 10px; height: 10px; margin: -3px 0;"
            " background: #c0c0d0; border-radius: 5px; }"
        )
        self._slider.sliderMoved.connect(self._on_seek)
        controls.addWidget(self._slider, 1)

        layout.addLayout(controls)

        self._player = QMediaPlayer()
        self._audio = QAudioOutput()
        self._audio.setVolume(0.5)
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._video)
        self._player.playbackStateChanged.connect(self._on_state_changed)
        self._player.positionChanged.connect(self._on_position_changed)

    def load(self, abs_path: str) -> None:
        self._player.stop()
        self._player.setSource(QUrl.fromLocalFile(abs_path))
        self._play_btn.setText("▶")

    def stop(self) -> None:
        self._player.stop()
        self._player.setSource(QUrl())

    def _toggle_play(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def _on_state_changed(self, state) -> None:
        self._play_btn.setText(
            "⏸" if state == QMediaPlayer.PlaybackState.PlayingState else "▶"
        )

    def _on_position_changed(self, pos_ms: int) -> None:
        dur = self._player.duration()
        if dur > 0:
            self._slider.blockSignals(True)
            self._slider.setValue(int(pos_ms * 1000 / dur))
            self._slider.blockSignals(False)

    def _on_seek(self, value: int) -> None:
        dur = self._player.duration()
        if dur > 0:
            self._player.setPosition(int(value * dur / 1000))


class DetailPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._library: Library | None = None
        self._file_id: int | None = None
        self._multi_ids: list[int] = []
        self._setup_ui()
        self.setMinimumWidth(220)
        self.setMaximumWidth(320)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # ── Single-file panel ──────────────────────────────────────────
        self._single_widget = QWidget()
        single_layout = QVBoxLayout(self._single_widget)
        single_layout.setContentsMargins(0, 0, 0, 0)
        single_layout.setSpacing(8)

        self._mini_player = _MiniPlayer()
        single_layout.addWidget(self._mini_player)

        title = QLabel("File Details")
        font = QFont()
        font.setBold(True)
        font.setPointSize(11)
        title.setFont(font)
        single_layout.addWidget(title)

        self._meta_frame = QFrame()
        self._meta_frame.setFrameShape(QFrame.Shape.StyledPanel)
        meta_layout = QGridLayout(self._meta_frame)
        meta_layout.setSpacing(4)

        self._meta_labels: dict[str, QLabel] = {}
        self._path_label = _PathLabel()
        for row, key in enumerate(["Name", "Duration", "Resolution", "Codec", "Path"]):
            lbl_key = QLabel(key + ":")
            lbl_key.setStyleSheet("color: #6d6d7a; font-size: 11px;")
            if key == "Path":
                lbl_val = self._path_label
            else:
                lbl_val = QLabel("—")
                lbl_val.setWordWrap(True)
                lbl_val.setStyleSheet("font-size: 11px;")
            meta_layout.addWidget(lbl_key, row, 0, Qt.AlignmentFlag.AlignTop)
            meta_layout.addWidget(lbl_val, row, 1, Qt.AlignmentFlag.AlignTop)
            self._meta_labels[key] = lbl_val

        single_layout.addWidget(self._meta_frame)

        tags_title = QLabel("Tags")
        tags_title.setStyleSheet("font-weight: bold;")
        single_layout.addWidget(tags_title)

        self._tags_container = QWidget()
        self._tags_layout = QHBoxLayout(self._tags_container)
        self._tags_layout.setContentsMargins(0, 0, 0, 0)
        self._tags_layout.setSpacing(4)
        self._tags_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        single_layout.addWidget(self._tags_container)

        single_layout.addStretch()

        # ── Multi-file batch panel ─────────────────────────────────────
        self._batch_widget = QWidget()
        batch_layout = QVBoxLayout(self._batch_widget)
        batch_layout.setContentsMargins(0, 0, 0, 0)
        batch_layout.setSpacing(8)

        batch_title_font = QFont()
        batch_title_font.setBold(True)
        batch_title_font.setPointSize(11)

        self._batch_title = QLabel("0 files selected")
        self._batch_title.setFont(batch_title_font)
        batch_layout.addWidget(self._batch_title)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #444;")
        batch_layout.addWidget(sep)

        common_lbl = QLabel("Common tags:")
        common_lbl.setStyleSheet("font-weight: bold;")
        batch_layout.addWidget(common_lbl)

        self._batch_tags_container = QWidget()
        self._batch_tags_layout = QHBoxLayout(self._batch_tags_container)
        self._batch_tags_layout.setContentsMargins(0, 0, 0, 0)
        self._batch_tags_layout.setSpacing(4)
        self._batch_tags_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        batch_layout.addWidget(self._batch_tags_container)

        batch_layout.addStretch()

        # ── Stack both into main layout ────────────────────────────────
        layout.addWidget(self._single_widget)
        layout.addWidget(self._batch_widget)
        self._batch_widget.hide()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def set_library(self, library: Library) -> None:
        self._library = library
        self._file_id = None
        self._multi_ids = []
        self._clear_meta()

    def show_selection(self, file_ids: list[int]) -> None:
        if len(file_ids) == 1:
            self._single_widget.show()
            self._batch_widget.hide()
            self._multi_ids = []
            self.show_file(file_ids[0])
        elif len(file_ids) > 1:
            self._multi_ids = list(file_ids)
            self._single_widget.hide()
            self._batch_widget.show()
            self._refresh_batch()
        else:
            self._multi_ids = []
            self._single_widget.show()
            self._batch_widget.hide()
            self._file_id = None
            self._clear_meta()

    def show_file(self, file_id: int) -> None:
        if self._library is None:
            return
        self._file_id = file_id
        conn = get_connection(self._library.db_path)
        row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
        if row is None:
            return
        d = dict(row)
        self._meta_labels["Name"].setText(Path(d["relative_path"]).name)
        self._meta_labels["Duration"].setText(f"{d['duration']:.1f}s" if d.get("duration") else "—")
        self._meta_labels["Resolution"].setText(d.get("resolution") or "—")
        self._meta_labels["Codec"].setText(d.get("codec") or "—")
        rel = d.get("relative_path", "")
        abs_path = str(self._library.root_path / rel) if self._library else rel
        self._path_label.set_path(abs_path, display=rel)
        self._mini_player.load(abs_path)
        self._refresh_tags()

    def refresh_tags_for(self, file_ids: list[int]) -> None:
        """Called by MainWindow when tags change for specific files."""
        if self._file_id in file_ids:
            self._refresh_tags()
        if any(fid in file_ids for fid in self._multi_ids):
            self._refresh_batch()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _clear_meta(self) -> None:
        self._mini_player.stop()
        for key, lbl in self._meta_labels.items():
            if key == "Path":
                self._path_label.set_path("")
            else:
                lbl.setText("—")
        while self._tags_layout.count():
            item = self._tags_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

    def _refresh_tags(self) -> None:
        while self._tags_layout.count():
            item = self._tags_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        if self._file_id is None or self._library is None:
            return
        for tag in get_tags_for_file(self._library.db_path, self._file_id):
            self._tags_layout.addWidget(TagPill(tag.name))

    def _refresh_batch(self) -> None:
        if self._library is None:
            return
        self._batch_title.setText(f"{len(self._multi_ids)} files selected")

        tag_sets = [
            {t.id for t in get_tags_for_file(self._library.db_path, fid)}
            for fid in self._multi_ids
        ]
        common_ids = set.intersection(*tag_sets) if tag_sets else set()

        while self._batch_tags_layout.count():
            item = self._batch_tags_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        all_tags = {t.id: t for t in get_tags_for_library(self._library.db_path, self._library.id)}
        for tid in sorted(common_ids):
            if tid in all_tags:
                self._batch_tags_layout.addWidget(TagPill(all_tags[tid].name))
