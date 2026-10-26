#!/usr/bin/env python3
"""Recast the bot infos as a random cast of playable figures.

Adding new objects to `BaseGameplay.pkz` makes the game hang on load, but
rewriting the payload of an *existing* `RacerAIInfo` in place is exactly what the
stats patch and the villain swap already do, and it keeps the file byte-for-byte
the same size. So instead of stuffing every figure into the container, this tool
re-points the 56 driver infos plus the 15 villain infos - all already referenced
by the enemy pools - at a random cast of the playable figures.

A recast villain info is also put on that terrain's `RentAWreck_*` (the vehicle
the shipped Greeble bots drive). That is the only `(character, AI template,
vehicle)` combination proven to work on every terrain: leaving a villain info on
its own hull (`GoldenQueen_Boat`, `DrKrankcase_Car`, ...) while swapping the
character under it is what made a fresh image come up with a corrupt racer.

Run it with a different `--seed` for every image and each race fields a
different random cast of characters.
"""
import argparse
import random
import re
import struct
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import pkz_pool_swap as pw

INFO_TYPE = 0x45BA524C
CATALOG_TYPE = 0x5DA30426
STATS_TYPE = 0x4BBD2CFD
VEHICLE_RE = re.compile(r"(Plane|Car|Boat)_Stats$|^RentAWreck_", re.I)
# stats objects that belong to a vehicle part rather than to a figure
PART_RE = re.compile(r"_(Body|Legs|Arms|Head|Top|Bottom|Wheels?|Wings?|Turret|Weapon"
                     r"|Chassis|Hull|Frame|Bumper|Spoiler|Exhaust)$", re.I)
RENTAL = {"air": "RentAWreck_Plane", "land": "RentAWreck_Car", "sea": "RentAWreck_Boat"}
TERRAIN_POOLS = (
    ("EnemyAIList_Air_ActionPack", "air"),
    ("EnemyAIList_Land_ActionPack", "land"),
    ("EnemyAIList_Sea_ActionPack", "sea"),
)


