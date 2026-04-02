"""
Main application window.

Layout:
  ┌──────────────────────────────────────────────────────────┐
  │  [Library ▾]   [Search bar]              [Inbox badge]  │
  ├────────┬───────────────────────────┬──────────┬──────────┤
  │  Tag   │       Video Grid          │  Detail  │  Inbox   │
  │  Tree  │                           │  Panel   │  Panel   │
  └────────┴───────────────────────────┴──────────┴──────────┘

The Inbox panel is shown/hidden via the toolbar badge button.
"""

import logging
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow,
    QToolBar, QComboBox, QLineEdit, QPushButton,
    QFileDialog, QSplitter, QMessageBox,
    QInputDialog, QProgressDialog,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject

from teletag.core.library import Library, add_library
from teletag.core.ingest import scan_library
from teletag.core.watcher import FileWatcher, WatcherSignals
from teletag.ui.tag_panel import TagPanel
from teletag.ui.grid_panel import GridPanel
from teletag.ui.detail_panel import DetailPanel
from teletag.ui.inbox_panel import InboxPanel
from teletag.ui.encode_dialog import EncodeDialog

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Background scan worker
# ---------------------------------------------------------------------------

class _ScanSignals(QObject):
    progress = pyqtSignal(int, int, str)   # (current, total, filename)
    finished = pyqtSignal()


