#!/usr/bin/env python3
"""Probe: insert exactly one new RacerAIInfo (Spyro, land) and field it.

Everything that worked so far was size-neutral. This is the smallest possible
test of the other question: *can* an object be added at all? It clones a real
racer info (`DriverEruptor_Land_AIInfo`, template `33D91E1A`), renames it
`DriverSpyro_Land_AIInfo`, points it at Spyro's catalogue key, inserts it into
the `RacerAIInfo` group with count/registry/length fixups, and then replaces one
driver record of `EnemyAIList_Land_StarterPack` with the new key so the race
actually has a chance to field it.

If the game loads and Spyro shows up, insertion works and the same code can add
every figure. If it hangs, the container really is fixed-size and the ceiling is
the 71 existing AI records.

Usage: pkz_add_test.py [--apply]
"""
import argparse
import struct
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import pkz_pool_swap as pw

INFO_TYPE = 0x45BA524C
CATALOG_TYPE = 0x5DA30426
GROUP_TAG = 0x80000032
COUNT_TAG = 0x8000139A
REGISTRY_TAG = 0x8000139B
TEMPLATE = "DriverEruptor_Land_AIInfo"
FIGURE = "0016_Spyro"
NEW_NAME = "DriverSpyro_Land_AIInfo"
POOL = "EnemyAIList_Land_StarterPack"


