"""
Main application window.

Panels (Tags, Details, Convert) are QDockWidgets — dockable, tabbable,
floatable. GridPanel is the central widget. WorkspaceManager handles
layout persistence and the Window menu.
"""

import logging
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QDockWidget,
    QToolBar, QComboBox, QLineEdit, QPushButton,
    QFileDialog, QMessageBox,
    QInputDialog, QProgressDialog,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QSettings
from PyQt6.QtGui import QAction, QKeySequence

from teletag.core.library import Library, add_library, rename_library
from teletag.core.ingest import scan_library
from teletag.core.watcher import FileWatcher, WatcherSignals
from teletag.ui.tag_panel import TagPanel
from teletag.ui.grid_panel import GridPanel
from teletag.ui.detail_panel import DetailPanel
from teletag.ui.convert_panel import ConvertPanel
from teletag.ui.fullscreen_player import FullscreenPlayer
from teletag.ui.workspace import WorkspaceManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Background scan worker
# ---------------------------------------------------------------------------

class _ScanSignals(QObject):
    progress = pyqtSignal(int, int, str)
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
        self._fullscreen_player: FullscreenPlayer | None = None

        self._watcher_signals = WatcherSignals()
        self._watcher = FileWatcher(self._watcher_signals)
        self._watcher_signals.file_added.connect(self._on_file_added)
        self._watcher_signals.file_deleted.connect(self._on_file_deleted)

        self._setup_ui()
        self._watcher.start()
        self._restore_libraries()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        self.setDockOptions(
            QMainWindow.DockOption.AllowTabbedDocks
            | QMainWindow.DockOption.AllowNestedDocks
            | QMainWindow.DockOption.AnimatedDocks
            | QMainWindow.DockOption.GroupedDragging
        )
        self._build_panels()
        self._build_docks()
        self._workspace = WorkspaceManager(self)
        self._workspace.register_dock("dock_tags", self._dock_tags)
        self._workspace.register_dock("dock_detail", self._dock_detail)
        self._workspace.register_dock("dock_convert", self._dock_convert)
        self._build_menubar()
        self._build_toolbar()
        restored = self._workspace.restore()
        if not restored:
            self._workspace.apply_preset("Default")
        self.statusBar().showMessage("Ready — add a library to get started.")

    def _build_panels(self) -> None:
        self._tag_panel = TagPanel()
        self._tag_panel.tag_selected.connect(self._on_tag_selected)
        self._tag_panel.tags_changed.connect(self._refresh_grid)
        self._tag_panel.tags_changed.connect(lambda: self._grid_panel.refresh_filters())

        self._grid_panel = GridPanel()
        self._grid_panel.file_selected.connect(self._on_file_selected)
        self._grid_panel.selection_changed.connect(self._on_selection_changed)
        self._grid_panel.fullscreen_requested.connect(self._on_fullscreen_requested)
        self._grid_panel.tags_changed.connect(self._tag_panel.refresh)
        self._grid_panel.add_to_convert_queue.connect(self._on_add_to_convert_queue)

        self._detail_panel = DetailPanel()
        self._grid_panel.tags_changed.connect(
            lambda: self._detail_panel.refresh_tags_for(
                [self._detail_panel._file_id] if self._detail_panel._file_id else []
            )
        )

        self._convert_panel = ConvertPanel()

        self.setCentralWidget(self._grid_panel)

    def _build_docks(self) -> None:
        features = (
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )

        self._dock_tags = QDockWidget("Tags", self)
        self._dock_tags.setObjectName("dock_tags")
        self._dock_tags.setWidget(self._tag_panel)
        self._dock_tags.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._dock_tags.setFeatures(features)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._dock_tags)

        self._dock_detail = QDockWidget("Details", self)
        self._dock_detail.setObjectName("dock_detail")
        self._dock_detail.setWidget(self._detail_panel)
        self._dock_detail.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._dock_detail.setFeatures(features)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._dock_detail)

        self._dock_convert = QDockWidget("Convert", self)
        self._dock_convert.setObjectName("dock_convert")
        self._dock_convert.setWidget(self._convert_panel)
        self._dock_convert.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._dock_convert.setFeatures(features)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._dock_convert)
        self._dock_convert.hide()

    def _build_menubar(self) -> None:
        mb = self.menuBar()

        lib_menu = mb.addMenu("Library")

        act_add = QAction("Add Library…", self)
        act_add.setShortcut(QKeySequence("Ctrl+L"))
        act_add.triggered.connect(self._on_add_library)
        lib_menu.addAction(act_add)

        lib_menu.addSeparator()

        self._act_rename = QAction("Rename…", self)
        self._act_rename.triggered.connect(self._on_rename_library)
        self._act_rename.setEnabled(False)
        lib_menu.addAction(self._act_rename)

        self._act_rescan_menu = QAction("Rescan", self)
        self._act_rescan_menu.setShortcut(QKeySequence("Ctrl+R"))
        self._act_rescan_menu.triggered.connect(self._on_rescan)
        self._act_rescan_menu.setEnabled(False)
        lib_menu.addAction(self._act_rescan_menu)

        lib_menu.addSeparator()

        self._libs_submenu = lib_menu.addMenu("Open Library")
        self._libs_submenu.aboutToShow.connect(self._populate_libs_submenu)

        lib_menu.addSeparator()

        self._act_remove = QAction("Remove Library", self)
        self._act_remove.triggered.connect(self._on_remove_library)
        self._act_remove.setEnabled(False)
        lib_menu.addAction(self._act_remove)

        # Window menu inserted between Library and Settings
        self._workspace.build_window_menu(mb)

        settings_menu = mb.addMenu("Settings")

        act_prefs = QAction("Preferences…", self)
        act_prefs.setShortcut(QKeySequence("Ctrl+,"))
        act_prefs.triggered.connect(self._on_open_settings)
        settings_menu.addAction(act_prefs)

        settings_menu.addSeparator()

        act_shortcuts = QAction("Keyboard Shortcuts", self)
        act_shortcuts.triggered.connect(self._on_open_shortcuts)
        settings_menu.addAction(act_shortcuts)

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        self._lib_combo = QComboBox()
        self._lib_combo.setMinimumWidth(180)
        self._lib_combo.setToolTip("Switch active library")
        self._lib_combo.currentIndexChanged.connect(self._on_library_switched)
        tb.addWidget(self._lib_combo)

        btn_add_lib = QPushButton("+ Library")
        btn_add_lib.setToolTip("Add a new library folder")
        btn_add_lib.clicked.connect(self._on_add_library)
        tb.addWidget(btn_add_lib)

        tb.addSeparator()

        self._search_bar = QLineEdit()
        self._search_bar.setPlaceholderText("Search files…  (Ctrl+F)")
        self._search_bar.setMinimumWidth(240)
        self._search_bar.textChanged.connect(self._on_search_changed)
        tb.addWidget(self._search_bar)

        focus_search = QAction(self)
        focus_search.setShortcut(QKeySequence("Ctrl+F"))
        focus_search.triggered.connect(self._search_bar.setFocus)
        self.addAction(focus_search)

        tb.addSeparator()

        btn_rescan = QPushButton("⟳ Rescan")
        btn_rescan.setToolTip("Rescan library for new/changed files")
        btn_rescan.clicked.connect(self._on_rescan)
        tb.addWidget(btn_rescan)

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

        if any(lib.root_path == library.root_path for lib in self._libraries):
            idx = next(i for i, lib in enumerate(self._libraries) if lib.root_path == library.root_path)
            self._lib_combo.setCurrentIndex(idx)
            return

        self._libraries.append(library)
        self._lib_combo.addItem(library.name, library.id)
        self._lib_combo.setCurrentIndex(self._lib_combo.count() - 1)
        self._watcher.watch_library(library)
        self._save_library_paths()
        self._start_scan(library)

    def _save_library_paths(self) -> None:
        settings = QSettings()
        entries = [f"{lib.name}|{lib.root_path}" for lib in self._libraries]
        settings.setValue("libraries", entries)

    def _restore_libraries(self) -> None:
        settings = QSettings()
        raw = settings.value("libraries", [])
        if isinstance(raw, str):
            raw = [raw]
        for entry in raw:
            try:
                name, path_str = entry.split("|", 1)
                root_path = Path(path_str)
                if not root_path.exists():
                    logger.warning("Skipping missing library path: %s", root_path)
                    continue
                library = add_library(name, root_path)
                if any(lib.root_path == library.root_path for lib in self._libraries):
                    continue
                self._libraries.append(library)
                self._lib_combo.addItem(library.name, library.id)
                self._watcher.watch_library(library)
            except Exception as exc:
                logger.warning("Failed to restore library '%s': %s", entry, exc)

        if self._current_library and QSettings().value("startup/auto_rescan", False, type=bool):
            self._start_scan(self._current_library)

    def _on_library_switched(self, index: int) -> None:
        if index < 0 or index >= len(self._libraries):
            self._current_library = None
            self._update_library_actions()
            return
        library = self._libraries[index]
        self._current_library = library
        self._tag_panel.set_library(library)
        self._grid_panel.set_library(library)
        self._detail_panel.set_library(library)
        self._convert_panel.set_library(library)
        self._update_library_actions()
        self.statusBar().showMessage(f"Library: {library.name}  ({library.root_path})")

    def _update_library_actions(self) -> None:
        has_lib = self._current_library is not None
        self._act_rename.setEnabled(has_lib)
        self._act_rescan_menu.setEnabled(has_lib)
        self._act_remove.setEnabled(has_lib)

    def _populate_libs_submenu(self) -> None:
        self._libs_submenu.clear()
        if not self._libraries:
            no_act = self._libs_submenu.addAction("(no libraries loaded)")
            no_act.setEnabled(False)
            return
        for i, lib in enumerate(self._libraries):
            act = self._libs_submenu.addAction(f"{lib.name}  —  {lib.root_path}")
            act.setCheckable(True)
            act.setChecked(
                self._current_library is not None
                and lib.root_path == self._current_library.root_path
            )
            act.triggered.connect(lambda _checked=False, idx=i: self._lib_combo.setCurrentIndex(idx))

    def _on_rename_library(self) -> None:
        if self._current_library is None:
            return
        name, ok = QInputDialog.getText(
            self, "Rename library", "New name:",
            text=self._current_library.name,
        )
        if not ok or not name.strip():
            return
        new_name = name.strip()
        rename_library(self._current_library.db_path, self._current_library.id, new_name)
        idx = self._lib_combo.currentIndex()
        self._current_library = Library(
            id=self._current_library.id,
            name=new_name,
            root_path=self._current_library.root_path,
        )
        self._libraries[idx] = self._current_library
        self._lib_combo.setItemText(idx, new_name)
        self._save_library_paths()
        self.statusBar().showMessage(f"Library renamed to '{new_name}'.")

    def _on_remove_library(self) -> None:
        if self._current_library is None:
            return
        reply = QMessageBox.question(
            self, "Remove library",
            f"Remove '{self._current_library.name}' from TELE-TAG?\n\n"
            "This only removes it from the app — your files and the .teletag folder are kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        idx = self._lib_combo.currentIndex()
        self._libraries.pop(idx)
        self._lib_combo.removeItem(idx)
        self._save_library_paths()
        if not self._libraries:
            self.statusBar().showMessage("No library loaded — add one to get started.")

    def _on_open_settings(self) -> None:
        from teletag.ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self)
        dlg.theme_changed.connect(self._refresh_grid)
        dlg.exec()

    def _on_open_shortcuts(self) -> None:
        from teletag.ui.shortcuts_dialog import ShortcutsDialog
        ShortcutsDialog(self).exec()

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
    # Events
    # ------------------------------------------------------------------

    def _on_tag_selected(self, tag_id: int) -> None:
        self._grid_panel.set_tag_filter(tag_id)

    def _on_search_changed(self, text: str) -> None:
        self._grid_panel.set_search(text)

    def _on_file_selected(self, file_id: int) -> None:
        self._detail_panel.show_file(file_id)

    def _on_selection_changed(self, file_ids: list) -> None:
        self._detail_panel.show_selection(file_ids)

    def _on_fullscreen_requested(self, file_id: int) -> None:
        if self._current_library is None:
            return
        from teletag.db.connection import get_connection
        conn = get_connection(self._current_library.db_path)
        row = conn.execute(
            "SELECT relative_path FROM files WHERE id = ?", (file_id,)
        ).fetchone()
        if row is None:
            return
        abs_path = str(self._current_library.root_path / row["relative_path"])
        if self._fullscreen_player is not None:
            self._fullscreen_player.close()
        self._fullscreen_player = FullscreenPlayer(abs_path)
        self._fullscreen_player.showFullScreen()

    def _on_add_to_convert_queue(self, file_ids: list[int]) -> None:
        if self._current_library is None:
            return
        self._convert_panel.add_files(file_ids, self._current_library)
        self._dock_convert.show()
        self._dock_convert.raise_()

    def _on_file_added(self, library_id: int, _abs_path: str) -> None:
        if self._current_library and self._current_library.id == library_id:
            self._refresh_all()

    def _on_file_deleted(self, library_id: int, _rel_path: str) -> None:
        if self._current_library and self._current_library.id == library_id:
            self._refresh_all()

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
        self._workspace.save()
        self._watcher.stop()
        from teletag.db.connection import close_all
        close_all()
        super().closeEvent(event)
