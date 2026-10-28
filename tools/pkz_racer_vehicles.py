#!/usr/bin/env python3
"""Keep every racer on the vehicle it shipped with - no borrowed hulls.

A `RacerAIInfo` is a (character, AI template, vehicle) triple, and the engine
validates the pair: `gamelogic.rso` carries `IsDriverVehicleCorrectPair`,
`GetVillainVehicle`, `GetVillainVehicleStat`, `ClearDriverVehicles` and
`IsOnlyVehicleRentAWreck`. A record whose figure does not belong to the hull it
names comes out on the fallback vehicle - the rent-a-wreck - which is why a
recast villain on a borrowed hull reads as "every bot drives the scrap".

So the rule here is the disc's own: a record keeps the figure and the hull it
shipped with, or neither. Two consequences:

* the 12 villain records and the 3 `Greeble*Info` dummies are **not** recast -
  their figure and their hull are one pair, so the mod leaves all three fields
  (character, template, vehicle) exactly as the disc has them;
* the 60 `Driver*_AIInfo` records are recast freely, because they keep their own
  hull (`DriverPeacock` still drives the Peacock vehicle, whoever is under the
  helmet), which is the state the mod has always run in.

This tool enforces that: it copies the shipped character, template and vehicle
back onto every non-driver record from a reference file, restores a driver's
shipped vehicle if it was changed, and rewrites the matching ids in each
wrapper's `0x139C` table. Same size - only those three 4-byte refs and their
mirrors move.

Usage:
    python3 tools/pkz_racer_vehicles.py --show
    python3 tools/pkz_racer_vehicles.py [--src ...] [--ref ...] [--dry-run]
"""
import argparse
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pkz_pool_swap as pw  # noqa: E402

INFO_TYPE = 0x45BA524C
DRIVER_RE = re.compile(r"^Driver.+_(Air|Land|Sea)_AIInfo$")
OFF_CHAR, OFF_TPL, OFF_VEH = 0x0C, 0x10, 0x14
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(HERE, "disc", "files", "Data", "BaseGameplay.pkz")
REF = os.path.join(HERE, "backups", "BaseGameplay.pkz.pristine")


ACTION_PACKS = ("EnemyAIList_Air_ActionPack", "EnemyAIList_Land_ActionPack",
                "EnemyAIList_Land_ActionPack_SheepHerder", "EnemyAIList_Sea_ActionPack")
GREEBLE_RE = re.compile(r"^Greeble\w+Info$")


def scan(d):
    """{name: (key, body offset, ref offset, ref len)} for every racer info."""
    out = {}
    for w in pw.wrappers(d):
        key, name, roff, rlen, doff, dlen = pw.read_wrapper(d, w)
        if not name or doff is None:
            continue
        ps, ln, own, typ, _keys = pw.body_fields(d, doff)
        if typ == INFO_TYPE:
            out[name] = (key, ps, roff, rlen)
    return out


def fixed_records(d):
    """Names of the villain + Greeble records: figure and hull are one pair.

    Found from the disc's own action-pack enemy pools rather than from the name
    alone - a few wrappers read with a mangled name, and those are drivers.
    """
    keys, pools = {}, {}
    for w in pw.wrappers(d):
        key, name, roff, rlen, doff, dlen = pw.read_wrapper(d, w)
        if not name or doff is None:
            continue
        ps, ln, own, typ, ks = pw.body_fields(d, doff)
        keys[key] = name
        if typ == pw.LIST_TYPE and name in ACTION_PACKS:
            pools[name] = ks
    out = set()
    for name, ks in pools.items():
        for k in ks:
            n = keys.get(k)
            if n and n not in ACTION_PACKS:
                out.add(n)
    out.update(n for n in keys.values() if GREEBLE_RE.match(n))
    return out


def triple(d, ps):
    return struct.unpack_from(">III", d, ps + OFF_CHAR)


