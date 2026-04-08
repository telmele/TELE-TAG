"""
Application settings dialog.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QCheckBox,
    QDialogButtonBox, QLabel, QComboBox, QApplication,
)
from PyQt6.QtCore import QSettings, pyqtSignal

from teletag.ui.theme import THEMES, apply_theme


class SettingsDialog(QDialog):
    theme_changed = pyqtSignal(str)   # emitted on accept if theme changed

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(440)
        self._original_theme = QSettings().value("appearance/theme", "Aura")
        self._setup_ui()

    def _setup_ui(self) -> None:
        settings = QSettings()
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ── Appearance ─────────────────────────────────────────────────
        appearance_group = QGroupBox("Appearance")
        appearance_layout = QVBoxLayout(appearance_group)

        row = QHBoxLayout()
        row.addWidget(QLabel("Theme:"))
        self._theme_combo = QComboBox()
        for name in THEMES:
            self._theme_combo.addItem(name)
        current = settings.value("appearance/theme", "Aura")
        idx = self._theme_combo.findText(current)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)
        self._theme_combo.currentTextChanged.connect(self._preview_theme)
        row.addWidget(self._theme_combo)
        row.addStretch()
        appearance_layout.addLayout(row)
        layout.addWidget(appearance_group)

        # ── Startup ────────────────────────────────────────────────────
        startup_group = QGroupBox("Startup")
        startup_layout = QVBoxLayout(startup_group)
        self._rescan_check = QCheckBox("Auto-rescan all libraries on startup")
        self._rescan_check.setChecked(
            settings.value("startup/auto_rescan", False, type=bool)
        )
        startup_layout.addWidget(self._rescan_check)
        layout.addWidget(startup_group)

        layout.addStretch()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self._cancel)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------

    def _preview_theme(self, name: str) -> None:
        apply_theme(QApplication.instance(), name)

    def _save(self) -> None:
        name = self._theme_combo.currentText()
        settings = QSettings()
        settings.setValue("appearance/theme", name)
        settings.setValue("startup/auto_rescan", self._rescan_check.isChecked())
        if name != self._original_theme:
            self.theme_changed.emit(name)
        self.accept()

    def _cancel(self) -> None:
        # Revert to the theme that was active when the dialog opened.
        if self._theme_combo.currentText() != self._original_theme:
            apply_theme(QApplication.instance(), self._original_theme)
        self.reject()
