"""
Theme system.

Usage:
    from teletag.ui.theme import apply_theme, card_style, THEMES
    apply_theme(app, "Aura")          # at startup
    apply_theme(app, name)            # on theme change
    VideoCard.setStyleSheet(card_style(selected=True))
"""

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont

# ---------------------------------------------------------------------------
# Palette definitions
# ---------------------------------------------------------------------------

THEMES: dict[str, dict] = {
    "Aura": {
        "BG0":        "#15141b",
        "BG1":        "#1b1a23",
        "BG2":        "#21202e",
        "BG2H":       "#252433",   # card hover
        "BG3":        "#292736",
        "BORDER":     "#3d3b54",
        "ACCENT":     "#a277ff",
        "TEAL":       "#61ffca",
        "ORANGE":     "#ffca85",
        "PINK":       "#f694ff",
        "DANGER":     "#ff6767",
        "TEXT":       "#edecee",
        "TEXT2":      "#a9a9b3",
        "MUTED":      "#6d6d7a",
        "SEL_FG":     "#15141b",
    },
    "VS Dark": {
        "BG0":        "#1e1e1e",
        "BG1":        "#252526",
        "BG2":        "#2d2d2d",
        "BG2H":       "#333333",
        "BG3":        "#3e3e42",
        "BORDER":     "#555569",
        "ACCENT":     "#569cd6",
        "TEAL":       "#4ec9b0",
        "ORANGE":     "#ce9178",
        "PINK":       "#c586c0",
        "DANGER":     "#f44747",
        "TEXT":       "#d4d4d4",
        "TEXT2":      "#9d9d9d",
        "MUTED":      "#6d6d6d",
        "SEL_FG":     "#ffffff",
    },
    "Dracula": {
        "BG0":        "#282a36",
        "BG1":        "#21222c",
        "BG2":        "#343746",
        "BG2H":       "#3c3f58",
        "BG3":        "#44475a",
        "BORDER":     "#6272a4",
        "ACCENT":     "#bd93f9",
        "TEAL":       "#50fa7b",
        "ORANGE":     "#ffb86c",
        "PINK":       "#ff79c6",
        "DANGER":     "#ff5555",
        "TEXT":       "#f8f8f2",
        "TEXT2":      "#bfbfbf",
        "MUTED":      "#6272a4",
        "SEL_FG":     "#282a36",
    },
    "Light": {
        "BG0":        "#ffffff",
        "BG1":        "#f3f3f3",
        "BG2":        "#e8e8e8",
        "BG2H":       "#dcdcdc",
        "BG3":        "#d0d0d0",
        "BORDER":     "#b0b0b0",
        "ACCENT":     "#6528d7",
        "TEAL":       "#006060",
        "ORANGE":     "#a05000",
        "PINK":       "#900070",
        "DANGER":     "#cc2200",
        "TEXT":       "#1e1e1e",
        "TEXT2":      "#555555",
        "MUTED":      "#8c8c8c",
        "SEL_FG":     "#ffffff",
    },
}

# ---------------------------------------------------------------------------
# QSS template  (use $VAR — plain {/} are raw CSS, no escaping needed)
# ---------------------------------------------------------------------------

