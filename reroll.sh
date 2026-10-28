#!/bin/sh
# Roll a fresh random bot cast into hotstreak-hub.wbfs.
#
# Each run recasts the AI records a race can field (56 driver infos + 12 villain
# infos, one figure per character) at random figures out of the 128 playable ones
# - in place, so the container keeps its size and the loader stays happy, and
# without touching the vehicle each record drives - then sets every bot to one
# pace per difficulty band, repacks and verifies the image. Use --seed N for a
# reproducible cast, --must to pin characters.
#
# Usage: ./reroll.sh [--seed N] [--must Spyro,Whirlwind,Bash]
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
cd "$HERE"

WIT=../DolRecomp/extern/wit/bin/wit
DATA=disc/files/Data

echo "== rolling a new cast"
python3 tools/pkz_random_bots.py "$@"

echo "== uniform bot pace (tools/pkz_ai_speed.py)"
python3 tools/pkz_ai_speed.py

echo "== repacking"
"$WIT" copy disc hotstreak-hub.wbfs --overwrite >/dev/null
"$WIT" verify hotstreak-hub.wbfs 2>&1 | tail -1

echo "== done: $HERE/hotstreak-hub.wbfs"
