#!/usr/bin/env python3
"""Rewrite Skylander racing stats in BaseSkylander.pkz to a balanced roster.

WARNING: this flattens the roster. It leaves every character on one of five
profiles, so in game they all drive alike - that is the whole point of the
"balanced" scheme, and it is also why a tree patched with this tool feels
identical from figure to figure. The disc's own numbers are in
`backups/BaseSkylander.pkz.pristine` (194 stats objects, 46 distinct values,
31 toy numbers with real values, 137 zero); copy that back to undo. Do not leave
a patched copy in `disc/files/Data` unless you actually want the flattening.

Every character/vehicle stats object stores five big-endian IEEE-754 floats
(TopSpeed, Acceleration, Armor, Handling, FirePower, each 0.0-1.0). This tool
overwrites them in place, so no container offsets, sizes or ids change.

Balanced scheme: every character gets the same total (3.0) but one of five
distinct profiles, picked from the character's own numeric id so the result is
stable and varied across the roster. Vehicle stats (Plane/Car/Boat) are left
alone.
"""
import os
import re
import shutil
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pkz_stats_scan import stats_objects, STAT_NAMES  # noqa: E402

# all profiles sum to 3.0
PROFILES = [
    ("speedster", (0.9, 0.8, 0.3, 0.6, 0.4)),
    ("bruiser", (0.4, 0.3, 1.0, 0.5, 0.8)),
    ("technical", (0.5, 0.7, 0.4, 1.0, 0.4)),
    ("gunner", (0.6, 0.5, 0.5, 0.4, 1.0)),
    ("all-rounder", (0.6, 0.6, 0.6, 0.6, 0.6)),
]

VEHICLE_RE = re.compile(r"(Plane|Car|Boat)_Stats$|^RentAWreck_", re.I)
FIGURE_RE = re.compile(r"^(\d{4})_")


def is_vehicle(name):
    return bool(VEHICLE_RE.search(name))


def profile_for(name):
    m = FIGURE_RE.match(name)
    idx = int(m.group(1)) if m else sum(name.encode()) % 97
    return PROFILES[idx % len(PROFILES)]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "disc/files/Data/BaseSkylander.pkz"
    dry = "--dry-run" in sys.argv
    backup = path + ".orig"
    d = bytearray(open(path, "rb").read())
    rows = list(stats_objects(d))

    chars = [(n, o, v) for n, o, v in rows if not is_vehicle(n)]
    vehicles = [n for n, o, v in rows if is_vehicle(n)]
    print("stats objects: %d (%d character/driver/villain, %d vehicle)"
          % (len(rows), len(chars), len(vehicles)))

    counts = {}
    for name, off, old in chars:
        label, new = profile_for(name)
        counts[label] = counts.get(label, 0) + 1
        if dry:
            continue
        struct.pack_into(">5f", d, off, *new)

    print("\nprofile distribution:", ", ".join("%s=%d" % kv for kv in sorted(counts.items())))
    print("total per character:", sum(PROFILES[0][1]))
    if dry:
        print("\n(dry run, nothing written)")
        return

    if not os.path.exists(backup):
        shutil.copy2(path, backup)
        print("backup written to", backup)
    open(path, "wb").write(d)
    print("wrote", path)

    after = list(stats_objects(open(path, "rb").read()))
    bad = [n for n, o, v in after
           if not is_vehicle(n) and abs(sum(v) - 3.0) > 1e-4]
    print("verified %d rewritten objects, %d with a wrong total" % (len(after), len(bad)))
    if bad:
        print("  mismatched:", bad[:10])


if __name__ == "__main__":
    main()