_QSS_TEMPLATE = """
QWidget {
    background-color: $BG0;
    color: $TEXT;
    font-family: "Segoe UI", system-ui, sans-serif;
    font-size: 13px;
    border: none;
    selection-background-color: $ACCENT;
    selection-color: $SEL_FG;
}
QMainWindow, QDialog { background-color: $BG0; }

/* Menu bar */
QMenuBar {
    background-color: $BG1;
    color: $TEXT;
    border-bottom: 1px solid $BG3;
    padding: 2px 0;
}
QMenuBar::item { padding: 5px 14px; background: transparent; border-radius: 0; }
QMenuBar::item:selected { background: $BG3; }
QMenuBar::item:pressed  { background: $ACCENT; color: $SEL_FG; }

/* Menu */
QMenu {
    background: $BG1;
    border: 1px solid $BG3;
    border-radius: 0;
    padding: 4px 0;
}
QMenu::item { padding: 7px 28px 7px 14px; border-radius: 0; margin: 1px 4px; }
QMenu::item:selected  { background: $BG3; color: $ACCENT; }
QMenu::item:disabled  { color: $MUTED; }
QMenu::separator { height: 1px; background: $BG3; margin: 4px 10px; }

/* Toolbar */
QToolBar {
    background: $BG1;
    border-bottom: 1px solid $BG3;
    padding: 4px 8px;
    spacing: 4px;
}
QToolBar::separator { width: 1px; background: $BG3; margin: 4px 6px; }

/* Buttons */
QPushButton {
    background: $BG2;
    color: $TEXT;
    border: 1px solid $BG3;
    border-radius: 0;
    padding: 5px 14px;
    font-weight: 500;
}
QPushButton:hover    { background: $BG3;    border-color: $ACCENT; }
QPushButton:pressed  { background: $ACCENT; color: $SEL_FG; border-color: $ACCENT; }
QPushButton:checked  { background: $ACCENT; color: $SEL_FG; border-color: $ACCENT; }
QPushButton:disabled { background: $BG1;    color: $MUTED; border-color: $BG3; }

/* ComboBox */
QComboBox {
    background: $BG2;
    color: $TEXT;
    border: 1px solid $BG3;
    border-radius: 0;
    padding: 5px 10px;
}
QComboBox:hover  { border-color: $ACCENT; }
QComboBox:focus  { border-color: $ACCENT; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow {
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid $TEXT2;
    margin-right: 6px;
}
QComboBox QAbstractItemView {
    background: $BG1;
    border: 1px solid $BORDER;
    border-radius: 0;
    selection-background-color: $BG3;
    selection-color: $ACCENT;
    outline: none;
}

/* LineEdit */
QLineEdit {
    background: $BG2;
    color: $TEXT;
    border: 1px solid $BG3;
    border-radius: 0;
    padding: 5px 10px;
}
QLineEdit:focus { border-color: $ACCENT; }
QLineEdit:hover { border-color: $BORDER; }

/* Tree / List */
QTreeWidget, QListWidget {
    background: $BG1;
    alternate-background-color: $BG2;
    border: 1px solid $BG3;
    border-radius: 0;
    outline: none;
}
QTreeWidget::item, QListWidget::item { padding: 5px 6px; border-radius: 0; }
QTreeWidget::item:hover, QListWidget::item:hover { background: $BG3; }
QTreeWidget::item:selected, QListWidget::item:selected { background: $BORDER; color: $ACCENT; }
QTreeWidget::branch:selected { background: $BORDER; }

/* Table */
QTableWidget {
    background: $BG1;
    alternate-background-color: $BG2;
    border: 1px solid $BG3;
    border-radius: 0;
    gridline-color: $BG3;
    outline: none;
}
QTableWidget::item { padding: 5px 8px; }
QTableWidget::item:selected { background: $BORDER; color: $ACCENT; }
QHeaderView::section {
    background: $BG2;
    color: $MUTED;
    border: none;
    border-bottom: 1px solid $BG3;
    border-right: 1px solid $BG3;
    padding: 6px 10px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
QHeaderView::section:last { border-right: none; }

/* Scrollbars */
QScrollBar:vertical   { background: transparent; width: 8px;  margin: 0; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 0; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: $BG3;
    border-radius: 0;
    min-width: 24px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover { background: $ACCENT; }
QScrollBar::add-line:vertical,   QScrollBar::sub-line:vertical   { height: 0; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:  0; }
QScrollBar::add-page:vertical,   QScrollBar::sub-page:vertical,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: none; }

/* Splitter */
QSplitter::handle           { background: $BG3; }
QSplitter::handle:horizontal { width: 1px;  }
QSplitter::handle:vertical   { height: 1px; }
QSplitter::handle:hover      { background: $ACCENT; }

/* Dock widgets */
QDockWidget {
    background: $BG1;
    border: 1px solid $BG3;
}
QDockWidget::title {
    background: $BG2;
    padding: 4px 8px;
    font-size: 11px;
    font-weight: 600;
    color: $MUTED;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    border-bottom: 1px solid $BG3;
}
QDockWidget::close-button, QDockWidget::float-button {
    background: transparent;
    border: none;
    padding: 2px;
}
QDockWidget::close-button:hover, QDockWidget::float-button:hover {
    background: $BG3;
}

/* Tab bar (tabbed docks) */
QTabBar { background: $BG1; border-bottom: 1px solid $BG3; }
QTabBar::tab {
    background: $BG2;
    color: $MUTED;
    padding: 5px 14px;
    border: none;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:selected {
    color: $ACCENT;
    background: $BG3;
    border-bottom: 2px solid $ACCENT;
}
QTabBar::tab:hover:!selected { background: $BG3; color: $TEXT; }

/* GroupBox */
QGroupBox {
    border: 1px solid $BG3;
    border-radius: 0;
    margin-top: 18px;
    padding: 10px 8px 8px 8px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: $MUTED;
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1px;
}

/* Checkbox */
QCheckBox { spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1px solid $BORDER;
    border-radius: 0;
    background: $BG2;
}
QCheckBox::indicator:hover   { border-color: $ACCENT; }
QCheckBox::indicator:checked { background: $ACCENT; border-color: $ACCENT; }

/* ProgressBar */
QProgressBar {
    background: $BG2;
    border: 1px solid $BG3;
    border-radius: 0;
    text-align: center;
    color: $TEXT;
    font-size: 11px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 $ACCENT, stop:1 $PINK);
    border-radius: 0;
}

/* Slider */
QSlider::groove:horizontal { height: 4px; background: $BG3; border-radius: 0; }
QSlider::sub-page:horizontal { background: $ACCENT; border-radius: 0; }
QSlider::handle:horizontal {
    background: $TEXT;
    width: 14px; height: 14px;
    margin: -5px 0;
    border-radius: 0;
}

/* Frame separators */
QFrame[frameShape="4"], QFrame[frameShape="5"] {
    background: $BG3; max-height: 1px; border: none;
}

/* Status bar */
QStatusBar {
    background: $BG1;
    border-top: 1px solid $BG3;
    color: $MUTED;
    font-size: 12px;
}

/* Tooltips */
QToolTip {
    background: $BG2;
    color: $TEXT;
    border: 1px solid $ACCENT;
    border-radius: 0;
    padding: 5px 10px;
    font-size: 12px;
}

/* Scroll area */
QScrollArea { border: none; background: transparent; }

/* Dialog buttons */
QDialogButtonBox QPushButton { min-width: 84px; }
"""

