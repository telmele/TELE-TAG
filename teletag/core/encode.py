"""
Re-encode job runner.

Presets: HAP, DXV (requires Resolume codec), H.264, ProRes, WebM.
Scale modes: resize, fit, fill, stretch.

FFmpeg runs in a subprocess; stdout/stderr are parsed for progress.
Job status is persisted to the `encode_jobs` table.
"""

import logging
import re
import subprocess
from pathlib import Path
from typing import Callable

from teletag.db.connection import get_connection
from teletag.core.library import Library

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PRESETS = ["hap", "dxv", "h264", "prores", "webm"]
SCALE_MODES = ["resize", "fit", "fill", "stretch"]


def _scale_filter(mode: str, w: int, h: int) -> str:
    if mode == "fit":
        return (
            f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
        )
    if mode == "fill":
        return (
            f"scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h}"
        )
    if mode == "stretch":
        return f"scale={w}:{h}"
    # "resize" — exact
    return f"scale={w}:{h}"


def _build_ffmpeg_cmd(
    input_path: Path,
    output_path: Path,
    preset: str,
    scale_filter: str,
) -> list[str]:
    base = ["ffmpeg", "-y", "-i", str(input_path)]

    vf = ["-vf", scale_filter]

    if preset == "hap":
        codec_args = ["-c:v", "hap", "-format", "hap"]
    elif preset == "dxv":
        # Requires the Resolume DXV codec installed on the system.
        codec_args = ["-c:v", "dxv"]
    elif preset == "h264":
        codec_args = ["-c:v", "libx264", "-crf", "18", "-preset", "fast", "-c:a", "aac"]
    elif preset == "prores":
        codec_args = ["-c:v", "prores_ks", "-profile:v", "3", "-c:a", "pcm_s16le"]
    elif preset == "webm":
        codec_args = ["-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "0", "-c:a", "libopus"]
    else:
        raise ValueError(f"Unknown preset: {preset!r}")

    return base + vf + codec_args + ["-progress", "pipe:1", str(output_path)]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def create_job(
    db_path: Path,
    file_id: int,
    preset: str,
    output_width: int,
    output_height: int,
    scale_mode: str,
    output_path: str,
) -> int:
    conn = get_connection(db_path)
    with conn:
        cur = conn.execute(
            """
            INSERT INTO encode_jobs
                (file_id, preset, output_width, output_height, scale_mode, status, output_path)
            VALUES (?, ?, ?, ?, ?, 'queued', ?)
            """,
            (file_id, preset, output_width, output_height, scale_mode, output_path),
        )
    return cur.lastrowid


def _set_job_status(db_path: Path, job_id: int, status: str) -> None:
    conn = get_connection(db_path)
    with conn:
        conn.execute(
            "UPDATE encode_jobs SET status = ? WHERE id = ?",
            (status, job_id),
        )


def list_jobs(db_path: Path, file_id: int | None = None) -> list[dict]:
    conn = get_connection(db_path)
    if file_id is not None:
        rows = conn.execute(
            "SELECT * FROM encode_jobs WHERE file_id = ? ORDER BY created_at DESC",
            (file_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM encode_jobs ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_encode_job(
    library: Library,
    job_id: int,
    input_path: Path,
    output_path: Path,
    preset: str,
    output_width: int,
    output_height: int,
    scale_mode: str,
    progress_cb: Callable[[float], None] | None = None,
    error_cb: Callable[[str], None] | None = None,
) -> bool:
    """
    Execute a single encode job synchronously.
    *progress_cb(pct)* is called with a 0-100 float.
    *error_cb(message)* is called if ffmpeg returns non-zero or the codec is missing.
    Returns True on success.
    """
    db_path = library.db_path
    _set_job_status(db_path, job_id, "running")

    scale_f = _scale_filter(scale_mode, output_width, output_height)
    cmd = _build_ffmpeg_cmd(input_path, output_path, preset, scale_f)

    # Probe total duration for progress percentage.
    try:
        import json, subprocess as sp
        probe = sp.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(input_path)],
            capture_output=True, text=True, timeout=10,
        )
        total_us = float(json.loads(probe.stdout).get("format", {}).get("duration", 0)) * 1_000_000
    except Exception:
        total_us = 0.0

    logger.info("Starting encode: %s -> %s [%s/%s]", input_path.name, output_path.name, preset, scale_mode)

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError:
        msg = "ffmpeg not found — please install ffmpeg and ensure it is on your PATH."
        logger.error(msg)
        _set_job_status(db_path, job_id, "error")
        if error_cb:
            error_cb(msg)
        return False

    out_time_re = re.compile(r"out_time_us=(\d+)")

    assert proc.stdout is not None
    for line in proc.stdout:
        m = out_time_re.search(line)
        if m and total_us > 0 and progress_cb:
            pct = min(100.0, float(m.group(1)) / total_us * 100.0)
            progress_cb(pct)

    proc.wait()

    if proc.returncode != 0:
        stderr = proc.stderr.read() if proc.stderr else ""
        # DXV-specific hint.
        if preset == "dxv" and "Unknown encoder" in stderr:  # noqa: S105
            msg = (
                "DXV encoding requires the Resolume DXV codec to be installed on this machine. "
                "Please install Resolume Avenue or Arena, then retry."
            )
        else:
            msg = f"ffmpeg exited with code {proc.returncode}:\n{stderr[:500]}"
        logger.error(msg)
        _set_job_status(db_path, job_id, "error")
        if error_cb:
            error_cb(msg)
        return False

    _set_job_status(db_path, job_id, "done")
    logger.info("Encode complete: %s", output_path)
    return True
