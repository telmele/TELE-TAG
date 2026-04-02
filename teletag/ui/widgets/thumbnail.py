"""
Lazy-loading thumbnail widget.

The pixmap is loaded from disk only when the widget becomes visible
(via a QTimer single-shot deferred load triggered after show()).
"""

from pathlib import Path

from PyQt6.QtWidgets import QLabel, QWidget
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap

_THUMB_W = 200
_THUMB_H = 112   # 16:9


class ThumbnailWidget(QLabel):
    """
    Displays a video thumbnail.  Pass `thumb_path=None` to show a placeholder.
    """

    def __init__(self, thumb_path: str | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._thumb_path = thumb_path
        self._loaded = False

        self.setFixedSize(_THUMB_W, _THUMB_H)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background-color: #1a1a2e; border-radius: 4px;")
        self.setText("⏳")  # placeholder until image loads

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        if not self._loaded:
            QTimer.singleShot(0, self._load)

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self._thumb_path:
            self.setText("🎬")
            return
        p = Path(self._thumb_path)
        if not p.exists():
            self.setText("🎬")
            return
        pix = QPixmap(str(p))
        if pix.isNull():
            self.setText("🎬")
            return
        self.setPixmap(
            pix.scaled(
                _THUMB_W, _THUMB_H,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.setText("")
