#!/usr/bin/env python3
"""Put villains into the driver AI pools by swapping keys in place.

The four driver pools (`EnemyAIList_Air/Land/Land_SheepHerder/Sea_StarterPack`)
each hold a personality record plus 20 `Driver*_AIInfo` keys. Growing a pool
stops the game from loading (see FINDINGS.md), so this tool never changes a
length: it only rewrites the 4-byte key of an existing record and the matching
entry of the object's `0x139C` reference table. File size, chunk lengths and
record counts stay identical, which keeps the risk to "does the engine accept a
villain key here" instead of "is my chunk arithmetic right".

Object layout, verified against the file (NOT the shifted binding the old tool
used, where a name belonged to the *next* wrapper):

    0x138D wrapper
        0x138E   key(u32) + 0x15 0x0F + "\\0" + zero-padded name
        0x0C80   marker
        0x139C   ref table, 21 entries of (u32 0x15, u32 key) for a driver pool
        0x0C81   -> 0x0C80 marker + 0x1391 data (the RacerAIList body)

Body: 24-byte header, then 16-byte records (word, key, owner, 91284605), the
last record truncated to (word, key). The 0x139C table holds the *distinct*
keys, so a pool can list one object several times.

It also spreads duplicate records: each shipped action-pack pool lists its
single Greeble object three times, and one object is one racer, so the excess
records are re-pointed at other keys the pool already references.

`--restore` is the way back: it writes the reference file's keys into the same
record positions (and their `0x139C` entries), so the pools hold the disc's own
driver records again. `setup.py` runs it on every build, because a race fields
the pool's records - with villains left at the end of a pool the whole field
comes out villain, whatever figures the driver records were recast to.

Usage: pkz_pool_swap.py [--src ...] [--dst ...] [--slots N] [--dry-run]
       pkz_pool_swap.py --restore [--ref backups/BaseGameplay.pkz.pristine]
"""
import argparse
import os
import re
import struct
import sys

WRAP = 0x8000138D
KEYC = 0x8000138E
REFC = 0x8000139C
BODY = 0x80001391
LIST_TYPE = 0xCAFB9B03
INFO_TYPE = 0x45BA524C
SHARED = 0x91284605

# the four pools that hold the 20 SuperCharger drivers, and the terrain each
# one races on (the engine picks bots per terrain, so a sea villain has no
# business in a land race)
POOLS = (
    ("EnemyAIList_Air_StarterPack", "air"),
    ("EnemyAIList_Land_StarterPack", "land"),
    ("EnemyAIList_Land_StarterPack_SheepHerder", "land"),
    ("EnemyAIList_Sea_StarterPack", "sea"),
)
# the shipped villain pools are the record of which villain belongs to which
# terrain; they are read from the file instead of being hardcoded
TERRAIN_POOLS = (
    ("EnemyAIList_Air_ActionPack", "air"),
    ("EnemyAIList_Land_ActionPack", "land"),
    ("EnemyAIList_Sea_ActionPack", "sea"),
)
DRIVER_RE = re.compile(r"^Driver(.+)_(Land|Air|Sea)_AIInfo$")


def chunks(d, start, end):
    o = start
    while o + 16 <= end:
        tag = struct.unpack_from(">I", d, o)[0]
        if tag >> 16 != 0x8000:
            return
        ln = struct.unpack_from(">I", d, o + 12)[0]
        yield o, tag, o + 16, ln
        o += 16 + ln


def wrappers(d, start=16, end=None):
    """Every 0x138D wrapper, descending through chunk-stream payloads."""
    if end is None:
        end = len(d)
    for o, tag, ps, ln in chunks(d, start, end):
        if tag == WRAP:
            yield o
        elif ln >= 16 and struct.unpack_from(">I", d, ps)[0] >> 16 == 0x8000:
            for w in wrappers(d, ps, ps + ln):
                yield w