def ancestors(d, w):
    """Chunk offsets enclosing `w`, innermost first, stopping at the root."""
    chain, a, b = [], 16, len(d)
    while True:
        hit = None
        for o, t, ps, ln in pw.chunks(d, a, b):
            if o <= w < o + 16 + ln:
                hit = (o, t, ps, ln)
                break
        if not hit or hit[0] == w:
            return chain
        chain.append(hit)
        a, b = hit[2], hit[0] + 16 + hit[3]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="disc/files/Data/BaseGameplay.pkz")
    ap.add_argument("--catalog", default="disc/files/Data/BaseSkylander.pkz")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    d = bytearray(open(args.src, "rb").read())
    cat = open(args.catalog, "rb").read()

    figure_key = None
    for w in pw.wrappers(cat):
        key, name, roff, rlen, doff, dlen = pw.read_wrapper(cat, w)
        if name == FIGURE and doff is not None:
            if struct.unpack_from(">I", cat, doff + 20)[0] == CATALOG_TYPE:
                figure_key = key
    print("%s catalogue key: %s" % (FIGURE, "%08X" % figure_key if figure_key else "MISSING"))
    if figure_key is None:
        return 1

    keys = set()
    info = pool = None
    for w in pw.wrappers(d):
        key, name, roff, rlen, doff, dlen = pw.read_wrapper(d, w)
        if key is not None:
            keys.add(key)
        if name is None or doff is None:
            continue
        typ = struct.unpack_from(">I", d, doff + 20)[0]
        if name == TEMPLATE and typ == INFO_TYPE:
            info = (w, key, roff, rlen, doff, dlen)
        elif name == POOL and typ == pw.LIST_TYPE:
            pool = (w, key, roff, rlen, doff, dlen)
    print("template 0x%X, pool 0x%X" % (info[0], pool[0]))

    # a unique key + instance id
    def fresh(seed):
        h = 0x811C9DC5
        for b in seed.encode():
            h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
        while h in keys or h == 0:
            h = (h + 1) & 0xFFFFFFFF
        keys.add(h)
        return h

    new_key = fresh("PROBE:" + NEW_NAME)
    new_id = fresh("PROBE:" + NEW_NAME + ":id")
    print("new key %08X, new id %08X" % (new_key, new_id))

    tw, tkey, troff, trlen, tdoff, tdlen = info
    wl = struct.unpack_from(">I", d, tw + 12)[0]
    blob = bytearray(d[tw:tw + 16 + wl])
    for o, tag, ps, ln in pw.chunks(blob, 16, 16 + wl):
        if tag == 0x8000138E:
            struct.pack_into(">I", blob, o + 16, new_key)
            seg = bytes(blob[o + 16:o + 16 + ln])
            i = seg.find(b"\xff\xff\xff\xff")
            start = i + 4
            field = len(seg) - start
            enc = NEW_NAME.encode()
            blob[o + 16 + start:o + 16 + ln] = enc + b"\x00" * (field - len(enc))
        elif tag == 0x8000139C:
            old_char = struct.unpack_from(">I", blob, o + 16 + 4)[0]
            for j in range(o + 16, o + 16 + ln, 8):
                if struct.unpack_from(">I", blob, j + 4)[0] == old_char:
                    struct.pack_into(">I", blob, j + 4, figure_key)
        elif tag == 0x80000C81:
            for o2, t2, p2, l2 in pw.chunks(blob, o + 16, o + 16 + ln):
                if t2 == 0x80001391:
                    struct.pack_into(">I", blob, o2 + 16, new_id)
                    struct.pack_into(">I", blob, o2 + 16 + 12, figure_key)
    print("cloned wrapper: %d bytes, name %s" % (len(blob), NEW_NAME))

    # locate the group and its bookkeeping chunks
    chain = ancestors(d, tw)
    group = [c for c in chain if c[1] == GROUP_TAG][0]
    gtag, gps, glen, _, _ = group[1], group[2], group[3], group[4] if len(group) > 4 else None, None
    count_off = registry_off = None
    for o, tag, ps, ln in pw.chunks(d, gps, gps + glen):
        if tag == COUNT_TAG:
            count_off = o
        elif tag == REGISTRY_TAG:
            registry_off = o
    print("group 0x%X len %d, count@0x%X, registry@0x%X"
          % (group[0], glen, count_off, registry_off))

    if not args.apply:
        print("\ndry run - pass --apply to write")
        return 0

    # grow lengths: + wrapper, + one registry key
    add = len(blob) + 4
    struct.pack_into(">I", d, group[0] + 12, glen + add)
    for o, t, ps, ln in chain:
        if o == group[0]:
            continue
        struct.pack_into(">I", d, o + 12, ln + add)
    struct.pack_into(">I", d, 12, struct.unpack_from(">I", d, 12)[0] + add)
    struct.pack_into(">I", d, count_off + 16, struct.unpack_from(">I", d, count_off + 16)[0] + 1)
    rlen = struct.unpack_from(">I", d, registry_off + 12)[0]
    struct.pack_into(">I", d, registry_off + 12, rlen + 4)

    d[registry_off:registry_off] = blob
    reg = registry_off + len(blob)
    d[reg + 16 + rlen:reg + 16 + rlen] = struct.pack(">I", new_key)

    out = bytearray(d)

    # now field it: swap one driver record of the land pool for the new key
    pool = None
    for w in pw.wrappers(out):
        key, name, roff, rlen2, doff, dlen = pw.read_wrapper(out, w)
        if name == POOL and doff is not None:
            pool = (w, key, roff, rlen2, doff, dlen)
    ps, ln, own, typ, pkeys = pw.body_fields(out, pool[4])
    slot = len(pkeys) - 2          # a full record, not the truncated last one
    old = pkeys[slot]
    struct.pack_into(">I", out, ps + 0x18 + slot * 16 + 4, new_key)
    for j in range(pool[2], pool[2] + pool[3], 8):
        if struct.unpack_from(">I", out, j + 4)[0] == old:
            struct.pack_into(">I", out, j + 4, new_key)
            break
    print("pool slot %d: %08X -> %08X" % (slot, old, new_key))

    open(args.src, "wb").write(bytes(out))
    print("wrote %s (%d -> %d bytes, +%d)" % (args.src, len(d) - add, len(out), add))
    return 0


if __name__ == "__main__":
    sys.exit(main())
