"""
Fullscreen video player with auto-hiding controls overlay.

QVideoWidget on Windows creates a native HWND that sits above all Qt child
widgets, so the controls bar is a separate top-level Tool window that is
positioned over the fullscreen surface.  Mouse-move events on the native
video surface are caught via an event filter.

Controls appear on mouse move and hide after 3 s of inactivity.

Keys:
  Space / Escape / F  — close
  P                   — pause / resume
  Left / Right        — seek ±10 s
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSlider
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtCore import Qt, QUrl, QTimer, QRectF, QEvent, QObject, QPoint
from PyQt6.QtGui import QKeyEvent, QPainter, QColor, QPainterPath

from teletag.ui.theme import get_palette

_HIDE_DELAY_MS  = 3_000
_BAR_H          = 56
_BAR_MARGIN_BTM = 24
_BAR_MARGIN_H   = 40


def _fmt_ms(ms: int) -> str:
    s = ms // 1000
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# ---------------------------------------------------------------------------
# Controls bar  (top-level window so it renders above the native video HWND)
# ---------------------------------------------------------------------------

class _ControlsBar(QWidget):
    def __init__(self, player: QMediaPlayer) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedHeight(_BAR_H)

        self._player = player
        self._duration = 0
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(12)

        self._play_btn = QPushButton("⏸")
        self._play_btn.setFixedSize(36, 36)
        self._play_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: white; border: none; font-size: 20px; }}"
            f"QPushButton:hover {{ color: {get_palette()['ACCENT']}; }}"
        )
        self._play_btn.clicked.connect(self.toggle_play)
        layout.addWidget(self._play_btn)

        self._pos_label = QLabel("0:00")
        self._pos_label.setStyleSheet("color: white; font-size: 13px;")
        self._pos_label.setFixedWidth(46)
        self._pos_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(self._pos_label)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, 10_000)
        self._slider.setStyleSheet(
            "QSlider::groove:horizontal { height: 4px; background: rgba(255,255,255,60); border-radius: 0; }"
            f"QSlider::sub-page:horizontal {{ background: {get_palette()['ACCENT']}; border-radius: 0; }}"
            "QSlider::handle:horizontal { width: 14px; height: 14px; margin: -5px 0; background: white; border-radius: 0; }"
        )
        self._slider.sliderMoved.connect(self._on_seek)
        layout.addWidget(self._slider)

        self._dur_label = QLabel("0:00")
        self._dur_label.setStyleSheet(
            "color: rgba(255,255,255,140); font-size: 13px;"
        )
        self._dur_label.setFixedWidth(46)
        layout.addWidget(self._dur_label)

    # ------------------------------------------------------------------
    # Public updates
    # ------------------------------------------------------------------

    def update_position(self, pos_ms: int) -> None:
        self._pos_label.setText(_fmt_ms(pos_ms))
        if self._duration > 0:
            self._slider.blockSignals(True)
            self._slider.setValue(int(pos_ms * 10_000 / self._duration))
            self._slider.blockSignals(False)

    def update_duration(self, dur_ms: int) -> None:
        self._duration = dur_ms
        self._dur_label.setText(_fmt_ms(dur_ms))

    def set_playing(self, playing: bool) -> None:
        self._play_btn.setText("⏸" if playing else "▶")

    def toggle_play(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_seek(self, value: int) -> None:
        if self._duration > 0:
            self._player.setPosition(int(value * self._duration / 10_000))

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 10, 10)
        painter.fillPath(path, QColor(0, 0, 0, 200))


# ---------------------------------------------------------------------------
# Fullscreen player
# ---------------------------------------------------------------------------

class FullscreenPlayer(QWidget):
    def __init__(self, abs_path: str) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.setStyleSheet("background: black;")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._video = QVideoWidget()
        self._video.setMouseTracking(True)
        # Catch mouse moves on the native video surface via event filter
        self._video.installEventFilter(self)
        layout.addWidget(self._video)

        self._player = QMediaPlayer()
        self._audio  = QAudioOutput()
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._video)
        self._player.setSource(QUrl.fromLocalFile(abs_path))

        # Controls — separate top-level window to stay above native HWND
        self._controls = _ControlsBar(self._player)
        self._controls.hide()

        self._player.positionChanged.connect(self._controls.update_position)
        self._player.durationChanged.connect(self._controls.update_duration)
        self._player.playbackStateChanged.connect(
            lambda s: self._controls.set_playing(
                s == QMediaPlayer.PlaybackState.PlayingState
            )
        )

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(_HIDE_DELAY_MS)
        self._hide_timer.timeout.connect(self._hide_controls)

    # ------------------------------------------------------------------
    # Controls visibility
    # ------------------------------------------------------------------

    def _show_controls(self) -> None:
        self._reposition_controls()
        self._controls.show()
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._hide_timer.start()

    def _hide_controls(self) -> None:
        self._controls.hide()
        self.setCursor(Qt.CursorShape.BlankCursor)

    def _reposition_controls(self) -> None:
        bar_w = max(100, self.width() - 2 * _BAR_MARGIN_H)
        origin = self.mapToGlobal(
            QPoint(_BAR_MARGIN_H, self.height() - _BAR_H - _BAR_MARGIN_BTM)
        )
        self._controls.setGeometry(origin.x(), origin.y(), bar_w, _BAR_H)

    # ------------------------------------------------------------------
    # Qt overrides
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        QTimer.singleShot(50, self._player.play)
        QTimer.singleShot(60, self._show_controls)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if hasattr(self, "_controls") and self._controls.isVisible():
            self._reposition_controls()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        self._show_controls()
        super().mouseMoveEvent(event)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        # Forward mouse moves from the native QVideoWidget to our handler
        if obj is self._video and event.type() == QEvent.Type.MouseMove:
            self._show_controls()
        return False

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        k = event.key()
        if k in (Qt.Key.Key_Escape, Qt.Key.Key_Space, Qt.Key.Key_F):
            self._close_player()
        elif k == Qt.Key.Key_P:
            self._controls.toggle_play()
        elif k == Qt.Key.Key_Left:
            self._player.setPosition(max(0, self._player.position() - 10_000))
        elif k == Qt.Key.Key_Right:
            dur = self._player.duration()
            pos = self._player.position() + 10_000
            self._player.setPosition(pos if dur <= 0 else min(pos, dur))
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._player.stop()
        self._controls.close()
        super().closeEvent(event)

    def _close_player(self) -> None:
        self._player.stop()
        self._controls.close()
        self.close()
