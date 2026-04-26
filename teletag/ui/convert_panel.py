"""
Convert panel — encode queue.

Layout (horizontal splitter):
  Queue (left) | Settings (middle) | Source info & tags (right)

Files are added from the Library grid via right-click → "Add to Convert Queue".
Each entry bakes in the current settings at the moment of adding.
After a successful encode the output file is ingested and inherits the
source file's tags automatically.
"""

from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QSplitter, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QFrame, QScrollArea, QComboBox, QSpinBox,
    QPushButton, QProgressBar, QSizePolicy, QGridLayout, QPlainTextEdit,
    QRadioButton, QButtonGroup, QLineEdit, QFileDialog,
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtGui import QFont

from teletag.core.library import Library
from teletag.core.encode import PRESETS, SCALE_MODES, create_job, run_encode_job
from teletag.core.ingest import ingest_single
from teletag.core.tags import get_tags_for_file, assign_tag
from teletag.db.connection import get_connection
from teletag.ui.widgets.tag_pill import TagPill


_EXT = {"hap": ".mov", "dxv": ".mov", "h264": ".mp4", "prores": ".mov", "webm": ".webm"}
_STATUS_COLOR = {
    "queued":  "#6d6d7a",
    "running": "#6a8fd8",
    "done":    "#4caf50",
    "error":   "#e05252",
}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class _Entry:
    file_id: int
    library: Library
    abs_path: Path
    output_path: Path
    filename: str
    preset: str
    width: int
    height: int
    scale_mode: str
    status: str = "queued"
    job_id: int | None = None
    progress: float = 0.0
    error_msg: str = ""


# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------

class _Worker(QThread):
    job_started  = pyqtSignal(int)             # entry index
    job_progress = pyqtSignal(int, float)      # entry index, pct
    job_done     = pyqtSignal(int, bool, str)  # entry index, success, message
    log_line     = pyqtSignal(str)             # one line of ffmpeg stderr

    def __init__(self, entries: list[_Entry]) -> None:
        super().__init__()
        self._entries = entries
        self._abort = False

    def abort(self) -> None:
        self._abort = True

    def run(self) -> None:
        for i, e in enumerate(self._entries):
            if self._abort:
                break
            if e.status != "queued":
                continue
            self.job_started.emit(i)

            out = e.output_path
            out.parent.mkdir(parents=True, exist_ok=True)

            e.job_id = create_job(
                e.library.db_path, e.file_id,
                e.preset, e.width, e.height, e.scale_mode, str(out),
            )

            err: list[str] = []
            ok = run_encode_job(
                e.library, e.job_id, e.abs_path, out,
                e.preset, e.width, e.height, e.scale_mode,
                progress_cb=lambda p, idx=i: self.job_progress.emit(idx, p),
                error_cb=lambda m: err.append(m),
                log_cb=self.log_line.emit,
            )

            if ok:
                try:
                    new_id = ingest_single(e.library, out)
                    if new_id:
                        for tag in get_tags_for_file(e.library.db_path, e.file_id):
                            assign_tag(e.library.db_path, new_id, tag.id)
                except Exception:
                    pass

            self.job_done.emit(i, ok, err[0] if err else "")


# ---------------------------------------------------------------------------
# Queue row widget
# ---------------------------------------------------------------------------

