"""
TELE-TAG — entry point.

Run with:
    python main.py
"""

import sys

from PyQt6.QtWidgets import QApplication

from teletag.ui.main_window import MainWindow
from teletag.ui.theme import apply_theme


def main() -> None:
    # High-DPI scaling is on by default in Qt6; no extra flags needed.
    app = QApplication(sys.argv)
    app.setApplicationName("TELE-TAG")
    app.setOrganizationName("TELE-TAG")
    app.setStyle("Fusion")
    from PyQt6.QtCore import QSettings
    saved_theme = QSettings().value("appearance/theme", "Aura")
    apply_theme(app, saved_theme)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
