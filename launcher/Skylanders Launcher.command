#!/bin/sh
# Double-click launcher: starts the roster launcher window.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
cd "$HERE"
exec python3 SkylandersLauncher.py