def drop_greebles(src, ref):
    """Replace the Greeble dummy entries in the enemy pools with real villains.

    The shippped action-pack pools field `GreeblePlaneInfo`/`GreebleCarInfo`/
    `GreebleBoatInfo` - the test dummies, which sit on the rent-a-wreck - so a
    third of that grid is scrap by design. One record is one racer, so each
    Greeble entry is re-pointed at a villain record the same pool already
    references (the shipped pools list the Greeble twice, and a pool may list an
    object more than once). No length changes; the wrapper's `0x139C` table gets
    the same key so it still mirrors the records.
    """
    d = bytearray(src)
    keys, pools, refs = {}, {}, {}
    for w in pw.wrappers(src):
        key, name, roff, rlen, doff, dlen = pw.read_wrapper(src, w)
        if not name or doff is None:
            continue
        ps, ln, own, typ, ks = pw.body_fields(src, doff)
        keys[key] = name
        if typ == pw.LIST_TYPE and name in ACTION_PACKS + tuple(
                p.replace("_ActionPack", "_StarterPack") for p in ACTION_PACKS):
            pools[name] = (ps, ln, ks)
            refs[name] = (roff, rlen)

    greebles = {k for k, n in keys.items() if GREEBLE_RE.match(n)}
    changed = []
    for name, (ps, ln, ks) in pools.items():
        if not (set(ks) & greebles):
            continue
        villains = [k for k in ks if k not in greebles and k in keys
                    and not GREEBLE_RE.match(keys[k]) and "PersonalityList" not in keys[k]]
        if not villains:
            continue
        roff, rlen = refs[name]
        for i, k in enumerate(ks):
            if k not in greebles:
                continue
            new = villains[i % len(villains)]
            struct.pack_into(">I", d, ps + 0x18 + i * 16 + 4, new)
            changed.append((name, i, k, new))
        # mirror it in the id table (position is not meaningful, the set is)
        for j in range(roff, roff + rlen, 8):
            v = struct.unpack_from(">I", src, j + 4)[0]
            if v in greebles:
                struct.pack_into(">I", d, j + 4, villains[0])
    return bytes(d), changed


def apply(src, ref):
    """Return (patched bytes, [(name, kind, was, now)]) putting shipped pairs back."""
    d = bytearray(src)
    have = scan(src)
    want = scan(ref)
    fixed = fixed_records(ref)
    report = []

    for name, (_k, ps, roff, rlen) in have.items():
        if name not in want:
            continue
        ref_ps = want[name][1]
        old = triple(src, ps)
        new = triple(ref, ref_ps)
        if name in fixed:
            # the figure and the hull shipped together, so both go back
            target = new
        elif DRIVER_RE.match(name):
            # a driver keeps the figure the roster gave it and its own hull
            target = (old[0], new[1], new[2])
        else:
            continue
        if old == target:
            continue
        report.append((name, "shipped pair" if name in fixed else "driver", old, target))
        struct.pack_into(">III", d, ps + OFF_CHAR, *target)
        for j in range(roff, roff + rlen, 8):
            v = struct.unpack_from(">I", d, j + 4)[0]
            for a, b in ((old[0], target[0]), (old[1], target[1]), (old[2], target[2])):
                if v == a and a != b:
                    struct.pack_into(">I", d, j + 4, b)
                    break

    out = bytes(d)
    if len(out) != len(src):
        raise RuntimeError("pair patch changed the file size")
    return out, report


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--dst", default=None, help="default: rewrite --src in place")
    ap.add_argument("--ref", default=REF, help="file holding the shipped pairs")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    src = open(args.src, "rb").read()
    if not os.path.exists(args.ref):
        print("error: %s not found - the shipped pairs are read from it" % args.ref,
              file=sys.stderr)
        return 1
    ref = open(args.ref, "rb").read()

    if args.show:
        fixed = fixed_records(ref)
        have = scan(src)
        print("racer records: %d drivers (recast, own hull) + %d villain/Greeble "
              "(figure and hull are one pair)" % (len(have) - len(fixed), len(fixed)))
        print()

    out, report = apply(src, ref)
    if not report:
        print("every record already matches its shipped pair")
    out, swapped = drop_greebles(out, ref)
    for pool, i, was, now in swapped:
        print("%-44s [%d] %-18s -> real villain" % (pool, i, "Greeble dummy"))
    if swapped:
        print("%d Greeble dummy entries replaced with real villain records" % len(swapped))

    for name, kind, was, now in report:
        print("%-34s %-12s %08X %08X %08X -> %08X %08X %08X"
              % (name, kind, was[0], was[1], was[2], now[0], now[1], now[2]))

    if not report and not swapped:
        print("nothing to do")
        return 0

    # verify: pools still mirror their id tables, and no Greeble is fielded
    bad = 0
    for w in pw.wrappers(out):
        key, name, roff, rlen, doff, dlen = pw.read_wrapper(out, w)
        if not name or doff is None:
            continue
        ps, ln, own, typ, ks = pw.body_fields(out, doff)
        if typ != pw.LIST_TYPE:
            continue
        rl = [struct.unpack_from(">I", out, j + 4)[0] for j in range(roff, roff + rlen, 8)]
        if set(rl) != set(ks):
            print("  MISMATCH %s" % name)
            bad += 1
    print("every RacerAIList still mirrors its id table:", not bad)

    diff = [i for i in range(len(src)) if src[i] != out[i]]
    print("\n%d records restored, %d pool entries re-pointed, %d bytes changed, size %s"
          % (len(report), len(swapped), len(diff),
             "unchanged" if len(out) == len(src) else "CHANGED"))
    if args.dry_run or bad:
        print("dry run - nothing written" if not bad else "error: verification failed")
        return 0 if not bad else 1
    open(args.dst or args.src, "wb").write(out)
    print("wrote %s" % (args.dst or args.src))
    return 0


if __name__ == "__main__":
    sys.exit(main())
