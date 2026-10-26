#!/usr/bin/env python3
"""Give every playable figure a `Driver<Name>_<Terrain>_AIInfo` record.

The 20 SuperChargers each own three `RacerAIInfo` objects (`0x45BA524C`), one per
terrain; every other figure has none, which is why only they can appear as bots.
But the missing pieces do exist:

* a figure's **character id** is the key of its catalogue object in
  `BaseSkylander.pkz` (type `0x5DA30426`, e.g. `0000_Whirlwind` -> `A6C7C735`),
  and the shipped `VehicleDriverPairList` proves that mapping (`3406_Peacock`
  key `9A56169E` is exactly the char id in `DriverPeacock_*_AIInfo`);
* the **vehicle** can be the rental the Greeble villains already use
  (`RentAWreck_Plane/Car/Boat`, keys `77878CD4` / `0C4E3BF4` / `47422C66`);
* the AI **template** is then `A76001FE`, the one those Greeble infos carry.

So each new AI info is a byte-for-byte clone of the matching Greeble info with
only its key, name, own id and character id replaced - a proven
(char, template, rental vehicle) combination, per terrain.

Objects are inserted into the `RacerAIInfo` group (`0x80000032`) properly:
the new `0x138D` wrapper goes in front of the group's `0x139B` key registry, the
`0x139A` object count is bumped, the registry gets the new keys, and every
enclosing length moves with it. Without those three fixups the loader ignores
appended objects, which is why the earlier append attempt did nothing.

Usage: pkz_ai_add.py [--apply] [--limit N]
"""
import argparse
import re
import struct
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import pkz_pool_swap as pw  # wrapper/chunk helpers

INFO_TYPE = 0x45BA524C
CATALOG_TYPE = 0x5DA30426
STATS_TYPE = 0x4BBD2CFD
TERRAINS = ("Air", "Land", "Sea")
# the shipped villain infos that drive the per-terrain rental vehicles
TEMPLATES = {"Air": "GreeblePlaneInfo", "Land": "GreebleCarInfo", "Sea": "GreebleBoatInfo"}
GROUP_TAG = 0x80000032
COUNT_TAG = 0x8000139A
REGISTRY_TAG = 0x8000139B
WRAP_TAG = 0x8000138D
NAME_RE = re.compile(r"^(\d{4})_(.+)$")
VEHICLE_RE = re.compile(r"(Plane|Car|Boat)_Stats$|^RentAWreck_", re.I)


def chunk_map(d):
    """offset -> (tag, payload_start, length, parent_start, parent_end)."""
    out = {}

    def walk(start, end):
        for o, tag, ps, ln in pw.chunks(d, start, end):
            out[o] = (tag, ps, ln, start, end)
            if ln >= 16 and d[ps] >= 0x80 and struct.unpack_from(">I", d, ps)[0] >> 16 == 0x8000:
                walk(ps, ps + ln)

    walk(16, len(d))
    return out


def ancestors(cmap, off):
    """Chunk offsets from `off` up to the root."""
    chain, cur = [], off
    while cur in cmap:
        chain.append(cur)
        parent_start = cmap[cur][3]
        if parent_start == 16:
            break
        cur = parent_start - 16  # parent chunk header sits 16 bytes before payload
    return chain


def rewrite_name(blob, name):
    """Replace the zero-padded name that follows the ffffffff marker."""
    i = blob.find(b"\xff\xff\xff\xff")
    if i < 0:
        raise SystemExit("error: no name marker in 0x138E payload")
    start = i + 4
    field = blob[start:]
    keep = len(field)
    enc = name.encode("latin1")
    if len(enc) >= keep:
        raise SystemExit("error: name too long for 0x138E field")
    out = bytearray(blob)
    out[start:] = enc + b"\x00" * (keep - len(enc))
    return bytes(out)


