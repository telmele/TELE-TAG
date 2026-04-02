"""
TELE-TAG — entry point.

Run with:
    python main.py
"""

import sys

from PyQt6.QtWidgets import QApplication

from teletag.ui.main_window import MainWindow


def main() -> None:
    # High-DPI scaling is on by default in Qt6; no extra flags needed.
    app = QApplication(sys.argv)
    app.setApplicationName("TELE-TAG")
    app.setOrganizationName("TELE-TAG")
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
