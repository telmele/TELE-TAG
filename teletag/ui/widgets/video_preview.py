"""
Floating video preview popup — scrubber mode.

Position corresponds to mouse X on the card: left = start, right = end.
The video plays forward from wherever the scrub position lands, giving
a quick visual feel for the content at that point in time.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtCore import Qt, QUrl, QPoint, QSize, pyqtSignal
from PyQt6.QtGui import QMouseEvent


class VideoPreviewPopup(QWidget):
    """
    Frameless video preview positioned over the card's thumbnail.
    Emits `clicked` on left-click so the grid can select the card.
    """

    clicked = pyqtSignal()

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._video = QVideoWidget()
        self._video.setStyleSheet("background: black;")
        layout.addWidget(self._video)

        self._player = QMediaPlayer()
        self._audio = QAudioOutput()
        self._audio.setVolume(0.0)
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._video)
        self._player.setLoops(QMediaPlayer.Loops.Infinite)

        self._duration_ms: int = 0
        self._pending_ratio: float = 0.0

        # Once the player reports a real duration, honour any pending seek.
        self._player.durationChanged.connect(self._on_duration_changed)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def show_for(
        self,
        abs_path: str,
        global_pos: QPoint,
        size: QSize,
        duration_ms: int,
        initial_ratio: float,
    ) -> None:
        """Show the preview at *global_pos* with *size*, starting at *initial_ratio*."""
        self.setFixedSize(size)
        self.move(global_pos)
        self._duration_ms = duration_ms
        self._pending_ratio = initial_ratio
        self._player.setSource(QUrl.fromLocalFile(abs_path))
        self._player.play()
        # Attempt an immediate seek; _on_duration_changed will retry if the
        # player isn't seekable yet (media still loading).
        self._seek(initial_ratio)
        self.show()

    def seek_to_ratio(self, ratio: float) -> None:
        """Called on every mouse-move over the card; scrubs to *ratio* (0..1)."""
        self._pending_ratio = ratio
        self._seek(ratio)

    def hide_preview(self) -> None:
        self._player.stop()
        self._player.setSource(QUrl())
        self._duration_ms = 0
        self.hide()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _seek(self, ratio: float) -> None:
        dur = self._player.duration() or self._duration_ms
        if dur > 0 and self._player.isSeekable():
            self._player.setPosition(int(ratio * dur))

    def _on_duration_changed(self, dur_ms: int) -> None:
        """Fired once the media is buffered and the real duration is known."""
        if dur_ms > 0:
            self._duration_ms = dur_ms
            self._seek(self._pending_ratio)

    # ------------------------------------------------------------------
    # Qt overrides
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)