class _ScanWorker(QThread):
    def __init__(self, library: Library) -> None:
        super().__init__()
        self._library = library
        self.signals = _ScanSignals()

    def run(self) -> None:
        scan_library(self._library, progress_cb=self.signals.progress.emit)
        self.signals.finished.emit()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TELE-TAG")
        self.resize(1280, 800)

        self._libraries: list[Library] = []
        self._current_library: Library | None = None
        self._scan_worker: _ScanWorker | None = None

        self._watcher_signals = WatcherSignals()
        self._watcher = FileWatcher(self._watcher_signals)
        self._watcher_signals.file_added.connect(self._on_file_added)
        self._watcher_signals.file_deleted.connect(self._on_file_deleted)
        self._watcher_signals.inbox_file_added.connect(self._on_inbox_file_added)

        self._setup_ui()
        self._watcher.start()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        self._build_toolbar()

        # Panels
        self._tag_panel = TagPanel()
        self._tag_panel.tag_selected.connect(self._on_tag_selected)
        self._tag_panel.tags_changed.connect(self._refresh_grid)

        self._grid_panel = GridPanel()
        self._grid_panel.file_selected.connect(self._on_file_selected)

        self._detail_panel = DetailPanel()
        self._detail_panel.encode_requested.connect(self._on_encode_requested)
        self._detail_panel.tags_changed.connect(self._refresh_grid)

        self._inbox_panel = InboxPanel()
        self._inbox_panel.file_promoted.connect(self._on_file_promoted)
        self._inbox_panel.hide()

        # Splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._tag_panel)
        splitter.addWidget(self._grid_panel)
        splitter.addWidget(self._detail_panel)
        splitter.addWidget(self._inbox_panel)
        splitter.setStretchFactor(1, 1)   # grid gets all extra space
        splitter.setSizes([200, 800, 260, 280])

        self.setCentralWidget(splitter)

        # Status bar
        self.statusBar().showMessage("Ready — add a library to get started.")

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        # Library switcher
        self._lib_combo = QComboBox()
        self._lib_combo.setMinimumWidth(180)
        self._lib_combo.setToolTip("Switch active library")
        self._lib_combo.currentIndexChanged.connect(self._on_library_switched)
        tb.addWidget(self._lib_combo)

        # Add library button
        btn_add_lib = QPushButton("+ Library")
        btn_add_lib.setToolTip("Add a new library folder")
        btn_add_lib.clicked.connect(self._on_add_library)
        tb.addWidget(btn_add_lib)

        tb.addSeparator()

        # Search bar
        self._search_bar = QLineEdit()
        self._search_bar.setPlaceholderText("Search files…")
        self._search_bar.setMinimumWidth(240)
        self._search_bar.textChanged.connect(self._on_search_changed)
        tb.addWidget(self._search_bar)

        tb.addSeparator()

        # Rescan
        btn_rescan = QPushButton("⟳ Rescan")
        btn_rescan.setToolTip("Rescan library for new/changed files")
        btn_rescan.clicked.connect(self._on_rescan)
        tb.addWidget(btn_rescan)

        # Inbox toggle
        self._inbox_btn = QPushButton("📥 Inbox")
        self._inbox_btn.setCheckable(True)
        self._inbox_btn.setToolTip("Toggle staging inbox panel")
        self._inbox_btn.toggled.connect(self._toggle_inbox)
        tb.addWidget(self._inbox_btn)

    # ------------------------------------------------------------------
    # Library management
    # ------------------------------------------------------------------

    def _on_add_library(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Select library folder", str(Path.home())
        )
        if not folder:
            return
        name, ok = QInputDialog.getText(
            self, "Library name", "Name for this library:",
            text=Path(folder).name,
        )
        if not ok or not name.strip():
            return

        try:
            library = add_library(name.strip(), Path(folder))
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))
            return

        if any(lib.id == library.id for lib in self._libraries):
            # Already in list — just switch to it.
            idx = next(i for i, lib in enumerate(self._libraries) if lib.id == library.id)
            self._lib_combo.setCurrentIndex(idx)
            return

        self._libraries.append(library)
        self._lib_combo.addItem(library.name, library.id)
        self._lib_combo.setCurrentIndex(self._lib_combo.count() - 1)

        self._watcher.watch_library(library)
        self._start_scan(library)

    def _on_library_switched(self, index: int) -> None:
        if index < 0 or index >= len(self._libraries):
            return
        library = self._libraries[index]
        self._current_library = library
        self._tag_panel.set_library(library)
        self._grid_panel.set_library(library)
        self._detail_panel.set_library(library)
        self._inbox_panel.set_library(library)
        self.statusBar().showMessage(f"Library: {library.name}  ({library.root_path})")

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def _on_rescan(self) -> None:
        if self._current_library is None:
            QMessageBox.information(self, "No library", "Please add a library first.")
            return
        self._start_scan(self._current_library)

    def _start_scan(self, library: Library) -> None:
        if self._scan_worker and self._scan_worker.isRunning():
            return

        dlg = QProgressDialog("Scanning…", None, 0, 0, self)
        dlg.setWindowTitle("Scanning library")
        dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
        dlg.show()

        worker = _ScanWorker(library)
        self._scan_worker = worker

        def on_progress(cur: int, total: int, name: str) -> None:
            dlg.setMaximum(total)
            dlg.setValue(cur)
            dlg.setLabelText(f"Scanning: {name}")

        def on_finished() -> None:
            dlg.close()
            self._refresh_all()
            self.statusBar().showMessage(f"Scan complete — {library.name}")

        worker.signals.progress.connect(on_progress)
        worker.signals.finished.connect(on_finished)
        worker.start()

    # ------------------------------------------------------------------
    # Tag / search events
    # ------------------------------------------------------------------

    def _on_tag_selected(self, tag_id: int) -> None:
        self._grid_panel.set_tag_filter(tag_id)

    def _on_search_changed(self, text: str) -> None:
        self._grid_panel.set_search(text)

    # ------------------------------------------------------------------
    # File events
    # ------------------------------------------------------------------

    def _on_file_selected(self, file_id: int) -> None:
        self._detail_panel.show_file(file_id)

    def _on_encode_requested(self, file_id: int) -> None:
        if self._current_library is None:
            return
        dlg = EncodeDialog(self._current_library, file_id, self)
        dlg.exec()

    def _on_file_added(self, library_id: int, _abs_path: str) -> None:
        if self._current_library and self._current_library.id == library_id:
            self._refresh_all()

    def _on_file_deleted(self, library_id: int, _rel_path: str) -> None:
        if self._current_library and self._current_library.id == library_id:
            self._refresh_all()

    def _on_file_promoted(self, _abs_path: str) -> None:
        self._refresh_all()

    # ------------------------------------------------------------------
    # Inbox
    # ------------------------------------------------------------------

    def _on_inbox_file_added(self, abs_path: str) -> None:
        self._inbox_panel.add_file(abs_path)
        if not self._inbox_btn.isChecked():
            self._inbox_btn.setStyleSheet("color: #e05050; font-weight: bold;")

    def _toggle_inbox(self, checked: bool) -> None:
        self._inbox_panel.setVisible(checked)
        if checked:
            self._inbox_btn.setStyleSheet("")

    # ------------------------------------------------------------------
    # Refresh helpers
    # ------------------------------------------------------------------

    def _refresh_all(self) -> None:
        self._tag_panel.refresh()
        self._refresh_grid()

    def _refresh_grid(self) -> None:
        self._grid_panel.refresh()

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._watcher.stop()
        from teletag.db.connection import close_all
        close_all()
        super().closeEvent(event)
