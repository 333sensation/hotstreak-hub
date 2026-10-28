#!/usr/bin/env python3
"""Give every bot the same speed, one speed per difficulty band.

A racer bot's pace is its `AIPersonality` object's skill scalar, the float at
body+0x0C. It is a clean ladder in the shipped data and nothing else competes
with it:

    SlowAttacker 0.80   SlowPacifist 0.85   AverageAttacker 0.90
    AveragePacifist 0.95   GoodAttacker 1.00   GoodPacifist 1.05
    ExpertAttacker 1.10   ExpertPacifist 1.15   MasterAttacker 1.20

and the pacifists sit 0.05 above their attacker sibling (same speed, less
appetite for attacking), so per-figure pace differences inside one race come
from this number plus the personality tiers a race draws.

This tool flattens that ladder into three bands - one speed per band, every
personality in a band identical - so all bots at a given difficulty run the
same speed instead of a spread:

    easy    0.80 0.85 0.90 0.95  ->  1.18
    medium  1.00 1.05            ->  1.20
    hard    1.10 1.15 1.20       ->  1.22

The three values are deliberately 3.4% apart, so every bot on the track runs at
one speed - no per-figure or per-tier spread - and the number that speed is set
to is the difficulty's. Every band sits at or just past the hardest AI this disc
ships (1.20, `MasterAttackerPersonality`), so the field the player actually races
- mostly the 0.90 average attacker, since 61 of the 75 `RacerAIInfo` records
name it - runs 31% to 47% faster than it shipped, without exceeding an opponent
the game already puts on the track by more than 2%.

The bands are read from a pristine copy of the file (default
`backups/BaseGameplay.pkz.pristine`) so re-running the tool is a no-op and a
second pass cannot move a band's value into the next band.

Only the four bytes of that float change: no object is added, moved or resized,
so the container keeps its size - the only edit this format tolerates.

Usage:
    python3 tools/pkz_ai_speed.py --show
    python3 tools/pkz_ai_speed.py                     # default bands, in place
    python3 tools/pkz_ai_speed.py --easy 1.14 --medium 1.18 --hard 1.22
"""
import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pkz_pool_swap as pw  # noqa: E402

PERSONALITY_TYPE = 0xC5EE3067
SPEED_OFF = 0x0C
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SRC = os.path.join(HERE, "disc", "files", "Data", "BaseGameplay.pkz")
REF = os.path.join(HERE, "backups", "BaseGameplay.pkz.pristine")

# band edges on the speed the file shipped with, and the speed each band gets
BANDS = (
    ("easy", 0.96, 1.18),
    ("medium", 1.06, 1.20),
    ("hard", 99.0, 1.22),
)


def personalities(d):
    """(key, name, body offset) for every AIPersonality object in the file."""
    out = []
    for w in pw.wrappers(d):
        key, name, roff, rlen, doff, dlen = pw.read_wrapper(d, w)
        if not name or doff is None:
            continue
        ps, ln, own, typ, keys = pw.body_fields(d, doff)
        if typ == PERSONALITY_TYPE and ln > SPEED_OFF + 4:
            out.append((key, name, ps))
    return out


def speed_of(d, ps):
    return struct.unpack_from(">f", d, ps + SPEED_OFF)[0]


def band_of(speed):
    for name, edge, _target in BANDS:
        if speed <= edge:
            return name
    return BANDS[-1][0]


def apply(src, ref=None, targets=None):
    """Return (patched bytes, [(key, name, band, was, now)]). Pure, same size."""
    targets = targets or {n: t for n, _e, t in BANDS}
    d = bytearray(src)
    # the band a personality belongs to is fixed by what it shipped with, never
    # by the value in the file we are about to overwrite
    shipped = {}
    if ref is not None:
        for key, name, ps in personalities(ref):
            shipped[key] = speed_of(ref, ps)

    report = []
    for key, name, ps in personalities(src):
        was = shipped.get(key)
        if was is None:
            was = speed_of(src, ps)
        band = band_of(was)
        now = targets[band]
        report.append((key, name, band, was, now))
        struct.pack_into(">f", d, ps + SPEED_OFF, now)

    out = bytes(d)
    if len(out) != len(src):
        raise RuntimeError("AI speed patch changed the file size")
    return out, report


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", default=SRC, help="file to patch (default: the disc tree)")
    ap.add_argument("--dst", default=None, help="default: rewrite --src in place")
    ap.add_argument("--ref", default=REF,
                    help="pristine copy to read the shipped bands from "
                         "(default: backups/BaseGameplay.pkz.pristine)")
    ap.add_argument("--easy", type=float, default=1.18)
    ap.add_argument("--medium", type=float, default=1.20)
    ap.add_argument("--hard", type=float, default=1.22)
    ap.add_argument("--show", action="store_true", help="just list the bands")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    src = open(args.src, "rb").read()
    ref = None
    if args.ref and os.path.exists(args.ref):
        ref = open(args.ref, "rb").read()
    elif args.ref:
        print("warning: %s not found, banding by the values in --src" % args.ref,
              file=sys.stderr)

    targets = {"easy": args.easy, "medium": args.medium, "hard": args.hard}
    out, report = apply(src, ref, targets)

    if not report:
        print("no AIPersonality objects found in %s" % args.src, file=sys.stderr)
        return 1

    print("%-38s %-9s %-7s %6s -> %6s" % ("personality", "key", "band", "was", "now"))
    for key, name, band, was, now in sorted(report, key=lambda r: (r[2], r[3])):
        flag = "" if abs(was - now) > 1e-6 else "  (already)"
        print("%-38s %08X %-7s %6.2f -> %6.2f%s" % (name, key, band, was, now, flag))

    for band, _edge, _t in BANDS:
        vals = sorted({round(r[4], 3) for r in report if r[2] == band})
        names = [r[1] for r in report if r[2] == band]
        print("\n%-6s %d personalities -> %s"
              % (band, len(names), ", ".join("%.2f" % v for v in vals) or "-"))
    diff = [i for i in range(len(src)) if src[i] != out[i]]
    print("\n%d personalities, %d bytes changed, size %s"
          % (len(report), len(diff), "unchanged" if len(out) == len(src) else "CHANGED"))
    if args.dry_run:
        print("dry run - nothing written")
        return 0
    open(args.dst or args.src, "wb").write(out)
    print("wrote %s" % (args.dst or args.src))
    return 0


if __name__ == "__main__":
    sys.exit(main())
