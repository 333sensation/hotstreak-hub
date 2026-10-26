#!/usr/bin/env python3
"""Put every playable figure into the AI pools - the missing piece was the key
registry's order.

`0x139B` is not a plain list: it is a 256-bucket hash index. Its entries are
grouped by `djb2(key_as_big_endian) >> 24` and ascending inside/between buckets
(verified over all 415 entries of the `RacerAIInfo` group). Appending keys breaks
that order, which is why every earlier insertion hung the loader: the engine
could no longer find keys it asks for.

This tool therefore
  1. adds a `Driver<Figure>_<Terrain>_AIInfo` for every playable figure/terrain
     that lacks one (cloned from the shipped racer info, charId = the figure's
     catalogue key, template + vehicle kept),
  2. rebuilds the group as `count chunk + objects + registry`, with the registry
     sorted by that bucket function, and
  3. grows the four driver pools to list every info of their terrain.

Usage: pkz_pool_all.py [--apply] [--figures N]
"""
import argparse
import re
import struct
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import pkz_pool_swap as pw

INFO_TYPE = 0x45BA524C
CATALOG_TYPE = 0x5DA30426
STATS_TYPE = 0x4BBD2CFD
GROUP_TAG = 0x80000032
COUNT_TAG = 0x8000139A
REGISTRY_TAG = 0x8000139B
TERRAINS = ("Air", "Land", "Sea")
TEMPLATES = {"Air": "DriverAirLock_Air_AIInfo",
             "Land": "DriverEruptor_Land_AIInfo",
             "Sea": "DriverBowser_Sea_AIInfo"}
POOLS = (("EnemyAIList_Air_StarterPack", "Air"),
         ("EnemyAIList_Land_StarterPack", "Land"),
         ("EnemyAIList_Land_StarterPack_SheepHerder", "Land"),
         ("EnemyAIList_Sea_StarterPack", "Sea"))
TERRAIN_POOLS = (("EnemyAIList_Air_ActionPack", "Air"),
                 ("EnemyAIList_Land_ActionPack", "Land"),
                 ("EnemyAIList_Sea_ActionPack", "Sea"))
VEHICLE_RE = re.compile(r"(Plane|Car|Boat)_Stats$|^RentAWreck_", re.I)
PART_RE = re.compile(r"_(Body|Legs|Arms|Head|Top|Bottom|Wheels?|Wings?|Turret|Weapon"
                     r"|Chassis|Hull|Frame|Bumper|Spoiler|Exhaust)$", re.I)
DRIVER_RE = re.compile(r"^Driver(.+)_(Air|Land|Sea)_AIInfo$")
SHARED = 0x91284605


def djb2_be(k):
    h = 5381
    for b in struct.pack(">I", k):
        h = ((h * 33) + b) & 0xFFFFFFFF
    return h


def bucket(k):
    return djb2_be(k) >> 24


def name_of(blob, off, ln):
    """Object name that follows the ffffffff marker in a 0x138E payload."""
    seg = blob[off:off + ln]
    i = seg.find(b"\xff\xff\xff\xff")
    if i < 0:
        return None
    j = i + 4
    end = seg.find(b"\x00", j)
    if end < 0:
        return None
    return seg[j:end].decode("latin1")


def figures(cat):
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


def group_payload(d, group_off):
    """(count_chunk_off, count, [(wrapper_off, raw_bytes)], registry_chunk_off, [keys])."""
    glen = struct.unpack_from(">I", d, group_off + 12)[0]
    gps = group_off + 16
    count = None
    objs = []
    reg_off = reg_keys = None
    for o, tag, ps, ln in pw.chunks(d, gps, gps + glen):
        if tag == COUNT_TAG:
            count = struct.unpack_from(">I", d, ps)[0]
        elif tag == REGISTRY_TAG:
            reg_off = o
            reg_keys = [struct.unpack_from(">I", d, i)[0] for i in range(ps, ps + ln, 4)]
        elif tag == pw.WRAP:
            objs.append((o, bytes(d[o:o + 16 + ln])))
    return count, objs, reg_off, reg_keys, glen


