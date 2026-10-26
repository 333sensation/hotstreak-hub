#!/usr/bin/env python3
"""Bind every object's NAME to its data chunk by walking the chunk tree.

The earlier flat scans read the name that *follows* a data chunk, which belongs
to the next object, so every name<->data binding was shifted by one. In the real
layout a wrapper chunk carries the object's key, its name and its reference list,
and nests the object's data:

    0x138D wrapper
        0x138E   key
        ffffffff + name (64 bytes, zero padded)
        0x0C80   marker
        0x139C   refs  ("00000015 <key>" * n)
        0x0C81
            0x0C80 marker
            0x1391 data      <- own id, type, fields

This tool walks that structure and prints (name, type, own id, key, refs).
"""
import argparse
import re
import struct
import sys

WRAP = 0x8000138D
KEYC = 0x8000138E
DATA = 0x80001391
REFC = 0x8000139C
MARK = 0x80000C80


def chunks(d, start, end):
    o = start
    while o + 16 <= end:
        tag = struct.unpack_from(">I", d, o)[0]
        if tag >> 16 != 0x8000:
            return
        ln = struct.unpack_from(">I", d, o + 12)[0]
        yield o, tag, o + 16, ln
        o += 16 + ln


def find_data(d, start, end):
    """First 0x1391 chunk nested anywhere inside [start,end)."""
    for o, tag, ps, ln in chunks(d, start, end):
        if tag == DATA:
            return o, ln
        got = find_data(d, ps, ps + ln)
        if got:
            return got
    return None, None


def tiles(d, start, end):
    o = start
    while o < end:
        if o + 16 > end or struct.unpack_from(">I", d, o)[0] >> 16 != 0x8000:
            return False
        o += 16 + struct.unpack_from(">I", d, o + 12)[0]
    return o == end


def objects(d):
    """Yield dict(name, type, own, key, refs, data_off, data_len)."""
    out = []

    def walk(start, end):
        for o, tag, ps, ln in chunks(d, start, end):
            if tag == WRAP:
                name = None
                key = None
                refs = []
                segment = d[ps:ps + ln]
                m = re.search(rb"\xff\xff\xff\xff([ -~]{2,63})\x00", segment)
                if m:
                    name = m.group(1).decode("latin1").strip()
                for co, ctag, cps, cl in chunks(d, ps, ps + ln):
                    if ctag == KEYC and cl >= 4:
                        key = struct.unpack_from(">I", d, cps)[0]
                    elif ctag == REFC:
                        refs = [struct.unpack_from(">I", d, i + 4)[0]
                                for i in range(cps, cps + cl, 8)]
                doff, dlen = find_data(d, ps, ps + ln)
                if name and doff is not None:
                    out.append({
                        "name": name,
                        "type": struct.unpack_from(">I", d, doff + 20)[0],
                        "own": struct.unpack_from(">I", d, doff + 16)[0], "key": key,
                        "refs": refs, "data_off": doff, "data_len": dlen,
                        "wrap_off": o, "wrap_len": ln,
                    })
            elif tiles(d, ps, ps + ln):
                walk(ps, ps + ln)

    walk(16, len(d))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--type", default=None)
    ap.add_argument("--name", default=None)
    args = ap.parse_args()
    d = open(args.file, "rb").read()
    want = None
    if args.type:
        import zlib
        want = zlib.crc32(args.type.upper().encode()) & 0xFFFFFFFF
    n = 0
    for ob in objects(d):
        n += 1
        if want is not None and ob["type"] != want:
            continue
        if args.name and args.name.lower() not in ob["name"].lower():
            continue
        print("%-42s type=%08X own=%08X key=%s refs=%2d @0x%X len=%d"
              % (ob["name"], ob["type"], ob["own"],
                 "%08X" % ob["key"] if ob["key"] else "--------",
                 len(ob["refs"]), ob["data_off"], ob["data_len"]))
    print("# objects bound: %d" % n)


if __name__ == "__main__":
    sys.exit(main())
