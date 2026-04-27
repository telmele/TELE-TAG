# TELE-TAG

**A local video library manager built for VJs.**

Organize, tag, and re-encode your video assets — HAP, H.264, ProRes, WebM — without leaving your desktop. No cloud, no subscription, no telemetry. Everything lives in a single SQLite file next to your footage.

---

## Features

- **Hierarchical tags** — organize tags in a parent → child tree; filtering a parent returns all descendant files
- **Thumbnail grid & list view** — browse your library with tag pills, drag files out to the OS or Resolume
- **Folder mode** — nested folder tree inside both grid and list views
- **Re-encode** — HAP, DXV\*, H.264, ProRes, WebM with fit / fill / stretch / resize scale modes
- **Fullscreen player** — click any thumbnail to play inline
- **Watch folders** — new files appear automatically via real-time monitoring
- **Dockable panels & themes** — flexible layout, four built-in color themes

> \* DXV encoding requires the Resolume DXV codec installed separately.

---

## Download

Pre-built binaries (FFmpeg included) are attached to every [GitHub Release](../../releases/latest).

| Platform | File |
|---|---|
| Windows 10/11 (64-bit) | `TELE-TAG-windows.zip` |
| macOS 10.15+ (Intel + Rosetta 2) | `TELE-TAG-macos.zip` |
| Linux (Ubuntu 22.04+) | `TELE-TAG-linux.tar.gz` |

**Windows** — extract the zip, run `TELE-TAG.exe`.

**macOS** — extract the zip, right-click `TELE-TAG.app` → Open (needed once to bypass Gatekeeper on unsigned builds).

**Linux** — extract the archive, run `./TELE-TAG/TELE-TAG`. You may need `libgl1` and `libxcb-cursor0`:
```bash
sudo apt-get install libgl1 libxcb-cursor0
```

---

## Run from Source

```bash
# 1. Clone
git clone https://github.com/youruser/tele-tag.git
cd tele-tag

# 2. Create virtual environment
python -m venv .venv

# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Install FFmpeg (required — not bundled when running from source)
# macOS:   brew install ffmpeg
# Ubuntu:  sudo apt install ffmpeg
# Windows: winget install ffmpeg  (or download from https://ffmpeg.org)

# 5. Run
python main.py
```

Requirements: **Python 3.11+** and **FFmpeg** on your PATH.

---

## Nextcloud / Synced Folders

Add these to your sync client's ignored files list to prevent partial-sync issues with the WAL write-ahead log:

```
.teletag/metadata.db-wal
.teletag/metadata.db-shm
.teletag/thumbs/
```

---

## Credits

TELE-TAG was built by telmele with the help of [Claude](https://claude.ai) (Anthropic) as an AI pair programmer — used throughout for architecture decisions, feature implementation, and debugging.

---

## License

MIT