class _JobRow(QFrame):
    selected = pyqtSignal(int)  # entry index

    def __init__(self, index: int, entry: _Entry, parent=None) -> None:
        super().__init__(parent)
        self._index = index
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        # Top: filename + preset badge
        top = QHBoxLayout()
        top.setSpacing(6)
        name_lbl = QLabel(entry.filename)
        name_lbl.setStyleSheet("font-size: 12px;")
        top.addWidget(name_lbl, 1)
        badge = QLabel(entry.preset.upper())
        badge.setStyleSheet(
            "font-size: 10px; padding: 1px 6px;"
            "background: #2a2938; border-radius: 3px; color: #a0a0b8;"
        )
        top.addWidget(badge)
        layout.addLayout(top)

        # Bottom: progress bar + status text
        bot = QHBoxLayout()
        bot.setSpacing(6)
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setFixedHeight(5)
        self._bar.setTextVisible(False)
        self._bar.setStyleSheet(
            "QProgressBar { background: #2a2938; border-radius: 2px; }"
            f"QProgressBar::chunk {{ background: {_STATUS_COLOR['queued']}; border-radius: 2px; }}"
        )
        bot.addWidget(self._bar, 1)
        self._status_lbl = QLabel("queued")
        self._status_lbl.setFixedWidth(44)
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._status_lbl.setStyleSheet(f"font-size: 10px; color: {_STATUS_COLOR['queued']};")
        bot.addWidget(self._status_lbl)
        layout.addLayout(bot)

        self._highlight(False)

    def update_status(self, status: str, progress: float = 0.0, msg: str = "") -> None:
        c = _STATUS_COLOR.get(status, "#6d6d7a")
        self._bar.setStyleSheet(
            "QProgressBar { background: #2a2938; border-radius: 2px; }"
            f"QProgressBar::chunk {{ background: {c}; border-radius: 2px; }}"
        )
        if status == "running":
            self._bar.setValue(int(progress))
            self._status_lbl.setText(f"{int(progress)}%")
        elif status == "done":
            self._bar.setValue(100)
            self._status_lbl.setText("done")
        elif status == "error":
            self._bar.setValue(0)
            self._status_lbl.setText("error")
        else:
            self._bar.setValue(0)
            self._status_lbl.setText("queued")
        self._status_lbl.setStyleSheet(f"font-size: 10px; color: {c};")

    def set_selected(self, s: bool) -> None:
        self._highlight(s)

    def _highlight(self, on: bool) -> None:
        self.setStyleSheet(
            "QFrame { background: #2d2c3a; border-radius: 4px; }" if on
            else "QFrame { background: transparent; }"
        )

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self._index)
        super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------

