"""
Lazy-loading thumbnail widget.

The pixmap is loaded from disk only when the widget becomes visible
(via a QTimer single-shot deferred load triggered after show()).
Fills whatever width the parent layout assigns; height is fixed at 16:9.
"""

from pathlib import Path

from PyQt6.QtWidgets import QLabel, QWidget, QSizePolicy
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap

_THUMB_H = 120   # fixed height; width comes from the layout


class ThumbnailWidget(QLabel):
    """
    Displays a video thumbnail.  Pass `thumb_path=None` to show a placeholder.
    Expands horizontally to fill its parent; height is fixed.
    """

    def __init__(self, thumb_path: str | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._thumb_path = thumb_path
        self._loaded = False

        self.setFixedHeight(_THUMB_H)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background-color: #15141b; border-radius: 0;")
        self.setText("⏳")

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
        w = self.width() or 200
        self.setPixmap(
            pix.scaled(
                w, _THUMB_H,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.setText("")
