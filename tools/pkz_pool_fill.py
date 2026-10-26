#!/usr/bin/env python3
"""Fill the four driver pools with every AI info of their terrain.

Run after `pkz_pool_all.py` has created a `Driver<Figure>_<Terrain>_AIInfo` for
every figure. Each pool keeps its personality record, then lists every info whose
name says it belongs to that terrain (plus the terrain's villain infos, which are
read from the shipped villain pools). A `RacerAIList` body is

    24-byte header | record[0..n-2] (16 B each) | last record truncated to 8 B

and every record has a matching `0x139C` entry, so the wrapper is rebuilt from
its parts (data, ref table, lengths) and the enclosing lengths grow with it. No
object keys are added, so the group's count and key registry stay untouched.

Usage: pkz_pool_fill.py [--apply]
"""
import argparse
import re
import struct
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import pkz_pool_swap as pw
import pkz_pool_all as pa

INFO_TYPE = 0x45BA524C
POOLS = (("EnemyAIList_Air_StarterPack", "Air"),
         ("EnemyAIList_Land_StarterPack", "Land"),
         ("EnemyAIList_Land_StarterPack_SheepHerder", "Land"),
         ("EnemyAIList_Sea_StarterPack", "Sea"))
TERRAIN_POOLS = (("EnemyAIList_Air_ActionPack", "Air"),
                 ("EnemyAIList_Land_ActionPack", "Land"),
                 ("EnemyAIList_Sea_ActionPack", "Sea"))
DRIVER_RE = re.compile(r"^Driver(.+)_(Air|Land|Sea)_AIInfo$")
SHARED = 0x91284605


def chunk(tag, payload):
    return struct.pack(">I", tag) + b"\x00\x01\x00\x00" + b"\x00" * 4 + \
        struct.pack(">I", len(payload)) + payload


def data_chunk(payload):
    return struct.pack(">I", 0x80001391) + b"\x00\x08\x00\x00" + b"\x00" * 4 + \
        struct.pack(">I", len(payload)) + payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="disc/files/Data/BaseGameplay.pkz")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    d = bytearray(open(args.src, "rb").read())

    def scan():
        infos, pools = {}, {}
        for w in pw.wrappers(d):
            key, name, roff, rlen, doff, dlen = pw.read_wrapper(d, w)
            if not name or doff is None:
                continue
            typ = struct.unpack_from(">I", d, doff + 20)[0]
            if typ == INFO_TYPE:
                infos[name] = key
            elif typ == pw.LIST_TYPE:
                pools[name] = (w, key, roff, rlen, doff, dlen)
        return infos, pools

    infos, pools = scan()

    villain_terrain = {}
    for pname, terrain in TERRAIN_POOLS:
        if pname not in pools:
            continue
        ps, ln, own, t2, keys = pw.body_fields(d, pools[pname][4])
        for k in keys:
            villain_terrain.setdefault(k, terrain)

    # info key -> terrain, from the name; villains keep the shipped terrain
    info_terrain = {}
    for name, key in infos.items():
        m = DRIVER_RE.match(name)
        if m:
            info_terrain[key] = (m.group(2), name)
        elif key in villain_terrain:
            info_terrain[key] = (villain_terrain[key], name)

    print("infos: %d, pools: %d" % (len(infos), len(pools)))
    for pool, terrain in POOLS:
        if pool not in pools:
            print("error: %s missing" % pool, file=sys.stderr)
            return 1
        w, key, roff, rlen, doff, dlen = pools[pool]
        wl = struct.unpack_from(">I", d, w + 12)[0]
        ps, ln, own, typ, keys = pw.body_fields(d, doff)
        header = bytes(d[ps:ps + 0x18])
        personality = keys[0]
        cast = [k for k, (t, _) in sorted(info_terrain.items(), key=lambda kv: kv[1][1])
                if t == terrain and k != personality]
        new_keys = [personality] + cast
        records = b"".join(struct.pack(">4I", 0x10 if i == 0 else 0, k, own, SHARED)
                           for i, k in enumerate(new_keys[:-1]))
        records += struct.pack(">2I", 0, new_keys[-1])
        body = header + records
        refs = b"".join(struct.pack(">II", 0x15, k) for k in new_keys[1:] + new_keys[:1])

        c80 = chunk(0x80000C80, struct.pack(">I", 1))
        c81 = chunk(0x80000C81, c80 + data_chunk(body))
        # rebuild the wrapper from its own children, replacing refs + data
        parts = []
        for o, tag, cp, cl in pw.chunks(d, w + 16, w + 16 + wl):
            if tag == 0x8000138E:
                parts.append(chunk(0x8000138E, bytes(d[cp:cp + cl])))
            elif tag == 0x8000139C:
                parts.append(chunk(0x8000139C, refs))
            elif tag == 0x80000C81:
                parts.append(c81)
            else:
                parts.append(chunk(tag, bytes(d[cp:cp + cl])))
        payload = b"".join(parts)
        delta = len(payload) - wl
        print("%-44s %-5s %3d -> %3d records, +%d bytes"
              % (pool, terrain, len(keys), len(new_keys), delta))
        if not args.apply:
            continue

        newblob = struct.pack(">I", 0x8000138D) + b"\x00\x02\x00\x01" + b"\x00" * 4 + \
            struct.pack(">I", len(payload)) + payload
        for o, t, cp, cl in pa.ancestors(d, w):
            struct.pack_into(">I", d, o + 12, cl + delta)
        struct.pack_into(">I", d, 12, struct.unpack_from(">I", d, 12)[0] + delta)
        d[w:w + 16 + wl] = newblob
        infos, pools = scan()   # offsets move with every pool

    if not args.apply:
        print("\ndry run - pass --apply to write")
        return 0

    open(args.src, "wb").write(bytes(d))
    print("wrote %s (%d bytes)" % (args.src, len(d)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
