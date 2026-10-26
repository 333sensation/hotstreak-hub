#!/bin/sh
# Linux / macOS: start the roster launcher.
#   ./run.sh              open the window
#   ./run.sh --check      report what this machine is missing
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
exec "$HERE/launcher/run.sh" "$@"