# ---------------------------------------------------------------------------
# Runtime state
# ---------------------------------------------------------------------------

_active_palette: dict = THEMES["Aura"]


def _make_qss(palette: dict) -> str:
    qss = _QSS_TEMPLATE
    for key, val in palette.items():
        qss = qss.replace(f"${key}", val)
    return qss


def get_palette() -> dict:
    """Return the currently active theme palette."""
    return _active_palette


def pill_colors(tag_name: str) -> tuple[str, str]:
    """Return (bg_css, fg_css) for a tag pill, derived from the active theme."""
    p = _active_palette
    fgs = [p["ACCENT"], p["TEAL"], p["ORANGE"], p["PINK"], p["DANGER"],
           "#82e2ff", "#c3e88d", "#ffe073"]
    fg = fgs[hash(tag_name) % len(fgs)]
    h = fg.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, 40)", fg


def apply_theme(app: QApplication, name: str = "Aura") -> None:
    global _active_palette
    palette = THEMES.get(name, THEMES["Aura"])
    _active_palette = palette
    font = QFont("Segoe UI", 10)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    app.setFont(font)
    app.setStyleSheet(_make_qss(palette))


def card_style(selected: bool) -> str:
    """Return the stylesheet string for a VideoCard in the current theme."""
    p = _active_palette
    if selected:
        return (
            f"VideoCard {{"
            f"  background: {p['BG2']};"
            f"  border: 2px solid {p['ACCENT']};"
            f"  border-radius: 0;"
            f"}}"
        )
    return (
        f"VideoCard {{"
        f"  background: {p['BG2']};"
        f"  border: 1px solid {p['BG3']};"
        f"  border-radius: 0;"
        f"}}"
        f"VideoCard:hover {{"
        f"  border: 1px solid {p['BORDER']};"
        f"  background: {p['BG2H']};"
        f"}}"
    )
