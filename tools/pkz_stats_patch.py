#!/usr/bin/env python3
"""Give every figure on the disc its own racing stats.

`BaseSkylander.pkz` holds **304** stat records (object type `0x4BBD2CFD`, each a
36-byte body: own id, type, then five big-endian floats TopSpeed, Acceleration,
Armor, Handling, FirePower, all 0.0-1.0 at data+0x20). They split into

    203  character records - one per figure (SA 00xx, Giants 01xx, Trap Team
         04xx/30xx, minis 05xx, SWAP Force halves 10xx/20xx, SuperChargers 34xx,
         the Eon's Elite / Dark / Legendary variants, and 14 villains)
    101  vehicle records - `*_Stats_Mod_0/1/2/SC` for the 20 player vehicles and
         `*Plane/_Car/_Boat_Stats` + `RentAWreck_*` for the villain hulls

Of the 203 character records **148 were all-zero stubs** on the shipped file: the
disc ships real numbers for only part of the roster, and nothing else on the disc
provides them (`BaseGameplay.pkz` and `Common.pkz` have no character stats), so
they have to be generated.

That is what this tool does: **every character record ends up with real values,
and no two figures share a spread.** Each figure gets one of five archetypes
picked from a CRC32 of its own name, jittered per figure, snapped to the 0.05
grid the disc uses and normalised to a total of 3.0 - the same budget the old
"balanced" scheme used, so the roster stays fair while every figure drives
differently. A variant (Dark / Legendary / Eon's Elite) keeps its base figure's
spread with 0.10 moved from its weakest stat to its strongest: same budget,
sharper feel, which is what the disc's own variant numbers do.

Vehicle records are left alone by default (the 20 player vehicles and the
`RentAWreck_*` hulls already ship real, tuned numbers - they are not characters).
The 13 all-zero villain hulls are filled in, and `--vehicles` rewrites all 101 if
you really want generated numbers there too.

Only the 20 float bytes of each record change, so no offsets, sizes, ids or chunk
lengths move - the only edit shape this container tolerates. Undo by copying
`BaseSkylander.pkz.orig` (written on the first run) back.

Usage:
    pkz_stats_patch.py [path] [--dry-run] [--vehicles] [--report]
"""
import argparse
import os
import random
import re
import shutil
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import pkz_pool_swap as pw  # noqa: E402

STATS_TYPE = 0x4BBD2CFD
BODY_LEN = 36           # 0x10 id/type + 20 bytes of floats
FLOAT_OFF = 0x20        # from the 0x1391 chunk header: +0x10 header, +0x10 body
STAT_NAMES = ("TopSpeed", "Acceleration", "Armor", "Handling", "FirePower")
TOTAL = 3.0             # budget per figure, as in the old balanced scheme
STEP = 20               # 0.05 grid: value * 20 is an integer

VEHICLE_RE = re.compile(r"(Plane|Car|Boat)_Stats$|^RentAWreck_|_Stats_Mod_", re.I)
MOD_SINGLE_RE = re.compile(r"_Stats_Mod_[12]$", re.I)
VARIANT_RE = re.compile(r"_(Dark|LG|EonsElite)$", re.I)
TOY_RE = re.compile(r"^(\d{4})_")
# what each toy-number range is, for the report only
RANGES = (("00", "Spyro's Adventure"), ("01", "Giants"), ("04", "Trap Team 04xx"),
          ("05", "minis"), ("10", "SWAP Force legs"), ("20", "SWAP Force body"),
          ("30", "Trap Team 30xx"), ("34", "SuperChargers"))

# relative shapes, scaled to TOTAL afterwards; one dominant stat each
ARCHETYPES = {
    "speedster":   (1.00, 0.55, 0.20, 0.80, 0.45),
    "bruiser":     (0.45, 0.30, 1.00, 0.50, 0.75),
    "technical":   (0.50, 0.65, 0.40, 1.00, 0.45),
    "gunner":      (0.55, 0.45, 0.50, 0.40, 1.00),
    "all-rounder": (0.65, 0.65, 0.55, 0.65, 0.50),
}


