"""
Floating video preview popup.

Shown near a card after a short hover delay; plays the video muted and looped.
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

    def show_for(self, abs_path: str, global_pos: QPoint, size: QSize) -> None:
        """Show the preview at *global_pos* with *size*, playing *abs_path*."""
        self.setFixedSize(size)
        self.move(global_pos)
        self._player.setSource(QUrl.fromLocalFile(abs_path))
        self._player.play()
        self.show()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def hide_preview(self) -> None:
        self._player.stop()
        self._player.setSource(QUrl())
        self.hide()