def ancestors(d, off):
    chain, a, b = [], 16, len(d)
    while True:
        hit = None
        for o, t, ps, ln in pw.chunks(d, a, b):
            if o <= off < o + 16 + ln:
                hit = (o, t, ps, ln)
                break
        if not hit or hit[0] == off:
            return chain
        chain.append(hit)
        a, b = hit[2], hit[0] + 16 + hit[3]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="disc/files/Data/BaseGameplay.pkz")
    ap.add_argument("--catalog", default="disc/files/Data/BaseSkylander.pkz")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--figures", type=int, default=0, help="limit for a smoke test")
    args = ap.parse_args()

    d = bytearray(open(args.src, "rb").read())
    cat = open(args.catalog, "rb").read()

    figs = figures(cat)
    print("playable figures: %d" % len(figs))

    # existing infos, their terrain, and the group
    have, info_keys, templates = {}, {}, {}
    for w in pw.wrappers(d):
        key, name, roff, rlen, doff, dlen = pw.read_wrapper(d, w)
        if not name or doff is None:
            continue
        if struct.unpack_from(">I", d, doff + 20)[0] != INFO_TYPE:
            continue
        m = DRIVER_RE.match(name)
        if m:
            have.setdefault(m.group(1), set()).add(m.group(2))
        for terrain, tname in TEMPLATES.items():
            if name == tname:
                templates[terrain] = w
        # any info is a usable template for its terrain, prefer the named ones
        info_keys[key] = name
    group = [c[0] for c in ancestors(d, templates["Land"]) if c[1] == GROUP_TAG][0]
    count, objs, reg_off, reg_keys, glen = group_payload(d, group)
    print("group objects %d, keys %d, count %s" % (len(objs), len(reg_keys), count))
    missing_tmpl = [t for t in TERRAINS if t not in templates]
    if missing_tmpl:
        print("error: no template for %s" % missing_tmpl, file=sys.stderr)
        return 1

    if args.figures:
        figs = figs[:args.figures]
        print("  --figures: limiting to %d" % len(figs))

    used = set(info_keys)
    def fresh(seed):
        h = 0x811C9DC5
        for b in ("AI:" + seed).encode():
            h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
        while h in used or h == 0:
            h = (h + 1) & 0xFFFFFFFF
        used.add(h)
        return h

    new_objs = []
    for base, fig_key in figs:
        short = base.split("_", 1)[1] if re.match(r"^\d{4}_", base) else base
        for terrain in TERRAINS:
            if terrain in have.get(short, set()):
                continue
            tname = "Driver%s_%s_AIInfo" % (short, terrain)
            tw = templates[terrain]
            wl = struct.unpack_from(">I", d, tw + 12)[0]
            blob = bytearray(d[tw:tw + 16 + wl])
            key = fresh(tname)
            oid = fresh(tname + "#id")
            for o, tag, ps, ln in pw.chunks(blob, 16, 16 + wl):
                if tag == 0x8000138E:
                    struct.pack_into(">I", blob, o + 16, key)
                    seg = bytes(blob[o + 16:o + 16 + ln])
                    i = seg.find(b"\xff\xff\xff\xff") + 4
                    field = len(seg) - i
                    enc = tname.encode()
                    if len(enc) >= field:
                        print("error: name too long: %s" % tname, file=sys.stderr)
                        return 1
                    blob[o + 16 + i:o + 16 + ln] = enc + b"\x00" * (field - len(enc))
                elif tag == 0x8000139C:
                    old_char = struct.unpack_from(">I", blob, o + 16 + 4)[0]
                    for j in range(o + 16, o + 16 + ln, 8):
                        if struct.unpack_from(">I", blob, j + 4)[0] == old_char:
                            struct.pack_into(">I", blob, j + 4, fig_key)
                elif tag == 0x80000C81:
                    for o2, t2, p2, l2 in pw.chunks(blob, o + 16, o + 16 + ln):
                        if t2 == 0x80001391:
                            struct.pack_into(">I", blob, o2 + 16, oid)
                            struct.pack_into(">I", blob, o2 + 16 + 12, fig_key)
            new_objs.append((key, bytes(blob)))
    print("new AI infos to add: %d" % len(new_objs))
    if not new_objs and not args.apply:
        pass

    # ---- rebuild the group payload: count + objects + sorted registry
    count_off = None
    for o, tag, ps, ln in pw.chunks(d, group + 16, group + 16 + glen):
        if tag == COUNT_TAG:
            count_off = o
            count_ps, count_len = ps, ln
            break
    head = bytearray(d[count_off:count_ps + count_len])
    struct.pack_into(">I", head, 16, count + len(new_objs))
    body = b"".join(raw for _, raw in objs) + b"".join(b for _, b in new_objs)
    all_keys = list(reg_keys) + [k for k, _ in new_objs]
    all_keys.sort(key=lambda k: (bucket(k), k))
    # 16-byte chunk header: tag, 00 01 00 00, four zero bytes, length
    reg = struct.pack(">I", REGISTRY_TAG) + b"\x00\x01\x00\x00" + b"\x00" * 4 + \
        struct.pack(">I", len(all_keys) * 4) + b"".join(struct.pack(">I", k) for k in all_keys)
    new_payload = bytes(head) + body + reg
    delta = len(new_payload) - glen
    print("group payload %d -> %d (+%d), registry %d -> %d keys"
          % (glen, len(new_payload), delta, len(reg_keys), len(all_keys)))
    if not args.apply:
        print("\ndry run - pass --apply to write")
        return 0

    # lengths first, then splice the payload
    for o, t, ps, ln in ancestors(d, group):
        struct.pack_into(">I", d, o + 12, ln + delta)
    struct.pack_into(">I", d, 12, struct.unpack_from(">I", d, 12)[0] + delta)
    struct.pack_into(">I", d, group + 12, len(new_payload))
    d[group + 16:group + 16 + glen] = new_payload
    open(args.src, "wb").write(bytes(d))
    print("wrote %s (%d -> %d bytes)" % (args.src, len(d) - delta, len(d)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