def read_bytes(d, path):
    n = 0
    for fn in (path,):
        pass
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="disc/files/Data/BaseGameplay.pkz")
    ap.add_argument("--catalog", default="disc/files/Data/BaseSkylander.pkz")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    d = bytearray(open(args.src, "rb").read())
    cat = open(args.catalog, "rb").read()

    # ---- character ids from the catalogue, keyed by figure name
    char_id = {}
    for w in pw.wrappers(cat):
        key, name, roff, rlen, doff, dlen = pw.read_wrapper(cat, w)
        if not name or doff is None:
            continue
        if struct.unpack_from(">I", cat, doff + 20)[0] != CATALOG_TYPE:
            continue
        char_id[name] = key
    print("catalogue objects usable as character ids: %d" % len(char_id))

    # ---- figures that have stats (= playable characters, vehicles excluded)
    figures = []
    for w in pw.wrappers(cat):
        key, name, roff, rlen, doff, dlen = pw.read_wrapper(cat, w)
        if not name or doff is None:
            continue
        if struct.unpack_from(">I", cat, doff + 20)[0] != STATS_TYPE or VEHICLE_RE.search(name):
            continue
        base = re.sub(r"_?Stats$", "", name)
        if base in char_id:
            figures.append(base)
    figures = sorted(set(figures))
    print("figures with stats and a character id: %d" % len(figures))

    # ---- what already exists
    templates, have = {}, {}
    info_wrappers = []
    for w in pw.wrappers(d):
        key, name, roff, rlen, doff, dlen = pw.read_wrapper(d, w)
        if not name or doff is None:
            continue
        if struct.unpack_from(">I", d, doff + 20)[0] != INFO_TYPE:
            continue
        info_wrappers.append((w, key, name, roff, rlen, doff, dlen))
        for terrain, tname in TEMPLATES.items():
            if name == tname:
                templates[terrain] = (w, key, name, roff, rlen, doff, dlen)
        m = re.match(r"^Driver(.+)_(Air|Land|Sea)_AIInfo$", name)
        if m:
            have.setdefault(m.group(1), set()).add(m.group(2).lower())
    print("existing AI infos: %d, greeble templates: %s" % (len(info_wrappers), sorted(templates)))
    if len(templates) != 3:
        print("error: need GreebleAir/Land/Sea infos as templates", file=sys.stderr)
        return 1

    group = None
    for w, key, name, roff, rlen, doff, dlen in info_wrappers:
        for a in ancestors(chunk_map(d), w):
            if chunk_map(d)[a][0] == GROUP_TAG:
                group = a
                break
        if group:
            break
    cmap = chunk_map(d)
    count_off = registry_off = None
    gtag, gps, glen, _, _ = cmap[group]
    for o, tag, pp, ln in pw.chunks(d, gps, gps + glen):
        if tag == COUNT_TAG:
            count_off = o
        elif tag == REGISTRY_TAG:
            registry_off = o
    print("group 0x%X len %d, count chunk %s, registry chunk %s"
          % (group, glen, hex(count_off), hex(registry_off)))
    if count_off is None or registry_off is None:
        print("error: group is missing 0x139A/0x139B", file=sys.stderr)
        return 1
    print("group object count: %d, registry entries: %d"
          % (struct.unpack_from(">I", d, count_off + 16)[0],
             struct.unpack_from(">I", d, registry_off + 12)[0] // 4))

    # ---- build the new objects
    all_keys = set()
    for w in pw.wrappers(d):
        k = pw.read_wrapper(d, w)[0]
        if k is not None:
            all_keys.add(k)

    def new_key(name):
        h = 0x811C9DC5
        for b in ("AI:" + name).encode():
            h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
        while h in all_keys or h == 0:
            h = (h + 1) & 0xFFFFFFFF
        all_keys.add(h)
        return h

    def figure_id(base):
        return base.split("_", 1)[1] if NAME_RE.match(base) else base

    planned = []
    for base in figures:
        short = figure_id(base)
        for terrain in TERRAINS:
            if terrain.lower() in have.get(short, set()):
                continue
            tw, tkey, tname, troff, trlen, tdoff, tdlen = templates[terrain]
            wl = struct.unpack_from(">I", d, tw + 12)[0]
            blob = bytearray(d[tw:tw + 16 + wl])

            name = "Driver%s_%s_AIInfo" % (short, terrain)
            key = new_key(name)
            oid = new_key(name + "#id")

            # 0x138E: key + name
            for o, tag, pp, ln in pw.chunks(blob, 16, 16 + wl):
                if tag == 0x8000138E:
                    struct.pack_into(">I", blob, o + 16, key)
                    seg = rewrite_name(bytes(blob[o + 16:o + 16 + ln]), name)
                    blob[o + 16:o + 16 + ln] = seg
                elif tag == 0x8000139C:
                    # refs: charId first (the one that is not template/vehicle)
                    refs = [struct.unpack_from(">I", blob, i + 20)[0] for i in range(o + 16, o + 16 + ln, 8)]
                    tvals = [struct.unpack_from(">I", d, tdoff + 16 + 4 * i)[0] for i in range(2, 7)]
                    old_char = tvals[1]
                    for i in range(o + 16, o + 16 + ln, 8):
                        if struct.unpack_from(">I", blob, i + 4)[0] == old_char:
                            struct.pack_into(">I", blob, i + 4, char_id[base])
                elif tag == 0x80001391:
                    raise SystemExit("error: unexpected nesting")
                elif tag == 0x80000C81:
                    # nested 0x0C80 marker + 0x1391 data
                    for o2, t2, p2, l2 in pw.chunks(blob, o + 16, o + 16 + ln):
                        if t2 == 0x80001391:
                            struct.pack_into(">I", blob, o2 + 16, oid)
                            struct.pack_into(">I", blob, o2 + 16 + 12, char_id[base])
            planned.append((name, key, base, terrain, bytes(blob), char_id[base]))

    print("AI infos to add: %d (for %d figures)" % (len(planned), len(figures)))
    for p in planned[:6]:
        print("   %-38s key=%08X char=%08X (%s)" % (p[0], p[1], p[5], p[2]))
    if args.limit:
        planned = planned[:args.limit]
        print("   --limit: keeping %d" % len(planned))
    if not planned:
        print("nothing to do")
        return 0
    if not args.apply:
        print("\ndry run - pass --apply to write")
        return 0

    # ---- insert
    anchor = registry_off
    blob_all = b"".join(p[4] for p in planned)
    keys = b"".join(struct.pack(">I", p[1]) for p in planned)
    add = len(blob_all) + len(keys)

    glen_new = glen + add
    struct.pack_into(">I", d, group + 12, glen_new)
    for a in ancestors(cmap, group):
        o = a
        if o == group:
            continue
        alen = struct.unpack_from(">I", d, o + 12)[0]
        struct.pack_into(">I", d, o + 12, alen + add)
    # root chunk
    root_len = struct.unpack_from(">I", d, 12)[0]
    struct.pack_into(">I", d, 12, root_len + add)
    # count + registry
    cnt = struct.unpack_from(">I", d, count_off + 16)[0]
    struct.pack_into(">I", d, count_off + 16, cnt + len(planned))
    rlen = struct.unpack_from(">I", d, registry_off + 12)[0]
    struct.pack_into(">I", d, registry_off + 12, rlen + len(keys))
    # insert objects in front of the registry, keys at the registry's end
    d[anchor:anchor] = blob_all
    d[anchor + len(blob_all) + 16 + rlen:anchor + len(blob_all) + 16 + rlen] = keys

    out = bytes(d)
    if len(out) != len(d):
        pass
    open(args.src, "wb").write(out)
    print("\nwrote %s (%d -> %d bytes, +%d)" % (args.src, len(d) - add, len(out), add))
    return 0


if __name__ == "__main__":
    sys.exit(main())
