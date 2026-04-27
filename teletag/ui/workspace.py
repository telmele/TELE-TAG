"""
Workspace layout manager.

Handles dock layout persistence, named presets, and the Window menu.
"""

from PyQt6.QtWidgets import QMainWindow, QDockWidget, QMenu, QInputDialog
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QAction

_STATE_VERSION = 1
_BUILTIN_PRESETS = ("Default", "Wide Grid", "Convert Focus")


class WorkspaceManager:
    def __init__(self, window: QMainWindow) -> None:
        self._win = window
        self._docks: dict[str, QDockWidget] = {}
        self._user_preset_actions: list[QAction] = []
        self._preset_menu: QMenu | None = None

    def register_dock(self, name: str, dock: QDockWidget) -> None:
        self._docks[name] = dock

    def build_window_menu(self, menubar) -> QMenu:
        win_menu = menubar.addMenu("Window")
        for dock in self._docks.values():
            win_menu.addAction(dock.toggleViewAction())
        win_menu.addSeparator()
        self._preset_menu = win_menu.addMenu("Layout Presets")
        for preset_name in _BUILTIN_PRESETS:
            act = QAction(preset_name, self._win)
            act.triggered.connect(
                lambda checked=False, n=preset_name: self.apply_preset(n)
            )
            self._preset_menu.addAction(act)
        self._preset_menu.addSeparator()
        self._refresh_user_preset_actions()
        win_menu.addSeparator()
        save_act = QAction("Save Layout As…", self._win)
        save_act.triggered.connect(self._on_save_layout_as)
        win_menu.addAction(save_act)
        reset_act = QAction("Reset to Default Layout", self._win)
        reset_act.triggered.connect(lambda: self.apply_preset("Default"))
        win_menu.addAction(reset_act)
        return win_menu

    def save(self) -> None:
        s = QSettings()
        s.setValue("workspace/window_geometry", self._win.saveGeometry())
        s.setValue("workspace/dock_state", self._win.saveState(_STATE_VERSION))

    def restore(self) -> bool:
        """Restore saved layout. Returns False on first run (no saved state)."""
        s = QSettings()
        geo = s.value("workspace/window_geometry")
        state = s.value("workspace/dock_state")
        if geo:
            self._win.restoreGeometry(geo)
        if state:
            self._win.restoreState(state, _STATE_VERSION)
            return True
        return False

    def apply_preset(self, name: str) -> None:
        s = QSettings()
        user_state = s.value(f"workspace/presets/{name}")
        if user_state:
            self._win.restoreState(user_state, _STATE_VERSION)
            return
        self._apply_builtin(name)

    def _apply_builtin(self, name: str) -> None:
        win = self._win
        tags = self._docks.get("dock_tags")
        detail = self._docks.get("dock_detail")
        convert = self._docks.get("dock_convert")

        if name == "Default":
            if tags:
                win.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, tags)
                tags.show()
            if detail:
                win.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, detail)
                detail.show()
            if convert:
                convert.hide()
            docks_to_resize = [d for d in [tags, detail] if d]
            sizes = [200, 260][: len(docks_to_resize)]
            if docks_to_resize:
                win.resizeDocks(docks_to_resize, sizes, Qt.Orientation.Horizontal)

        elif name == "Wide Grid":
            for d in [tags, detail, convert]:
                if d:
                    d.hide()

        elif name == "Convert Focus":
            if tags:
                win.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, tags)
                tags.show()
            if detail:
                detail.hide()
            if convert:
                win.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, convert)
                convert.show()
                win.resizeDocks([convert], [350], Qt.Orientation.Vertical)

    def _on_save_layout_as(self) -> None:
        name, ok = QInputDialog.getText(self._win, "Save Layout", "Preset name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        s = QSettings()
        s.setValue(f"workspace/presets/{name}", self._win.saveState(_STATE_VERSION))
        names = self._get_user_preset_names()
        if name not in names:
            names.append(name)
            s.setValue("workspace/preset_names", names)
        self._refresh_user_preset_actions()

    def _get_user_preset_names(self) -> list[str]:
        s = QSettings()
        raw = s.value("workspace/preset_names", [])
        if isinstance(raw, str):
            return [raw]
        return list(raw) if raw else []

    def _refresh_user_preset_actions(self) -> None:
        if self._preset_menu is None:
            return
        for act in self._user_preset_actions:
            self._preset_menu.removeAction(act)
        self._user_preset_actions.clear()
        for name in self._get_user_preset_names():
            act = QAction(name, self._win)
            act.triggered.connect(
                lambda checked=False, n=name: self.apply_preset(n)
            )
            self._preset_menu.addAction(act)
            self._user_preset_actions.append(act)
