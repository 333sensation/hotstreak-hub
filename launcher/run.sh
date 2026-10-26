#!/bin/sh
# Linux / macOS: start the roster launcher.
#   ./run.sh              open the window
#   ./run.sh --check      report what this machine is missing
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
cd "$HERE"

PY=${PYTHON:-python3}
command -v "$PY" >/dev/null 2>&1 || { echo "python3 not found - install Python 3.9+" >&2; exit 1; }
"$PY" -c "import tkinter" 2>/dev/null || {
  echo "tkinter is missing. Debian/Ubuntu: sudo apt install python3-tk   Fedora: sudo dnf install python3-tkinter" >&2
  exit 1
}
"$PY" -c "import PIL" 2>/dev/null || {
  echo "Pillow is missing. Install it with: $PY -m pip install pillow" >&2
  exit 1
}
exec "$PY" SkylandersLauncher.py "$@"
