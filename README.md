# TELE-TAG

A Python desktop application for managing a local or Nextcloud-hosted video library with hierarchical tagging, re-encoding presets, and a staging inbox for incoming files.

## Features

- **Library management** — add any folder as a library; all metadata lives in a single `.teletag/metadata.db` SQLite file
- **File identity** — files tracked by relative path + xxHash so renames and moves are reconcilable on rescan
- **Hierarchical tags** — closure-table-backed tag tree with per-library scoping; searching a parent returns all descendant-tagged files
- **Video grid** — lazy-loading thumbnail grid with tag pills, drag-out to OS / Resolume
- **Re-encode panel** — HAP, DXV (requires Resolume codec), H.264, ProRes, WebM; fit / fill / stretch / resize scale modes
- **Watch folders / Staging inbox** — real-time `watchdog` monitoring; incoming files land in an inbox with a "needs tagging" badge before being promoted to the main library
- **Concurrent-safe DB** — SQLite WAL mode on every connection for freeze-free UI

## Requirements

- Python 3.11+
- `ffmpeg` on `PATH` (for thumbnail extraction, metadata probing, and transcoding)
- For DXV encoding: Resolume Avenue/Arena with the DXV codec installed on the machine

## Installation

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

# 4. Run
python main.py
```

## Nextcloud sync notes

If your library root lives inside a Nextcloud-synced folder, add the following to your Nextcloud client's **ignored files** list (or `.sync-exclude.lst`) to prevent the database WAL files from interfering with sync:

```
.teletag/metadata.db
.teletag/metadata.db-wal
.teletag/metadata.db-shm
.teletag/thumbs/
```

The `.teletag/` folder itself does **not** need to be excluded — only the files above. This keeps the DB from being partially synced mid-write.

## Project structure

```
tele-tag/
├── main.py                  # Entry point
├── requirements.txt
├── teletag/
│   ├── db/
│   │   ├── connection.py    # WAL-enabled connection manager
│   │   └── schema.py        # Schema definitions & migrations
│   ├── core/
│   │   ├── library.py       # Library CRUD
│   │   ├── ingest.py        # Scan → hash → ffprobe → thumbnail
│   │   ├── tags.py          # Tag & closure-table management
│   │   ├── encode.py        # Re-encode job runner
│   │   └── watcher.py       # Watchdog file watcher
│   └── ui/
│       ├── main_window.py   # Top-level QMainWindow
│       ├── tag_panel.py     # Left: tag tree with counts
│       ├── grid_panel.py    # Center: thumbnail grid
│       ├── detail_panel.py  # Right: file detail & re-encode
│       ├── inbox_panel.py   # Staging area / watch-folder inbox
│       ├── encode_dialog.py # Re-encode settings dialog
│       └── widgets/
│           ├── thumbnail.py # Lazy-loading thumbnail widget
│           └── tag_pill.py  # Tag pill widget
```

## License

MIT