def read_wrapper(d, w):
    """Return (key, name, ref_off, ref_len, data_off, data_len)."""
    wl = struct.unpack_from(">I", d, w + 12)[0]
    key = name = None
    ref_off = ref_len = data_off = data_len = None
    for o, tag, ps, ln in chunks(d, w + 16, w + 16 + wl):
        if tag == KEYC:
            seg = d[ps:ps + ln]
            key = struct.unpack_from(">I", seg, 0)[0]
            m = re.search(rb"[ -~]{2,80}\x00", seg)
            name = m.group(0)[:-1].decode("latin1") if m else None
        elif tag == REFC:
            ref_off, ref_len = ps, ln
        elif tag == 0x80000C81:
            for o2, t2, p2, l2 in chunks(d, ps, ps + ln):
                if t2 == BODY:
                    data_off, data_len = o2, l2
    return key, name, ref_off, ref_len, data_off, data_len


def body_fields(d, data_off):
    ps = data_off + 16
    ln = struct.unpack_from(">I", d, data_off + 12)[0]
    body = d[ps:ps + ln]
    own = struct.unpack_from(">I", body, 0)[0]
    type_id = struct.unpack_from(">I", body, 4)[0]
    # data_keys() in pkz_pool_grow counts one extra entry because the last
    # record is truncated
    n = (len(body) - 0x18 + 8) // 16 if (len(body) - 0x18 + 8) % 16 == 0 else 0
    keys = [struct.unpack_from(">I", body, 0x18 + i * 16 + 4)[0] for i in range(n)]
    return ps, ln, own, type_id, keys


