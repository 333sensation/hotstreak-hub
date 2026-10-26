#!/usr/bin/env python3
"""Make every RacerAIList pool reference AI infos of its own terrain.

Each `Driver<Name>_<Terrain>_AIInfo` record carries the driver, the AI template,
the vehicle for that terrain and the terrain id:

    80 00 13 91 00 08 00 00 00 00 | len | own id | RacerAIInfo | 0
    | char id | template id | vehicle id | terrain (1=Land 2=Air 3=Sea)

A RacerAIList body is

    own id | RacerAIList | 0 | u16 maxRacers, u16 count | ... 
    | { u32 word, u32 key, u32 owner, u32 shared=0x91284605 } * N
    | u32 0, u32 key                       (trailing slot)

The shipped pools are shifted: `EnemyAIList_Land_ActionPack` lists `*_Air_AIInfo`
entries and `EnemyAIList_Sea_ActionPack` lists `*_Land_AIInfo` entries, so bots
are spawned with a vehicle/terrain that does not match the race.

This tool rewrites the key of every driver entry in a pool to the same driver's
AI info for the pool's own terrain. Only 4-byte key slots change, so every
length, count and layout in the container stays exactly as it was.
"""
import argparse
import os
import re
import struct
import sys

DATA_TAG = b"\x80\x00\x13\x91\x00\x08\x00\x00\x00\x00"
LIST_TYPE = 0xCAFB9B03  # crc32("RACERAILIST")
SHARED = 0x91284605

TERRAINS = {"land": 1, "air": 2, "sea": 3}
DRIVER_RE = re.compile(r"^Driver(.+)_(Land|Air|Sea)_AIInfo$")


def obj_key(d, off, size):
    """The object's key lives in the 0x138E chunk that follows its payload."""
    seg = d[off:off + size + 0x200]
    m = re.search(rb"\x80\x00\x13\x8e", seg)
    if not m or m.start() + 0x14 > len(seg):
        return None
    return struct.unpack_from(">I", seg, m.start() + 0x10)[0]


def walk_objects(d):
    """Yield (offset, own_id, type, body_start, body_len, name)."""
    for m in re.finditer(re.escape(DATA_TAG), d):
        s = m.start()
        body_len = struct.unpack_from(">I", d, s + 12)[0]
        own = struct.unpack_from(">I", d, s + 16)[0]
        typ = struct.unpack_from(">I", d, s + 20)[0]
        bs = s + 16
        end = d.find(b"\x80\x00\x13\x8d", s)
        if end < 0:
            continue
        nm = re.search(rb"[ -~]{2,80}\x00", d[end:end + 0x100])
        if not nm:
            continue
        yield s, own, typ, bs, end - bs, nm.group(0)[:-1].decode("latin1")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pkz", default="disc/files/Data/BaseGameplay.pkz")
    ap.add_argument("--apply", action="store_true",
                    help="write the patch (default is a dry run)")
    args = ap.parse_args()

    path = args.pkz
    d = bytearray(open(path, "rb").read())
    objs = list(walk_objects(bytes(d)))

    # driver -> terrain -> key
    keymap = {}
    for s, own, typ, bs, blen, name in objs:
        m = DRIVER_RE.match(name)
        if not m:
            continue
        k = obj_key(bytes(d), s, blen)
        if k is not None:
            keymap.setdefault(m.group(1), {})[m.group(2).lower()] = k

    print("drivers with AI infos: %d" % len(keymap))
    for drv, t in sorted(keymap.items()):
        print("  %-16s %s" % (drv, " ".join("%s=%08X" % (a, b) for a, b in sorted(t.items()))))

    # every key we might have to rewrite, mapped to its driver
    key2driver = {}
    for drv, t in keymap.items():
        for terr, k in t.items():
            key2driver[k] = (drv, terr)

    pools = [o for o in objs if o[2] == LIST_TYPE]
    changed_total = 0
    for s, own, typ, bs, blen, name in pools:
        m = re.search(r"(Land|Air|Sea)", name)
        if not m:
            continue
        want = m.group(1).lower()
        body = bytes(d[bs:bs + blen])
        edits = []
        for i in range(0, len(body) - 3, 4):
            k = struct.unpack_from(">I", body, i)[0]
            if k not in key2driver:
                continue
            drv, terr = key2driver[k]
            new = keymap.get(drv, {}).get(want)
            if new is None or new == k:
                continue
            edits.append((i, k, new, drv, terr))
        if not edits:
            continue
        print("\n%s  (%d key slots -> %s)" % (name, len(edits), want))
        for i, old, new, drv, terr in edits:
            print("  +0x%03X  %-16s %s %08X -> %08X %s"
                  % (i, drv, terr, old, new, want))
            if args.apply:
                struct.pack_into(">I", d, bs + i, new)
        changed_total += len(edits)

    print("\nkey slots rewritten: %d" % changed_total)
    if not args.apply:
        print("dry run - pass --apply to write")
        return 0
    if len(d) != os.path.getsize(path):
        print("error: file size changed", file=sys.stderr)
        return 1
    open(path, "wb").write(d)
    print("wrote %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
