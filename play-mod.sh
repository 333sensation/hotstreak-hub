#!/bin/sh
# Run the Skylanders SuperChargers Racing mod image in Dolphin.
#
# Dolphin 2606a's Metal backend fails to build vertex pipelines on this disc
# ("Vertex attribute rawpos(0) is missing from the vertex descriptor", dumps to
# ~/Library/Application Support/Dolphin/Dump/bad_pipeline_Metal_*.txt). OpenGL
# has no such problem, so the backend is forced with -v ogl here instead of
# editing Dolphin's own configuration.
#
# Usage: ./play-mod.sh [extra dolphin args]

set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
IMAGE="$HERE/skylanders-scr-mod.wbfs"
DOLPHIN=/Applications/Dolphin.app/Contents/MacOS/Dolphin

[ -x "$DOLPHIN" ] || { echo "Dolphin not found at $DOLPHIN" >&2; exit 1; }
[ -f "$IMAGE" ] || { echo "missing $IMAGE" >&2; exit 1; }

exec "$DOLPHIN" -v ogl -e "$IMAGE" "$@"
