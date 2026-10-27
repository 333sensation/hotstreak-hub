#!/usr/bin/env python3
"""Give every figure on the **3DS** build its own racing stats.

The same mod as `pkz_stats_patch.py`, applied to the 3DS romfs instead of the Wii
disc. The scheme, the archetypes, the 3.0 budget, the 0.05 grid and the
"no two figures share a spread" pass are all imported from that tool, so a figure
gets *the same five numbers on both builds* - the seeds are the figure names and
those are identical:

    Wii  `0000_Whirlwind_EonsElite_Stats`  0.80 0.60 1.00 0.60 0.50  (shipped)
    3DS  `0000_Whirlwind_EonsElite_Stats`  the same shipped numbers

What differs is only the container (see `pkz_3ds.py`): the 3DS file is a
little-endian roceGS stream inside a zlib stream, and the stat body is the same
36 bytes with the five floats at `+0x20` from the data chunk - but little-endian,
where the Wii build is big-endian. The type word stays big-endian on both
(`4BBD2CFD`).

Writing it back keeps the file the **same size**, which is the discipline this
project uses everywhere: the patched stream is re-deflated, the header's
compressed-size field is updated, and the tail is padded with the `0xDA` fill the
original used. A re-compressed stream that does not fit is an error rather than a
silently different file, and a `.orig` backup is written once on the first run.

Installing the result on a 3DS: leave the romfs alone and drop the patched file
in Luma's layeredfs folder, which needs no repack -

    luma/titles/0004000000165E00/romfs/Data/BaseSkylander.pkz

Usage:
    pkz_3ds_stats.py <BaseSkylander.pkz> [--out FILE] [--dry-run] [--report]
                     [--compare <wii BaseSkylander.pkz>]
"""
import argparse
import os
import re
import shutil
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pkz_3ds as P3                     # noqa: E402
import pkz_stats_patch as PS             # noqa: E402

DATA_TAG = b"\x91\x13\x00\x80"           # 0x80001391, the object's data chunk
STATS_TYPE = PS.STATS_TYPE               # 0x4BBD2CFD, same on both builds
BODY_LEN = PS.BODY_LEN                   # 36
FLOATS_AT = 0x20                         # from the data chunk: +0x10 header +0x10 body
FLOATS = 5 * 4
FILL = 0xDA                              # what the original pads the tail with
NAME_RE = re.compile(rb"[ -~]{2,80}")


