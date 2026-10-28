#!/bin/sh
# Roll a new track line-up into the three cups and repack the image.
#
# Each run picks five of the seven circuits of every terrain, in a random order,
# out of the tracks the disc already ships for that terrain (land, sea, air) -
# in place, so Common.pkz keeps its size and the loader stays happy.
#
# Usage: ./cups.sh [--seed N] [--mirrors] [--print]
#   --seed N    reproducible line-up (the launcher derives this from the
#               session code, so both netplay players get the same cups)
#   --mirrors   allow the reversed versions of the circuits as well
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
cd "$HERE"

WIT=../DolRecomp/extern/wit/bin/wit

echo "== rolling new cup tracks"
python3 tools/pkz_cup_random.py "$@"

echo "== repacking"
"$WIT" copy disc hotstreak-hub.wbfs --overwrite >/dev/null
"$WIT" verify hotstreak-hub.wbfs 2>&1 | tail -1

echo "== done: $HERE/hotstreak-hub.wbfs"
