"""
Tag pill — compact inline label used in the grid and detail panel.

Design: rectangular chip with a 2 px left accent bar and matching text,
on a very dark tinted background.  No border-radius (flat theme).
"""

from PyQt6.QtWidgets import QLabel
from PyQt6.QtCore import Qt


# (background, left-border / text) pairs — Aura-inspired palette
_PILL_COLORS = [
    ("#2a1f42", "#a277ff"),   # purple
    ("#152e28", "#61ffca"),   # teal
    ("#2e2010", "#ffca85"),   # orange
    ("#2e1530", "#f694ff"),   # pink
    ("#2e1515", "#ff6767"),   # red
    ("#152033", "#82e2ff"),   # blue
    ("#1a2e10", "#c3e88d"),   # green
    ("#2e2a10", "#ffe073"),   # yellow
]


class TagPill(QLabel):
    """A flat rectangular chip that displays a single tag name."""

    def __init__(self, tag_name: str, parent=None) -> None:
        super().__init__(f"# {tag_name}", parent)
        bg, fg = _PILL_COLORS[hash(tag_name) % len(_PILL_COLORS)]
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