def figures(cat):
    """Playable figures: a catalogue object plus a stats object with that name."""
    char_id, stats = {}, set()
    for w in pw.wrappers(cat):
        key, name, roff, rlen, doff, dlen = pw.read_wrapper(cat, w)
        if not name or doff is None:
            continue
        typ = struct.unpack_from(">I", cat, doff + 20)[0]
        if typ == CATALOG_TYPE:
            char_id[name] = key
        elif typ == STATS_TYPE and not VEHICLE_RE.search(name):
            base = re.sub(r"_?Stats$", "", name)
            if not PART_RE.search(base):
                stats.add(base)
    return [(n, char_id[n]) for n in sorted(stats) if n in char_id]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="disc/files/Data/BaseGameplay.pkz")
    ap.add_argument("--catalog", default="disc/files/Data/BaseSkylander.pkz")
    ap.add_argument("--seed", type=int, default=None, help="default: random each run")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--must", default="",
                    help="comma separated names that must be in the cast, e.g. "
                         "Spyro,Whirlwind,Bash")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    d = bytearray(open(args.src, "rb").read())
    cat = open(args.catalog, "rb").read()

    pool_chars = figures(cat)

    infos, pools = {}, {}
    for w in pw.wrappers(d):
        key, name, roff, rlen, doff, dlen = pw.read_wrapper(d, w)
        if not name or doff is None:
            continue
        typ = struct.unpack_from(">I", d, doff + 20)[0]
        if typ == INFO_TYPE:
            infos[name] = (w, key, roff, rlen, doff, dlen)
        elif typ == pw.LIST_TYPE:
            ps, ln, own, t2, keys = pw.body_fields(d, doff)
            pools[name] = keys

    # the rental vehicle per terrain is whatever the Greeble infos already drive
    rental = {}
    for terrain, iname in (("air", "GreeblePlaneInfo"), ("land", "GreebleCarInfo"),
                           ("sea", "GreebleBoatInfo")):
        if iname in infos:
            rental[terrain] = struct.unpack_from(">I", d, infos[iname][4] + 16 + 20)[0]
    print("playable figures: %d, rentals: %s"
          % (len(pool_chars), {k: "%08X" % v for k, v in rental.items()}))
    if len(rental) != 3:
        print("error: greeble templates not found", file=sys.stderr)
        return 1

    # which villain infos belong to which terrain (from the shipped villain pools)
    per_terrain = {}
    for pname, terrain in TERRAIN_POOLS:
        for k in pools.get(pname, []):
            for iname, (w, key, roff, rlen, doff, dlen) in infos.items():
                if key == k and "_AIInfo" not in iname:
                    per_terrain.setdefault(terrain, [])
                    if iname not in per_terrain[terrain]:
                        per_terrain[terrain].append(iname)
    print("villain infos per terrain:",
          {t: len(v) for t, v in per_terrain.items()})

    changes = 0

    def recast(iname, fig, fig_key, new_veh, label):
        """Point one AI info at `fig`, keeping template and (usually) vehicle."""
        nonlocal changes
        w, key, roff, rlen, doff, dlen = infos[iname]
        body = doff + 16
        old_char = struct.unpack_from(">I", d, body + 12)[0]
        old_veh = struct.unpack_from(">I", d, body + 20)[0]
        veh = old_veh if new_veh is None else new_veh
        print("   %-12s %-30s char %08X -> %08X  veh %08X%s"
              % (label, iname, old_char, fig_key, veh,
                 "" if veh == old_veh else " (rental)"))
        if args.dry_run:
            return
        struct.pack_into(">I", d, body + 12, fig_key)
        struct.pack_into(">I", d, body + 20, veh)
        for j in range(roff, roff + rlen, 8):
            v = struct.unpack_from(">I", d, j + 4)[0]
            if v == old_char:
                struct.pack_into(">I", d, j + 4, fig_key)
            elif v == old_veh:
                struct.pack_into(">I", d, j + 4, veh)
        changes += 1

    # the 60 driver infos carry the racer AI template (`33D91E1A`) and are the
    # records a race actually fields as opponents; they keep their own vehicle
    DRIVER_RE = re.compile(r"^Driver(.+)_(Air|Land|Sea)_AIInfo$")
    drivers = [(n, m.group(2).lower()) for n in infos
               for m in [DRIVER_RE.match(n)] if m]
    remaining = list(pool_chars)
    rng.shuffle(remaining)
    must = [m.strip().lower() for m in args.must.split(",") if m.strip()]
    if must:
        forced = [p for p in remaining if any(m in p[0].lower() for m in must)]
        rest = [p for p in remaining if p not in forced]
        # the loops below pop() from the end, so the pinned figures go last
        remaining = rest + forced
        print("pinned to the front: %s" % ", ".join(p[0] for p in forced))
    print("\ndriver infos recast:")
    for iname, terrain in drivers:
        if not remaining:
            remaining = list(pool_chars)
            rng.shuffle(remaining)
        fig, fig_key = remaining.pop()
        recast(iname, fig, fig_key, None, terrain)

    # and the villain infos (which the pools also reference) get the same
    # treatment, on the terrain rental the Greeble bots are proven with
    print("\nvillain infos recast:")
    for terrain, names in per_terrain.items():
        for iname in names:
            if not remaining:
                remaining = list(pool_chars)
                rng.shuffle(remaining)
            fig, fig_key = remaining.pop()
            recast(iname, fig, fig_key, rental[terrain], terrain)

    if args.dry_run:
        print("\ndry run - nothing written")
        return 0

    out = bytes(d)
    orig = open(args.src, "rb").read()
    if len(out) != len(orig):
        print("error: size changed", file=sys.stderr)
        return 1
    diff = sum(1 for a, b in zip(out, orig) if a != b)
    print("\ninfos rewritten: %d, bytes changed: %d, size unchanged: %s"
          % (changes, diff, len(out) == len(orig)))
    open(args.src, "wb").write(out)
    print("wrote %s (seed %s)" % (args.src, args.seed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
