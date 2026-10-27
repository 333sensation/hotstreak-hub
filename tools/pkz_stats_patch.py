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
and no two figures share a spread.** Each figure gets one of nine **spiked**
archetypes picked from a CRC32 of its own name - shapes that max one stat and
starve another - jittered per figure, snapped to the 0.05 grid the disc uses and
normalised to a total of 3.0. The budget is the same three points it has always
been, so the roster stays fair; what the shapes change is how far apart the
figures sit, so a weakness is as plain as a strength. A variant (Dark /
Legendary / Eon's Elite) keeps its base figure's spread with 0.10 moved off its
weakest stat onto its strongest that still has room: same budget, sharper feel,
which is what the disc's own variant numbers do.

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
FLOOR = 1               # 0.05 is as low as a stat goes, so nothing is stuck

VEHICLE_RE = re.compile(r"(Plane|Car|Boat)_Stats$|^RentAWreck_|_Stats_Mod_", re.I)
MOD_SINGLE_RE = re.compile(r"_Stats_Mod_[12]$", re.I)
VARIANT_RE = re.compile(r"_(Dark|LG|EonsElite)$", re.I)
TOY_RE = re.compile(r"^(\d{4})_")
# what each toy-number range is, for the report only
RANGES = (("00", "Spyro's Adventure"), ("01", "Giants"), ("04", "Trap Team 04xx"),
          ("05", "minis"), ("10", "SWAP Force legs"), ("20", "SWAP Force body"),
          ("30", "Trap Team 30xx"), ("34", "SuperChargers"))

# Relative shapes, scaled to TOTAL afterwards. Each one sums to exactly 3.00
# already, so on a no-jitter draw the scaling is a no-op and the shape is what
# the disk gets. They are deliberately spiked - every archetype but the last
# maxes a stat and starves another, so the spread reads as an identity instead
# of five numbers hovering around the middle.
ARCHETYPES = {
    # TopSpeed, Acceleration, Armor, Handling, FirePower
    "rocket":      (1.00, 0.85, 0.10, 0.70, 0.35),   # flat out, no armour
    "sprinter":    (1.00, 1.00, 0.15, 0.50, 0.35),   # away from the line, nothing else
    "cornerer":    (0.45, 0.95, 0.15, 1.00, 0.45),   # launch and grip
    "drifter":     (0.75, 0.50, 0.10, 1.00, 0.65),   # turns, cannot take a hit
    "bruiser":     (0.25, 0.20, 1.00, 0.55, 1.00),   # armour and guns, no pace
    "juggernaut":  (0.15, 0.35, 1.00, 0.70, 0.80),   # the heavy
    "gunner":      (0.70, 0.30, 0.50, 0.50, 1.00),   # hits and runs
    "brawler":     (0.40, 0.45, 0.85, 0.30, 1.00),   # punches, cannot turn
    "all-rounder": (0.75, 0.65, 0.45, 0.60, 0.55),   # solid everywhere, best at nothing
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
    """Scale `weights` to `total` on the 0.05 grid, clamped to FLOOR-1.0.

    Whatever is left over after rounding is handed to the *biggest* stat with
    room and taken from the *smallest* one that has any, never spread evenly:
    that keeps a spiked shape spiked instead of sanding it towards the middle.
    """
    s = sum(weights)
    v = [int(round(w / s * total * STEP)) for w in weights]
    v = [min(STEP, max(FLOOR, x)) for x in v]
    delta = int(round(total * STEP)) - sum(v)
    guard = 0
    while delta and guard < 10_000:
        guard += 1
        if delta > 0:
            room = [i for i in range(5) if v[i] < STEP]
            if not room:
                break
            v[max(room, key=lambda i: (v[i], -i))] += 1
            delta -= 1
        else:
            low = [i for i in range(5) if v[i] > FLOOR]
            if not low:
                break
            v[min(low, key=lambda i: (v[i], i))] -= 1
            delta += 1
    return tuple(x / STEP for x in v)


def profile(base, total=TOTAL):
    """One distinct spread per figure, stable across runs."""
    rng = random.Random(zlib.crc32(base.lower().encode()))
    arch = ARCHETYPES[sorted(ARCHETYPES)[rng.randrange(len(ARCHETYPES))]]
    # multiplicative so the archetype's shape survives; wide enough that two
    # figures landing on the same archetype still land on different spreads
    jitter = [max(0.05, a * rng.uniform(0.70, 1.30)) for a in arch]
    return _grid(jitter, total)


def figure_spread(base, var):
    """The spread a character record wants before the roster-wide check."""
    v = profile(base)
    return sharpen(v, steps=2) if var else v


def _nudge(g, seen):
    """Walk one 0.05 step away from `g` onto a spread nobody holds yet.

    Pair order follows the shape: the smallest stat with room gives first, the
    largest that can take the step is tried first, so the move widens the spread
    instead of flattening it. False means every step from here is taken.
    """
    los = sorted((i for i in range(5) if g[i] > FLOOR), key=lambda i: (g[i], i))
    his = sorted((i for i in range(5) if g[i] < STEP), key=lambda i: (-g[i], i))
    for lo in los:
        for hi in his:
            if hi == lo:
                continue
            g[lo] -= 1
            g[hi] += 1
            if tuple(x / STEP for x in g) not in seen:
                return True
            g[lo] += 1
            g[hi] -= 1
    return False


def diversify(spreads):
    """Make a list of spreads unique, moving whole 0.05 steps of the same budget.

    A spiked archetype pins its best stat at 1.00 often enough that two figures
    can round onto the same five numbers, and "no two figures share a spread" is
    the point of the scheme, so a repeat is walked one step at a time - taken
    from the smallest stat with room, given to the largest one that has any -
    until it lands on a spread nobody else holds. Every move keeps the total at
    3.0 and widens the shape rather than flattening it. Spreads that are already
    unique (the common case) come back untouched, and the walk is bounded, so a
    figure that cannot be separated keeps its spread and the count in the report
    shows it.
    """
    seen = set()
    out = []
    for v in spreads:
        g = [int(round(x * STEP)) for x in v]
        for _ in range(24):
            if tuple(x / STEP for x in g) not in seen:
                break
            if not _nudge(g, seen):
                break
        spread = tuple(x / STEP for x in g)
        seen.add(spread)
        out.append(spread)
    return out


def sharpen(v, steps=2):
    """Move `steps` grid steps from the weakest stat to the strongest with room.

    A figure that already maxes one stat (Whirlwind's armor is 1.00) cannot take
    the boost there, so it goes to the next strongest, and a weakest stat that is
    already on the floor is skipped rather than pushed to zero - otherwise every
    variant of that figure would come out identical to its base.
    """
    g = [int(round(x * STEP)) for x in v]
    for _ in range(steps):
        lows = [i for i in range(5) if g[i] > FLOOR]
        if not lows:
            break
        lo = min(lows, key=lambda i: (g[i], i))
        room = [i for i in range(5) if i != lo and g[i] < STEP]
        if not room:
            break
        hi = max(room, key=lambda i: (g[i], -i))
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

    # character spreads are decided together, in file order, so that a repeat
    # can be nudged off another figure's numbers before anything is written.
    car_offs = [off for off, name in recs if not VEHICLE_RE.search(name)]
    car_named = {off: split_name(name) for off, name in recs
                 if not VEHICLE_RE.search(name)}
    car_new = dict(zip(car_offs, diversify([figure_spread(*car_named[o])
                                           for o in car_offs])))

    todo, kept = [], []
    for off, name in recs:
        old = struct.unpack_from(">5f", raw, off)
        if VEHICLE_RE.search(name):
            if not args.vehicles and any(old):
                kept.append((off, name, old))   # tuned vehicle numbers stay
                continue
            new = vehicle_profile(name)
        else:
            new = car_new[off]
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
