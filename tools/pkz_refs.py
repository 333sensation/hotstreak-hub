#!/usr/bin/env python3
"""Map object names to the 4-byte character GUIDs hidden in their ref tables.

Layout of one object record in a `.pkz` (all big-endian, 16-byte chunk headers):

    [0x139C ref table for this object]   00000015 <key>  * N
    [0x0C80 marker][0x0C81 wrapper]
    [0x1391 data]                        own id, type, fields...
    [0x138D closing]                     [0x138E key chunk][name][...]

So an object's GUIDs are *not* in its payload - they sit in the `0x139C` chunk that
precedes it, which is why scanning payloads found nothing.

This tool prints, for every object, its name and the reference keys listed for it,
and can resolve a given GUID back to the objects that mention it.
"""
import argparse
import re
import struct
import sys

DATA_TAG = b"\x80\x00\x13\x91\x00\x08\x00\x00\x00\x00"
REF_TAG = b"\x80\x00\x13\x9c"
END_TAG = b"\x80\x00\x13\x8d"


def records(d):
    """Yield (data_off, type, name, own_id, refs) for every data chunk."""
    for m in re.finditer(re.escape(DATA_TAG), d):
        s = m.start()
        own = struct.unpack_from(">I", d, s + 16)[0]
        typ = struct.unpack_from(">I", d, s + 20)[0]
        end = d.find(END_TAG, s)
        if end < 0:
            continue
        nm = re.search(rb"[ -~]{2,80}\x00", d[end:end + 0x100])
        if not nm:
            continue
        refs = []
        lo = max(0, s - 0x400)
        for r in reversed([x.start() + lo for x in re.finditer(re.escape(REF_TAG), d[lo:s])]):
            ln = struct.unpack_from(">I", d, r + 12)[0]
            if r + 16 + ln == s or (r + 16 + ln < s and ln % 8 == 0 and ln < 0x2000):
                refs = [struct.unpack_from(">I", d, i + 4)[0]
                        for i in range(r + 16, r + 16 + ln, 8)]
                break
        yield s, typ, nm.group(0)[:-1].decode("latin1"), own, refs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--has", action="append", default=[],
                    help="only show objects whose ref table contains this 8-hex GUID")
    ap.add_argument("--minrefs", type=int, default=0)
    args = ap.parse_args()

    want = {int(h, 16) for h in args.has}
    for path in args.files:
        d = open(path, "rb").read()
        print("== %s (%d bytes)" % (path, len(d)))
        for off, typ, name, own, refs in records(d):
            if len(refs) < args.minrefs:
                continue
            if want and not (want & set(refs)):
                continue
            print("  @0x%06X %-40s type=%08X refs=%2d %s"
                  % (off, name, typ, len(refs),
                     " ".join("%08X" % r for r in refs[:8])))


if __name__ == "__main__":
    sys.exit(main())