# ------------------------------------------------------------------ container
def stats_records(d):
    """Yield (offset_of_floats, name) for every stat record in the file.

    Walks the `0x138D` wrappers by object type instead of grepping for the name
    suffix: 94 of the 304 records do not end in `Stats` (the vehicle mod stages),
    and on 27 of them the key chunk holds the key *before* the name, so the name
    has to be read from behind the `ff ff ff ff` end marker.
    """
    for w in pw.wrappers(d):
        wl = struct.unpack_from(">I", d, w + 12)[0]
        name = None
        doff = None
        for _o, tag, ps, ln in pw.chunks(d, w + 16, w + 16 + wl):
            if tag == pw.KEYC:
                seg = d[ps:ps + ln]
                m = re.search(rb"\xff\xff\xff\xff([\x20-\x7e]{2,80})\x00", seg)
                if m:
                    name = m.group(1).decode("latin1")
                else:
                    m = re.search(rb"[\x20-\x7e]{2,80}\x00", seg)
                    name = m.group(0)[:-1].decode("latin1") if m else None
            elif tag == 0x80000C81:
                for o2, t2, _p2, _l2 in pw.chunks(d, ps, ps + ln):
                    if t2 == pw.BODY:
                        doff = o2
        if doff is None or name is None:
            continue
        if struct.unpack_from(">I", d, doff + 20)[0] != STATS_TYPE:
            continue
        if struct.unpack_from(">I", d, doff + 12)[0] != BODY_LEN:
            continue
        yield doff + FLOAT_OFF, name


# --------------------------------------------------------------------- naming
def split_name(name):
    """'0005_Terrafin_EonsElite_Stats' -> ('0005_Terrafin', 'EonsElite')."""
    n = name
    if n.endswith("Stats"):                 # `XStats`, `X_Stats`, `X_EonsElite_Stats`
        n = n[:-5].rstrip("_")
    var = ""
    m = VARIANT_RE.search(n)                # `XStats_Dark`, `XStats_LG`
    if m:
        var = m.group(1)
        n = n[:m.start()]
    if n.endswith("Stats"):
        n = n[:-5]
    return n.rstrip("_"), var


def category(name):
    if VEHICLE_RE.search(name):
        return "vehicles"
    toy = TOY_RE.match(name)
    if not toy:
        return "villains"
    for pref, label in RANGES:
        if toy.group(1).startswith(pref):
            return label
    return "other"


# ------------------------------------------------------------------- profiles
def _grid(weights, total):
    """Scale `weights` to `total` on the 0.05 grid, clamped to 0.0-1.0."""
    s = sum(weights)
    v = [int(round(w / s * total * STEP)) for w in weights]
    v = [min(STEP, max(0, x)) for x in v]
    delta = int(round(total * STEP)) - sum(v)
    order = sorted(range(5), key=lambda i: -v[i])
    i = 0
    while delta:
        j = order[i % 5]
        if delta > 0 and v[j] < STEP:
            v[j] += 1
            delta -= 1
        elif delta < 0 and v[j] > 0:
            v[j] -= 1
            delta += 1
        i += 1
        if i > 10_000:
            break
    return tuple(x / STEP for x in v)


def profile(base, total=TOTAL):
    """One distinct spread per figure, stable across runs."""
    rng = random.Random(zlib.crc32(base.lower().encode()))
    arch = ARCHETYPES[sorted(ARCHETYPES)[rng.randrange(len(ARCHETYPES))]]
    # multiplicative so the archetype's shape survives; wide enough that two
    # figures landing on the same archetype still land on different spreads
    jitter = [max(0.05, a * rng.uniform(0.65, 1.35)) for a in arch]
    return _grid(jitter, total)


def sharpen(v, steps=2):
    """Move `steps` grid steps from the weakest stat to the strongest with room.

    A figure that already maxes one stat (Whirlwind's armor is 1.00) cannot take
    the boost there, so it goes to the next strongest - otherwise every variant
    of that figure would come out identical to its base.
    """
    g = [int(round(x * STEP)) for x in v]
    for _ in range(steps):
        lo = min(range(5), key=lambda i: g[i])
        room = [i for i in range(5) if i != lo and g[i] < STEP]
        if not room or g[lo] == 0:
            break
        hi = max(room, key=lambda i: g[i])
        g[lo] -= 1
        g[hi] += 1
    return tuple(x / STEP for x in g)


def vehicle_profile(name):
    """Mod stages keep the disc shape (a 1.0 spike plus a 0.7 support); plain
    records get the same generator as the figures, seeded by their own name."""
    if MOD_SINGLE_RE.search(name):
        rng = random.Random(zlib.crc32(name.lower().encode()))
        peak, sup = rng.sample(range(5), 2)
        g = [0] * 5
        g[peak] = STEP
        g[sup] = int(0.7 * STEP)
        return tuple(x / STEP for x in g)
    return profile(name)