def stats_records(inner):
    """(offset_of_floats, name, five floats) for every stat record, in file order.

    The name is not in the body: it follows it, behind the object's end marker,
    the same way it does on the Wii build - which is also why the name is searched
    for rather than indexed, and why a record whose name cannot be read is
    reported instead of guessed at.
    """
    out = []
    for m in re.finditer(re.escape(DATA_TAG), inner):
        o = m.start()
        if o + FLOATS_AT + FLOATS > len(inner):
            continue
        ln = struct.unpack_from("<I", inner, o + 8)[0]
        typ = struct.unpack_from("<I", inner, o + 20)[0]
        if typ != STATS_TYPE or ln != BODY_LEN:
            continue
        end = o + 12 + ln
        name = None
        # the name sits behind the payload, and a variant keeps its suffix after
        # the word (3413_DriverJetVacStats_LG, 3412_NitroStats_Dark), so match on
        # "Stat" anywhere rather than on the ending
        for cand in NAME_RE.finditer(inner, end, end + 0x60):
            text = cand.group(0).decode("latin1")
            if "Stat" in text:
                name = text
                break
        if name is None:
            # two records on this build ship no name of their own - the run that
            # follows belongs to the next object - so they are seeded from their
            # own id instead of borrowing a neighbour's name
            name = "?%08X" % struct.unpack_from("<I", inner, o + 16)[0]
        vals = struct.unpack_from("<5f", inner, o + FLOATS_AT)
        out.append((o + FLOATS_AT, name, vals))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path")
    ap.add_argument("--out", help="write here (default: <path>.patched)")
    ap.add_argument("--in-place", action="store_true",
                    help="overwrite the input (a .orig backup is kept)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", action="store_true", help="print every record")
    ap.add_argument("--compare", metavar="WII_PKZ",
                    help="compare against a patched Wii BaseSkylander.pkz")
    args = ap.parse_args()

    raw = open(args.path, "rb").read()
    kind, sections, parts = P3.load(args.path)
    if kind != "zlib" or len(sections) != 1:
        print("error: %s is not a single-package 3DS container (%s, %d packages)"
              % (args.path, kind, len(sections)), file=sys.stderr)
        return 1
    inner = bytearray(sections[0])
    off, unc = P3.header(raw)
    print("%s: %d bytes, %d in one package (0x%X)" % (args.path, len(raw), len(inner), off))

    recs = stats_records(inner)
    if not recs:
        print("error: no stat records found", file=sys.stderr)
        return 1
    unnamed = [n for _o, n, _v in recs if n.startswith("?")]
    chars = [(o, n) for o, n, _v in recs if not PS.VEHICLE_RE.search(n)]
    vehs = [(o, n) for o, n, _v in recs if PS.VEHICLE_RE.search(n)]
    zero = [n for _o, n, v in recs if not any(v)]
    print("records          : %d (%d character, %d vehicle), %d all-zero, %d unnamed"
          % (len(recs), len(chars), len(vehs), len(zero), len(unnamed)))
    if unnamed:
        print("  unnamed:", unnamed[:6])

    # character spreads are decided together so a repeat can be nudged off
    # another figure's numbers before anything is written - same as the Wii tool
    named = {o: PS.split_name(n) for o, n, _v in recs}
    char_new = dict(zip([o for o, _n, _v in recs if not PS.VEHICLE_RE.search(_n)],
                        PS.diversify([PS.figure_spread(*named[o])
                                      for o, n, _v in recs
                                      if not PS.VEHICLE_RE.search(n)])))

    todo, kept = [], []
    for o, name, old in recs:
        if PS.VEHICLE_RE.search(name):
            if any(old):
                kept.append((o, name, old))     # tuned vehicle numbers stay
                continue
            new = PS.vehicle_profile(name)
        else:
            new = char_new[o]
        todo.append((o, name, old, new))

    spreads = {tuple(round(x, 4) for x in new) for _o, _n, _old, new in todo}
    print("to write         : %d records, %d distinct spreads, %d kept"
          % (len(todo), len(spreads), len(kept)))
    if args.report:
        for _o, name, old, new in todo:
            print("  %-46s %-22s %s"
                  % (name, " ".join("%.2f" % x for x in old),
                     " ".join("%.2f" % x for x in new)))

    if args.compare:
        wii = open(args.compare, "rb").read()
        # the Wii records are big-endian and only give (offset, name)
        theirs = {n: struct.unpack_from(">5f", wii, o) for o, n in PS.stats_records(wii)}
        same = diff = 0
        for _o, name, _old, new in todo:
            if name in theirs:
                if all(abs(a - b) < 1e-6 for a, b in zip(new, theirs[name])):
                    same += 1
                else:
                    diff += 1
        print("vs %s: %d figures identical, %d different, %d not on the Wii build"
              % (os.path.basename(args.compare), same, diff,
                 sum(1 for _o, n, _old, _new in todo if n not in theirs)))

    if args.dry_run:
        print("(dry run, nothing written)")
        return 0

    for o, _name, _old, new in todo:
        struct.pack_into("<5f", inner, o, *new)

    stream = zlib.compress(bytes(inner), 9)
    room = len(raw) - off
    if len(stream) > room:
        print("error: re-compressed stream is %d bytes, only %d fit"
              % (len(stream), room), file=sys.stderr)
        return 1
    header = bytearray(raw[:off])
    struct.pack_into("<I", header, 0x0C, len(inner))     # uncompressed size
    struct.pack_into("<I", header, 0x10, len(stream))    # compressed size
    out = bytes(header) + stream + bytes([FILL]) * (room - len(stream))

    if args.in_place:
        dst = args.path
        if not os.path.exists(dst + ".orig"):
            shutil.copy2(dst, dst + ".orig")
            print("backup written to %s.orig" % dst)
    else:
        dst = args.out or (args.path + ".patched")
        os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    open(dst, "wb").write(out)

    # ---------------------------------------------------------- verify
    kind2, sections2, _ = P3.load(dst)
    recs2 = stats_records(bytearray(sections2[0]))
    sums = {round(sum(v), 4) for _o, n, v in recs2 if not PS.VEHICLE_RE.search(n)}
    grid = all(0.05 - 1e-6 <= x <= 1.0 + 1e-6 and abs(x * 20 - round(x * 20)) < 1e-6
               for _o, _n, v in recs2 for x in v)
    print("\nwrote %s (%d bytes, was %d, %s)"
          % (dst, len(out), len(raw), "same size" if len(out) == len(raw) else "SIZE CHANGED"))
    print("stream           : %d bytes in, %d out, %d of %d used"
          % (unc, len(inner), len(stream), room))
    print("records          : %d (was %d)" % (len(recs2), len(recs)))
    print("character totals : %s" % ", ".join("%.2f" % s for s in sorted(sums)))
    print("distinct spreads : %d" % len({tuple(round(x, 4) for x in v)
                                        for _o, _n, v in recs2}))
    print("on the 0.05 grid : %s" % grid)
    if len(out) != len(raw) or grid is None or len(sums) > 1:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
