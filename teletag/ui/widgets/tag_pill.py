"""
Tag pill — a compact inline label widget used in the grid and detail panel.
"""

from PyQt6.QtWidgets import QLabel
from PyQt6.QtCore import Qt


_PILL_COLORS = [
    "#5B7FA6", "#6A9E6A", "#A67C5B", "#8E6AAD", "#A65B5B",
    "#5BA6A0", "#A6A05B", "#5B7FA6",
]


class TagPill(QLabel):
    """A rounded-rectangle label that displays a single tag name."""

    def __init__(self, tag_name: str, parent=None) -> None:
        super().__init__(tag_name, parent)
        idx = hash(tag_name) % len(_PILL_COLORS)
        color = _PILL_COLORS[idx]
        self.setStyleSheet(
            f"""
            QLabel {{
                background-color: {color};
                color: white;
                border-radius: 8px;
                padding: 2px 8px;
                font-size: 11px;
                font-weight: 600;
            }}
            """
        )
        self.setFixedHeight(20)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