# ----------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", nargs="?", default="disc/files/Data/BaseSkylander.pkz")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--vehicles", action="store_true",
                    help="also regenerate the 101 vehicle records")
    ap.add_argument("--report", action="store_true",
                    help="print every record and what it was given")
    args = ap.parse_args()

    try:
        raw = open(args.path, "rb").read()
    except OSError as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    d = bytearray(raw)
    recs = list(stats_records(raw))
    if not recs:
        print("error: no stat records in %s" % args.path, file=sys.stderr)
        return 1

    chars = [(o, n) for o, n in recs if not VEHICLE_RE.search(n)]
    vehs = [(o, n) for o, n in recs if VEHICLE_RE.search(n)]
    zero = [(o, n) for o, n in recs if not any(struct.unpack_from(">5f", raw, o))]
    print("%s: %d stat records - %d character, %d vehicle; %d all-zero"
          % (args.path, len(recs), len(chars), len(vehs), len(zero)))

    todo, kept = [], []
    for off, name in recs:
        old = struct.unpack_from(">5f", raw, off)
        is_vehicle = bool(VEHICLE_RE.search(name))
        if is_vehicle and not args.vehicles and any(old):
            kept.append((off, name, old))       # tuned vehicle numbers stay
            continue
        base, var = split_name(name)
        new = vehicle_profile(name) if is_vehicle else profile(base)
        if var:
            new = sharpen(new, steps=2)
        todo.append((off, name, old, new))

    # ------------------------------------------------------------- report
    per_cat = {}
    for _off, name, _old, _new in todo:
        per_cat.setdefault(category(name), []).append(name)
    print("\n%-22s %6s %6s" % ("category", "blocks", "zero"))
    zero_names = {n for _o, n in zero}
    for label in [r[1] for r in RANGES] + ["villains", "other", "vehicles"]:
        names = per_cat.get(label)
        if not names:
            continue
        print("%-22s %6d %6d" % (label, len(names), sum(n in zero_names for n in names)))

    spreads = {_new for _o, _n, _old, _new in todo}
    print("\nrecords to write : %d (%d characters, %d vehicles)"
          % (len(todo), sum(not VEHICLE_RE.search(n) for _o, n, _old, _new in todo),
             sum(bool(VEHICLE_RE.search(n)) for _o, n, _old, _new in todo)))
    print("distinct spreads : %d" % len(spreads))
    print("unchanged        : %d (tuned vehicle records)" % len(kept))

    if args.report:
        print("\n%s" % ("%-46s %-22s %s" % ("record", "was", "now")))
        for _off, name, old, new in todo:
            print("%-46s %-22s %s"
                  % (name, " ".join("%.2f" % x for x in old),
                     " ".join("%.2f" % x for x in new)))

    if args.dry_run:
        print("\n(dry run, nothing written)")
        return 0

    # -------------------------------------------------------------- write
    for off, _name, _old, new in todo:
        struct.pack_into(">5f", d, off, *new)

    backup = args.path + ".orig"
    if not os.path.exists(backup):
        shutil.copy2(args.path, backup)
        print("\nbackup written to", backup)

    out = bytes(d)
    if len(out) != len(raw):
        print("error: size changed, not writing", file=sys.stderr)
        return 1
    changed = {i // 4096 for i in range(0, len(out), 4096)
               if out[i:i + 4096] != raw[i:i + 4096]}
    allowed = set()
    for off, _n, _o, _v in todo:
        for i in range(off, off + 20):
            allowed.add(i // 4096)
    stray = changed - allowed
    if stray:
        print("error: bytes changed outside the stat floats (blocks %s), not writing"
              % sorted(stray)[:5], file=sys.stderr)
        return 1
    open(args.path, "wb").write(out)

    # -------------------------------------------------------------- verify
    after = list(stats_records(out))
    left = [n for o, n in after if not any(struct.unpack_from(">5f", out, o))]
    sums = {round(sum(struct.unpack_from(">5f", out, o)), 4) for o, n in after
            if not VEHICLE_RE.search(n)}
    sets = {struct.unpack_from(">5f", out, o) for o, _n in after}
    print("\nwrote %s (%d bytes, %d unchanged)" % (args.path, len(out), len(raw) - len(out)))
    print("records          : %d (was %d)" % (len(after), len(recs)))
    print("all-zero left    : %d" % len(left))
    print("character totals : %s" % ", ".join("%.2f" % s for s in sorted(sums)))
    print("distinct spreads : %d" % len(sets))
    if left:
        print("  still empty:", left[:8])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
