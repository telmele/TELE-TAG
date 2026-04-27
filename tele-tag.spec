# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []

for pkg in ("PyQt6", "xxhash", "watchdog"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# FFmpeg binaries downloaded by CI into ffmpeg_bin/ — bundle them at root
# so sys._MEIPASS (prepended to PATH at startup) resolves ffmpeg/ffprobe.
_ffmpeg_dir = Path("ffmpeg_bin")
if _ffmpeg_dir.exists():
    for _exe in sorted(_ffmpeg_dir.iterdir()):
        if _exe.is_file():
            binaries.append((str(_exe), "."))

a = Analysis(
    ["main.py"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TELE-TAG",
    debug=False,
    console=False,
    argv_emulation=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="TELE-TAG",
)

# macOS app bundle — only active when spec runs on darwin
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="TELE-TAG.app",
        bundle_identifier="studio.uncannyvalley.tele-tag",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleShortVersionString": "1.0.0",
        },
    )
