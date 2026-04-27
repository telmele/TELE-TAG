"""
Tag pill — compact inline label used in the grid and detail panel.

Design: rectangular chip with a 2 px left accent bar and matching text,
on a very dark tinted background.  No border-radius (flat theme).
"""

from PyQt6.QtWidgets import QLabel
from PyQt6.QtCore import Qt

from teletag.ui.theme import pill_colors


class TagPill(QLabel):
    """A flat rectangular chip that displays a single tag name."""

    def __init__(self, tag_name: str, parent=None) -> None:
        super().__init__(f"# {tag_name}", parent)
        bg, fg = pill_colors(tag_name)
        self.setStyleSheet(f"""
            QLabel {{
                background-color: {bg};
                color: {fg};
                border-left: 2px solid {fg};
                border-radius: 0;
                padding: 1px 6px 1px 5px;
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 0.3px;
            }}
        """)
        self.setFixedHeight(18)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setToolTip(tag_name)
