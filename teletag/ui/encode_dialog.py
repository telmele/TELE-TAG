"""
Re-encode dialog.

Lets the user choose preset, target resolution, and scale mode,
then queues an encode job.
"""

import threading
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QComboBox,
    QSpinBox, QDialogButtonBox, QProgressBar, QLabel,
    QHBoxLayout, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject

from teletag.core.encode import PRESETS, SCALE_MODES, create_job, run_encode_job
from teletag.core.library import Library
from teletag.db.connection import get_connection


class _EncodeSignals(QObject):
    progress = pyqtSignal(float)
    finished = pyqtSignal(bool, str)   # (success, message)


class EncodeDialog(QDialog):
    job_started = pyqtSignal(int)  # job_id

    def __init__(self, library: Library, file_id: int, parent=None) -> None:
        super().__init__(parent)
        self._library = library
        self._file_id = file_id
        self._signals = _EncodeSignals()
        self._signals.progress.connect(self._on_progress)
        self._signals.finished.connect(self._on_finished)
        self.setWindowTitle("Re-encode")
        self.setMinimumWidth(360)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # File name
        conn = get_connection(self._library.db_path)
        row = conn.execute(
            "SELECT relative_path FROM files WHERE id = ?", (self._file_id,)
        ).fetchone()
        name = Path(row["relative_path"]).name if row else "Unknown"
        layout.addWidget(QLabel(f"<b>{name}</b>"))

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._preset_combo = QComboBox()
        for p in PRESETS:
            self._preset_combo.addItem(p.upper(), p)
        form.addRow("Preset:", self._preset_combo)

        # DXV note
        self._dxv_note = QLabel(
            "⚠ DXV requires Resolume Avenue / Arena codec installed on this machine."
        )
        self._dxv_note.setStyleSheet("color: #e0a030; font-size: 11px;")
        self._dxv_note.setWordWrap(True)
        self._dxv_note.hide()
        layout.addWidget(self._dxv_note)
        self._preset_combo.currentIndexChanged.connect(self._on_preset_changed)

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

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.hide()
        layout.addWidget(self._progress)

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_encode)
        buttons.rejected.connect(self.reject)
        self._ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_btn.setText("Encode")
        layout.addWidget(buttons)

    def _on_preset_changed(self) -> None:
        preset = self._preset_combo.currentData()
        self._dxv_note.setVisible(preset == "dxv")

    def _on_encode(self) -> None:
        preset = self._preset_combo.currentData()
        scale_mode = self._scale_combo.currentData()
        w = self._width_spin.value()
        h = self._height_spin.value()

        conn = get_connection(self._library.db_path)
        row = conn.execute(
            "SELECT relative_path FROM files WHERE id = ?", (self._file_id,)
        ).fetchone()
        if row is None:
            return

        input_path = self._library.root_path / row["relative_path"]
        ext_map = {"hap": ".mov", "dxv": ".mov", "h264": ".mp4", "prores": ".mov", "webm": ".webm"}
        ext = ext_map.get(preset, ".mp4")
        output_path = input_path.with_name(input_path.stem + f"_{preset}{ext}")

        job_id = create_job(
            self._library.db_path,
            self._file_id, preset, w, h, scale_mode, str(output_path),
        )
        self.job_started.emit(job_id)

        self._progress.show()
        self._ok_btn.setEnabled(False)
        self._status_label.setText("Encoding…")

        sigs = self._signals

        def worker():
            run_encode_job(
                self._library, job_id, input_path, output_path,
                preset, w, h, scale_mode,
                progress_cb=lambda pct: sigs.progress.emit(pct),
                error_cb=lambda msg: sigs.finished.emit(False, msg),
            )
            sigs.finished.emit(True, "Done!")

        threading.Thread(target=worker, daemon=True).start()

    def _on_progress(self, pct: float) -> None:
        self._progress.setValue(int(pct))

    def _on_finished(self, success: bool, message: str) -> None:
        self._ok_btn.setEnabled(True)
        self._status_label.setText(message)
        if success:
            self._progress.setValue(100)
        else:
            QMessageBox.critical(self, "Encode error", message)
