#!/usr/bin/env python3
"""Extract per-character racing stat blocks from goliath .pkz containers.

Each object in a .pkz chunk stream ends with an end marker, its inline name and
a data chunk holding the object's payload:

    80 00 13 91 00 08 ... <id> ... <5 f32>     data chunk: TopSpeed, Acceleration,
                                               Armor, Handling, FirePower (0..1)
    80 00 13 8d ...                            closing chunk
    ff ff ff ff "0100_JetVacStats"             end marker + object name

Because the data chunk for an object is followed by that object's end marker and
name, every data chunk can be attributed to exactly one object.
"""
import re
import struct
import sys

DATA_TAG = b"\x80\x00\x13\x91"
END_TAG = b"\xff\xff\xff\xff"
STAT_NAMES = ["TopSpeed", "Acceleration", "Armor", "Handling", "FirePower"]


def stats_objects(d):
    """Yield (name, offset_of_floats, (f0..f4)) for every *Stats object."""
    seen = set()
    for m in re.finditer(re.escape(DATA_TAG), d):
        fpos = m.start() + 0x20
        if fpos + 20 > len(d):
            continue
        end = d.find(END_TAG, m.start(), m.start() + 0x120)
        if end < 0:
            continue
        name = None
        for cand in re.finditer(rb"[ -~]{3,60}\x00", d[end:end + 0x60]):
            name = cand.group(0)[:-1].decode("latin1")
            break
        if not name or not name.endswith("Stats"):
            continue
        vals = struct.unpack_from(">5f", d, fpos)
        if not all(0.0 <= v <= 5.0 for v in vals):
            continue
        if name in seen:
            continue
        seen.add(name)
        yield name, fpos, vals


def main():
    if len(sys.argv) < 2:
        print("usage: pkz_stats_scan.py <file.pkz> [-v]")
        return
    verbose = "-v" in sys.argv
    d = open(sys.argv[1], "rb").read()
    rows = list(stats_objects(d))
    zero = 0
    if verbose:
        print("%-40s %-9s %s" % ("object", "offset", "  ".join("%-7s" % n for n in STAT_NAMES)))
        for name, off, vals in rows:
            if not any(vals):
                zero += 1
            print("%-40s 0x%06x %s" % (name, off, "  ".join("%-7.2f" % v for v in vals)))
    print("%d stats objects in %s%s" % (len(rows), sys.argv[1],
                                        (" (%d all-zero)" % zero) if verbose else ""))


if __name__ == "__main__":
    main()