class ConvertPanel(QWidget):
    """Three-pane encode queue: Queue | Settings | Source Info."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._library: Library | None = None
        self._entries: list[_Entry] = []
        self._rows: list[_JobRow] = []
        self._selected_idx: int | None = None
        self._worker: _Worker | None = None
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_queue_pane())
        splitter.addWidget(self._build_settings_pane())
        splitter.addWidget(self._build_info_pane())
        splitter.setSizes([320, 320, 280])
        splitter.setStretchFactor(0, 1)
        outer.addWidget(splitter)

    def _build_queue_pane(self) -> QWidget:
        w = QWidget()
        w.setMinimumWidth(240)
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._queue_title = QLabel("Queue — 0 items")
        font = QFont()
        font.setBold(True)
        font.setPointSize(11)
        self._queue_title.setFont(font)
        layout.addWidget(self._queue_title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        inner = QWidget()
        self._queue_layout = QVBoxLayout(inner)
        self._queue_layout.setContentsMargins(0, 0, 0, 0)
        self._queue_layout.setSpacing(2)
        self._queue_layout.addStretch()
        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)

        self._clear_btn = QPushButton("Clear completed")
        self._clear_btn.clicked.connect(self._clear_completed)
        layout.addWidget(self._clear_btn)

        return w

    def _build_settings_pane(self) -> QWidget:
        w = QWidget()
        w.setMinimumWidth(240)
        w.setMaximumWidth(360)
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        title = QLabel("Encode Settings")
        font = QFont()
        font.setBold(True)
        font.setPointSize(11)
        title.setFont(font)
        layout.addWidget(title)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(6)

        self._preset_combo = QComboBox()
        for p in PRESETS:
            self._preset_combo.addItem(p.upper(), p)
        self._preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        form.addRow("Preset:", self._preset_combo)

        self._scale_combo = QComboBox()
        for s in SCALE_MODES:
            self._scale_combo.addItem(s.capitalize(), s)
        form.addRow("Scale mode:", self._scale_combo)

        res_row = QHBoxLayout()
        self._width_spin = QSpinBox()
        self._width_spin.setRange(16, 7680)
        self._width_spin.setSingleStep(8)
        self._width_spin.setValue(1920)
        self._height_spin = QSpinBox()
        self._height_spin.setRange(16, 4320)
        self._height_spin.setSingleStep(8)
        self._height_spin.setValue(1080)
        res_row.addWidget(self._width_spin)
        res_row.addWidget(QLabel("×"))
        res_row.addWidget(self._height_spin)
        form.addRow("Resolution:", res_row)

        layout.addLayout(form)

        # ── Output destination ────────────────────────────────────────
        dest_lbl = QLabel("Output destination:")
        dest_lbl.setStyleSheet("font-weight: bold; font-size: 11px;")
        layout.addWidget(dest_lbl)

        self._dest_group = QButtonGroup(w)

        self._rb_same = QRadioButton("Same folder as source")
        self._rb_same.setChecked(True)
        self._dest_group.addButton(self._rb_same, 0)
        layout.addWidget(self._rb_same)

        self._rb_subfolder = QRadioButton("Sub-folder:")
        self._dest_group.addButton(self._rb_subfolder, 1)
        layout.addWidget(self._rb_subfolder)

        subfolder_row = QHBoxLayout()
        subfolder_row.setContentsMargins(20, 0, 0, 0)
        self._subfolder_edit = QLineEdit("encoded")
        self._subfolder_edit.setPlaceholderText("folder name…")
        subfolder_row.addWidget(self._subfolder_edit)
        layout.addLayout(subfolder_row)

        self._rb_custom = QRadioButton("Custom folder:")
        self._dest_group.addButton(self._rb_custom, 2)
        layout.addWidget(self._rb_custom)

        custom_row = QHBoxLayout()
        custom_row.setContentsMargins(20, 0, 0, 0)
        self._custom_path_edit = QLineEdit()
        self._custom_path_edit.setPlaceholderText("choose folder…")
        self._custom_path_edit.setReadOnly(True)
        custom_row.addWidget(self._custom_path_edit, 1)
        btn_browse = QPushButton("…")
        btn_browse.setFixedWidth(28)
        btn_browse.clicked.connect(self._browse_custom_folder)
        custom_row.addWidget(btn_browse)
        layout.addLayout(custom_row)

        # ── Rename template ───────────────────────────────────────────
        rename_lbl = QLabel("Output filename:")
        rename_lbl.setStyleSheet("font-weight: bold; font-size: 11px;")
        layout.addWidget(rename_lbl)

        self._rename_edit = QLineEdit("{name}_{preset}_{w}x{h}")
        self._rename_edit.setToolTip(
            "Variables: {name} original stem, {preset}, {w}, {h}, {scale}"
        )
        hint = QLabel("  {name}  {preset}  {w}  {h}  {scale}")
        hint.setStyleSheet("color: #6d6d7a; font-size: 10px;")
        layout.addWidget(self._rename_edit)
        layout.addWidget(hint)

        self._dxv_note = QLabel(
            "⚠ DXV requires the Resolume codec installed on this machine."
        )
        self._dxv_note.setStyleSheet("color: #e0a030; font-size: 11px;")
        self._dxv_note.setWordWrap(True)
        self._dxv_note.hide()
        layout.addWidget(self._dxv_note)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setStyleSheet("color: #444;")
        layout.addWidget(sep1)

        # Queue controls
        self._start_btn = QPushButton("▶  Start Queue")
        self._start_btn.setStyleSheet(
            "QPushButton { background: #2a4a2a; color: #4caf50; border-radius: 4px; padding: 6px; font-weight: bold; }"
            "QPushButton:hover { background: #2e5a2e; }"
            "QPushButton:disabled { color: #444; background: #1e1e2a; }"
        )
        self._start_btn.clicked.connect(self._start_queue)
        layout.addWidget(self._start_btn)

        self._stop_btn = QPushButton("■  Stop")
        self._stop_btn.setStyleSheet(
            "QPushButton { background: #4a2a2a; color: #e05252; border-radius: 4px; padding: 6px; font-weight: bold; }"
            "QPushButton:hover { background: #5a2e2e; }"
            "QPushButton:disabled { color: #444; background: #1e1e2a; }"
        )
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._stop_queue)
        layout.addWidget(self._stop_btn)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color: #444;")
        layout.addWidget(sep2)

        self._progress_lbl = QLabel("No jobs running")
        self._progress_lbl.setStyleSheet("color: #6d6d7a; font-size: 11px;")
        layout.addWidget(self._progress_lbl)

        self._current_bar = QProgressBar()
        self._current_bar.setRange(0, 100)
        self._current_bar.setValue(0)
        self._current_bar.setFixedHeight(8)
        self._current_bar.hide()
        layout.addWidget(self._current_bar)

        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setStyleSheet("color: #444;")
        layout.addWidget(sep3)

        log_lbl = QLabel("Output")
        log_lbl.setStyleSheet("font-weight: bold; font-size: 11px;")
        layout.addWidget(log_lbl)

        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._log_view.setStyleSheet(
            "QPlainTextEdit {"
            "  background: #0d0d14;"
            "  color: #c0c0d0;"
            "  font-family: Consolas, 'Courier New', monospace;"
            "  font-size: 11px;"
            "  border: 1px solid #2a2938;"
            "  border-radius: 4px;"
            "}"
        )
        self._log_view.setMaximumBlockCount(2000)
        layout.addWidget(self._log_view, 1)

        return w

    def _build_info_pane(self) -> QWidget:
        w = QWidget()
        w.setMinimumWidth(200)
        w.setMaximumWidth(320)
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QLabel("Source File")
        font = QFont()
        font.setBold(True)
        font.setPointSize(11)
        title.setFont(font)
        layout.addWidget(title)

        meta_frame = QFrame()
        meta_frame.setFrameShape(QFrame.Shape.StyledPanel)
        meta_grid = QGridLayout(meta_frame)
        meta_grid.setSpacing(4)

        self._info_labels: dict[str, QLabel] = {}
        for row, key in enumerate(["Name", "Duration", "Resolution", "Codec", "Path"]):
            lk = QLabel(key + ":")
            lk.setStyleSheet("color: #6d6d7a; font-size: 11px;")
            lv = QLabel("—")
            lv.setWordWrap(True)
            lv.setStyleSheet("font-size: 11px;")
            meta_grid.addWidget(lk, row, 0, Qt.AlignmentFlag.AlignTop)
            meta_grid.addWidget(lv, row, 1, Qt.AlignmentFlag.AlignTop)
            self._info_labels[key] = lv
        layout.addWidget(meta_frame)

        tags_lbl = QLabel("Tags")
        tags_lbl.setStyleSheet("font-weight: bold;")
        layout.addWidget(tags_lbl)

        self._info_tags_container = QWidget()
        self._info_tags_layout = QHBoxLayout(self._info_tags_container)
        self._info_tags_layout.setContentsMargins(0, 0, 0, 0)
        self._info_tags_layout.setSpacing(4)
        self._info_tags_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self._info_tags_container)

        layout.addStretch()
        return w

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def set_library(self, library: Library) -> None:
        self._library = library

    def _browse_custom_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select output folder")
        if folder:
            self._custom_path_edit.setText(folder)
            self._rb_custom.setChecked(True)

    def _compute_output_path(self, abs_path: Path, preset: str, width: int, height: int, scale_mode: str) -> Path:
        ext = _EXT.get(preset, ".mp4")
        template = self._rename_edit.text().strip() or "{name}_{preset}"
        stem = template.format(
            name=abs_path.stem,
            preset=preset,
            w=width,
            h=height,
            scale=scale_mode,
        )
        filename = stem + ext

        dest_id = self._dest_group.checkedId()
        if dest_id == 1:
            # Sub-folder of the source file's directory
            sub = self._subfolder_edit.text().strip() or "encoded"
            return abs_path.parent / sub / filename
        elif dest_id == 2:
            # Custom folder
            custom = self._custom_path_edit.text().strip()
            if custom:
                return Path(custom) / filename
        # Default: same folder as source
        return abs_path.parent / filename

    def add_files(self, file_ids: list[int], library: Library) -> None:
        """Add files to the queue using the current settings."""
        preset = self._preset_combo.currentData()
        width = self._width_spin.value()
        height = self._height_spin.value()
        scale_mode = self._scale_combo.currentData()

        conn = get_connection(library.db_path)
        for fid in file_ids:
            row = conn.execute(
                "SELECT relative_path FROM files WHERE id = ?", (fid,)
            ).fetchone()
            if row is None:
                continue
            abs_path = library.root_path / row["relative_path"]
            output_path = self._compute_output_path(abs_path, preset, width, height, scale_mode)
            entry = _Entry(
                file_id=fid,
                library=library,
                abs_path=abs_path,
                output_path=output_path,
                filename=Path(row["relative_path"]).name,
                preset=preset,
                width=width,
                height=height,
                scale_mode=scale_mode,
            )
            self._entries.append(entry)
            self._add_row(entry)

        self._update_queue_title()

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------

    def _add_row(self, entry: _Entry) -> None:
        idx = len(self._rows)
        row = _JobRow(idx, entry)
        row.selected.connect(self._on_row_selected)
        self._rows.append(row)
        # Insert before the trailing stretch item
        self._queue_layout.insertWidget(self._queue_layout.count() - 1, row)

    def _on_row_selected(self, idx: int) -> None:
        if self._selected_idx is not None and self._selected_idx < len(self._rows):
            self._rows[self._selected_idx].set_selected(False)
        self._selected_idx = idx
        self._rows[idx].set_selected(True)
        self._show_info(self._entries[idx])

    def _show_info(self, entry: _Entry) -> None:
        conn = get_connection(entry.library.db_path)
        row = conn.execute("SELECT * FROM files WHERE id = ?", (entry.file_id,)).fetchone()
        if row is None:
            return
        d = dict(row)
        self._info_labels["Name"].setText(entry.filename)
        self._info_labels["Duration"].setText(f"{d['duration']:.1f}s" if d.get("duration") else "—")
        self._info_labels["Resolution"].setText(d.get("resolution") or "—")
        self._info_labels["Codec"].setText(d.get("codec") or "—")
        self._info_labels["Path"].setText(d.get("relative_path") or "—")

        while self._info_tags_layout.count():
            item = self._info_tags_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        for tag in get_tags_for_file(entry.library.db_path, entry.file_id):
            self._info_tags_layout.addWidget(TagPill(tag.name))

    def _clear_completed(self) -> None:
        """Remove done/error entries from the queue (only when worker is idle)."""
        if self._worker and self._worker.isRunning():
            return
        keep_entries = []
        keep_rows_idx = []
        for i, (entry, row) in enumerate(zip(self._entries, self._rows)):
            if entry.status in ("done", "error"):
                self._queue_layout.removeWidget(row)
                row.deleteLater()
            else:
                keep_entries.append(entry)
                keep_rows_idx.append(i)

        self._entries = keep_entries
        # Rebuild rows list and re-index
        self._rows = [r for i, r in enumerate(self._rows) if i in set(keep_rows_idx)]
        for new_idx, row in enumerate(self._rows):
            row._index = new_idx

        self._selected_idx = None
        self._update_queue_title()

    def _update_queue_title(self) -> None:
        n = len(self._entries)
        done = sum(1 for e in self._entries if e.status == "done")
        self._queue_title.setText(f"Queue — {n} item{'s' if n != 1 else ''}" +
                                  (f"  ({done} done)" if done else ""))

    # ------------------------------------------------------------------
    # Encode controls
    # ------------------------------------------------------------------

    def _on_preset_changed(self) -> None:
        self._dxv_note.setVisible(self._preset_combo.currentData() == "dxv")

    def _start_queue(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        if not any(e.status == "queued" for e in self._entries):
            return
        self._log_view.clear()
        self._worker = _Worker(self._entries)
        self._worker.job_started.connect(self._on_job_started)
        self._worker.job_progress.connect(self._on_job_progress)
        self._worker.job_done.connect(self._on_job_done)
        self._worker.log_line.connect(self._append_log)
        self._worker.finished.connect(self._on_all_done)
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._current_bar.show()
        self._worker.start()

    def _stop_queue(self) -> None:
        if self._worker:
            self._worker.abort()
        self._stop_btn.setEnabled(False)

    def _on_job_started(self, idx: int) -> None:
        e = self._entries[idx]
        e.status = "running"
        if idx < len(self._rows):
            self._rows[idx].update_status("running", 0.0)
        self._current_bar.setValue(0)
        self._progress_lbl.setText(f"Encoding: {e.filename}")

    def _on_job_progress(self, idx: int, pct: float) -> None:
        self._entries[idx].progress = pct
        if idx < len(self._rows):
            self._rows[idx].update_status("running", pct)
        self._current_bar.setValue(int(pct))

    def _on_job_done(self, idx: int, ok: bool, msg: str) -> None:
        e = self._entries[idx]
        e.status = "done" if ok else "error"
        e.error_msg = msg
        if idx < len(self._rows):
            self._rows[idx].update_status(e.status, 100 if ok else 0, msg)
        self._update_queue_title()

    def _append_log(self, line: str) -> None:
        self._log_view.appendPlainText(line)
        # Keep scrolled to bottom.
        sb = self._log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_all_done(self) -> None:
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._current_bar.hide()
        done = sum(1 for e in self._entries if e.status == "done")
        total = len(self._entries)
        self._progress_lbl.setText(f"{done} / {total} done")