def restore(src, ref):
    """Put the disc's own record keys back in the four driver pools.

    Only the record keys and their `0x139C` mirrors are rewritten - never a
    length, never a racer record - so the recast driver records (the random
    cast) and every fuel/hull reference stay exactly as they are.

    Returns (bytes, [(pool, records changed)]) or (None, []) when the result
    would not still mirror its tables, in which case nothing may be written.
    """
    want = {}
    for name, _terrain in POOLS:
        for w in wrappers(ref):
            key, rname, roff, rlen, doff, dlen = read_wrapper(ref, w)
            if rname == name and doff is not None:
                ps, ln, own, typ, keys = body_fields(ref, doff)
                want[name] = (keys, ref[ps + 0x18:ps + ln], ref[roff:roff + rlen])
                break

    d = bytearray(src)
    changed = []
    for w in wrappers(src):
        key, name, roff, rlen, doff, dlen = read_wrapper(src, w)
        if doff is None or name not in want:
            continue
        ps, ln, own, typ, keys = body_fields(src, doff)
        if typ != LIST_TYPE:
            continue
        ref_keys, ref_body, ref_table = want[name]
        if (len(ref_keys) != len(keys) or len(ref_body) != ln - 0x18
                or len(ref_table) != rlen):
            print("error: %s does not have the same layout as the reference"
                  % name, file=sys.stderr)
            return None, []
        # the record area and the 0x139C table, straight from the shipped file
        # (both files put the pool at the same offset - every edit here is in
        # place, so the layout never moved)
        d[ps + 0x18:ps + ln] = ref_body
        d[roff:roff + rlen] = ref_table
        if keys != ref_keys:
            changed.append((name, sum(1 for a, b in zip(keys, ref_keys) if a != b)))

    for w in wrappers(src):
        key, name, roff, rlen, doff, dlen = read_wrapper(src, w)
        if doff is None or name not in want:
            continue
        ps, ln, own, typ, keys = body_fields(d, doff)
        refs = [struct.unpack_from(">I", d, j + 4)[0]
                for j in range(roff, roff + rlen, 8)]
        if set(refs) != set(keys):
            print("error: %s would not mirror its ref table" % name,
                  file=sys.stderr)
            return None, []
    return bytes(d), changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="disc/files/Data/BaseGameplay.pkz")
    ap.add_argument("--dst", default=None, help="default: rewrite --src in place")
    ap.add_argument("--slots", type=int, default=8, help="driver records to replace per pool")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--restore", action="store_true",
                    help="put the shipped driver records back in the four pools "
                         "(undo the villain swap)")
    ap.add_argument("--ref", default="backups/BaseGameplay.pkz.pristine",
                    help="with --restore: the file holding the shipped pools")
    args = ap.parse_args()

    raw = open(args.src, "rb").read()
    d = bytearray(raw)
    print("source %s: %d bytes" % (args.src, len(raw)))

    if args.restore:
        if not os.path.exists(args.ref):
            print("error: no reference file at %s" % args.ref, file=sys.stderr)
            return 1
        out, changed = restore(raw, open(args.ref, "rb").read())
        if out is None:
            return 1
        for name, n in changed:
            print("  %-44s %d record%s back to the shipped key"
                  % (name, n, "" if n == 1 else "s"))
        if not changed:
            print("  pools already hold the shipped records")
        if len(out) != len(raw):
            print("error: size changed", file=sys.stderr)
            return 1
        print("\nbytes changed: %d" % sum(1 for a, b in zip(raw, out) if a != b))
        if args.dry_run:
            print("dry run - nothing written")
            return 0
        open(args.dst or args.src, "wb").write(out)
        print("wrote %s (size unchanged)" % (args.dst or args.src))
        return 0

    pool_rows, infos = {}, {}
    for w in wrappers(raw):
        key, name, roff, rlen, doff, dlen = read_wrapper(raw, w)
        if doff is None or not name:
            continue
        ps, ln, own, typ, keys = body_fields(raw, doff)
        if typ == LIST_TYPE:
            pool_rows[name] = (w, key, roff, rlen, ps, ln, keys)
        elif typ == INFO_TYPE:
            infos[name] = key

    drivers = {}
    for name, key in infos.items():
        m = DRIVER_RE.match(name)
        if m:
            drivers.setdefault(m.group(1), {})[m.group(2).lower()] = (key, name)
    villains = {k for n, k in infos.items()
                if "_AIInfo" not in n and n.endswith("Info")}
    by_terrain = {}
    for tpool, terrain in TERRAIN_POOLS:
        if tpool not in pool_rows:
            print("warning: terrain pool %s missing" % tpool, file=sys.stderr)
            continue
        for k in pool_rows[tpool][6]:
            if k in villains and k not in by_terrain.setdefault(terrain, []):
                by_terrain[terrain].append(k)
    print("driver AI infos: %d characters, villain infos: %d" % (len(drivers), len(villains)))
    key2name = {v: k for k, v in infos.items()}
    for terrain in ("air", "land", "sea"):
        got = by_terrain.get(terrain, [])
        print("  %-4s villains: %s"
              % (terrain, ", ".join(key2name.get(k, "%08X" % k) for k in got) or "-"))
    print("pools found: %d" % len(pool_rows))

    if not villains:
        print("error: no villain infos resolved", file=sys.stderr)
        return 1

    total = 0
    for pname, terrain in POOLS:
        if pname not in pool_rows:
            print("error: %s not found" % pname, file=sys.stderr)
            return 1
        w, key, roff, rlen, ps, ln, keys = pool_rows[pname]
        body = raw[ps:ps + ln]
        refs = [struct.unpack_from(">I", raw, j + 4)[0]
                for j in range(roff, roff + rlen, 8)]
        # the shipped tables list the personality record last, so the entries
        # are the same set as the records but rotated by one; match by value
        if sorted(refs) != sorted(keys):
            print("error: %s ref table does not mirror its records" % pname, file=sys.stderr)
            return 1
        pool_villains = by_terrain.get(terrain, [])
        slots = list(range(1, len(keys)))[-min(args.slots, len(pool_villains)):]  # skip the personality record
        picks = pool_villains[:len(slots)]
        print("\n%s (%s): %d records, replacing %d driver slots"
              % (pname, terrain, len(keys), len(slots)))
        for slot, vkey in zip(slots, picks):
            # keep a record that is already a villain, and never duplicate within the pool
            if keys[slot] in villains or vkey in keys:
                continue
            print("   [%2d] %08X -> %08X" % (slot, keys[slot], vkey))
            if args.dry_run:
                continue
            ref_slot = refs.index(keys[slot])
            struct.pack_into(">I", d, ps + 0x18 + slot * 16 + 4, vkey)
            struct.pack_into(">I", d, roff + ref_slot * 8 + 4, vkey)
            refs[ref_slot] = vkey
            keys[slot] = vkey
            total += 1

    # ---- one info is one racer: a pool may not list the same record three
    # times. Each shipped action-pack pool repeats its Greeble record three
    # times, so recasting that one object puts three clones of a single figure
    # on the grid. Only excess records move, and only onto keys the pool already
    # references, so the 0x139C ref table (distinct keys, fixed size) stays as is.
    print("\nduplicate records spread:")
    spread = 0
    for pname, (w, key, roff, rlen, ps, ln, keys) in pool_rows.items():
        if len(keys) < 3:
            continue
        distinct = []
        for k in keys[1:]:
            if k not in distinct:
                distinct.append(k)
        if len(distinct) < 2:
            continue
        moved = 0
        for i in range(1, len(keys)):
            if keys.count(keys[i]) <= 2:
                continue
            cand = min((k for k in distinct if k != keys[i]),
                       key=lambda k: (keys.count(k), distinct.index(k)), default=None)
            if cand is None or keys.count(cand) >= 2:
                continue
            print("   %-44s [%2d] %08X -> %08X" % (pname, i, keys[i], cand))
            if args.dry_run:
                continue
            struct.pack_into(">I", d, ps + 0x18 + i * 16 + 4, cand)
            keys[i] = cand
            moved += 1
        if not moved:
            print("   %-44s nothing to spread" % pname)
        spread += moved
    total += spread

    if args.dry_run:
        print("\ndry run - nothing written")
        return 0

    out = bytes(d)
    if len(out) != len(raw):
        print("error: size changed", file=sys.stderr)
        return 1

    # ---- verify: only record/ref key fields differ, everything still consistent
    diff = [i for i in range(len(raw)) if raw[i] != out[i]]
    print("\nbytes changed: %d (slots written: %d)" % (len(diff), total))
    allowed = set()
    for pname, (w, key, roff, rlen, ps, ln, _) in pool_rows.items():
        if not ln:
            continue
        n = (ln - 0x18 + 8) // 16
        for i in range(n):
            for b in range(4):
                allowed.add(ps + 0x18 + i * 16 + 4 + b)
        for j in range(roff, roff + rlen, 8):
            for b in range(4):
                allowed.add(j + 4 + b)
    bad = [i for i in diff if i not in allowed]
    print("changes outside record/ref key fields:", len(bad))

    ok = True
    for w in wrappers(out):
        key, name, roff, rlen, doff, dlen = read_wrapper(out, w)
        if doff is None or not name:
            continue
        ps, ln, own, typ, keys = body_fields(out, doff)
        if typ != LIST_TYPE:
            continue
        refs = [struct.unpack_from(">I", out, j + 4)[0] for j in range(roff, roff + rlen, 8)]
        if set(refs) != set(keys):
            print("  MISMATCH %s" % name)
            ok = False
    print("every RacerAIList still mirrors its ref table:", ok)

    known = set(infos.values())
    for pname, terrain in POOLS:
        w, key, roff, rlen, ps, ln, _ = pool_rows[pname]
        doff = ps - 16
        _, _, own, typ, keys = body_fields(out, doff)
        unknown = [k for k in keys if k not in known]
        print("%-46s %-5s %d records, %d unresolved keys" % (pname, terrain, len(keys), len(unknown)))
    if bad or not ok:
        print("error: verification failed, not writing", file=sys.stderr)
        return 1
    open(args.dst or args.src, "wb").write(out)
    print("\nwrote %s (%d bytes, size unchanged)" % (args.dst or args.src, len(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
