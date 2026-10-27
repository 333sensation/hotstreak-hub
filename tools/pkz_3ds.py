#!/usr/bin/env python3
"""Read the 3DS build's `.pkz` containers (Skylanders: SuperChargers Racing).

The 3DS romfs next to the Wii disc ships the same game data in a different
wrapper, and both halves of that were worked out from the files themselves:

  * the container is **little-endian** (the Wii build is big-endian): the root
    chunk of a plain container starts `01 00 00 80` = tag `0x80000001`;
  * the chunk header is the same 16 bytes, but the two `u32`s swap places —
    on the Wii it is `tag, u16, u16, 0, len`, on the 3DS `tag, u16, u16, len, 0`;
  * a container that starts `b0 b1 be ba` is **zlib-compressed**: an 0x8000-byte
    header (+0x04 = where the payload starts, +0x0C = the uncompressed size, all
    little-endian, the rest 0xAA fill) followed by one or more zlib streams, each
    inflating to a little-endian roceGS stream.

Proof it is the same data: `BaseSkylander.pkz` on the 3DS inflates to 174,028
bytes, exactly its header's size, and that stream carries 343 `0x138D` object
wrappers with the figure names (`0009_Eruptor_Series3_LavaBarf`, ...) and 102
`*Stats` names — the same objects the Wii build parses.

    90 of the 782 files on that romfs are plain (the small ones); 691 are the
    zlib wrapper, including every file the multiplayer wiring lives in
    (`BaseGameplay.pkz`, `Main.pkz`, `FrontScreen.pkz`, `MultiplayerHuds.pkz`,
    the level `*_Common.pkz`). One file starts with neither (0xF8110080).

What that comparison settles: the 3DS build's `BaseGameplay.pkz` carries the
same two objects the Wii build does - `Player1Reference` and
`Player2Reference` - and every level ships the *same three* splitscreen
overriders with the same keys on both builds (`MNG_SplitscreenOverrider_2P`,
`_4P`, `_Multiplayer`). Four-player local play is therefore not data the 3DS
build has and the Wii build lacks; it lives in the executables (the Wii one
registers the 2P local flow and never starts the online one).

Usage:
    pkz_3ds.py <file.pkz>                    what it is, and what it inflates to
    pkz_3ds.py <file.pkz> --list             object names, keys, payload sizes
    pkz_3ds.py <file.pkz> --unpack out.bin   write the inner roceGS stream
    pkz_3ds.py <file.pkz> --name _AIInfo     filter --list by substring

Measured against the dump this was written for (`.../romfs/0004000000165E00`):
`BaseSkylander.pkz` 98,304 -> 174,028 bytes / 343 objects, `BaseGameplay.pkz`
3,014,656 -> 6,154,009 bytes / 1,234 objects, `MultiplayerHuds.pkz` -> 617,117
bytes / 149 objects, `L_ChompyMountain_Common.pkz` -> 7,377,190 bytes / 185
objects. Payload sizes are only read where the object frames the way the Wii
build does (`payload=0` means the walker did not resolve that object's body,
not that it is empty).
"""
import argparse
import os
import re
import struct
import sys
import zlib

MAGIC = b"\xb0\xb1\xbe\xba"
PLAIN_TAG = b"\x01\x00\x00\x80"
PAYLOAD_OFF = 0x8000

WRAP = 0x8000138D
KEYC = 0x8000138E
REFC = 0x8000139C
BODY = 0x80001391
NEST = 0x80000C81


# ---------------------------------------------------------------- container

def u32(d, off):
    return struct.unpack_from("<I", d, off)[0]


def header(d):
    """(payload offset, uncompressed size) out of a 0xB0B1BEBA header."""
    return u32(d, 4), u32(d, 0x0C)


def find_stream(d, start):
    """Offset of the next zlib stream header at or after `start`."""
    for o in range(start, len(d) - 1):
        if d[o] == 0x78 and ((0x78 << 8) | d[o + 1]) % 31 == 0:
            if inflate(d, o, limit=4096)[0]:
                return o
    return None


def inflate(d, off, limit=None, chunk=8192):
    """Inflate one zlib stream at `off`; on a stream error keep what we got.

    The containers hold several streams back to back, so a short/corrupt tail is
    expected; feeding the input in chunks keeps the output produced before the
    error, which a single `decompress()` call would throw away.
    """
    oo = zlib.decompressobj(15)
    out = bytearray()
    for i in range(off, len(d), chunk):
        try:
            out += oo.decompress(d[i:i + chunk])
        except zlib.error:
            break
        if limit and len(out) >= limit:
            break
        if oo.eof:
            break
    return bytes(out[:limit] if limit else out), oo.eof


def streams(d):
    """Every zlib stream in the file, in order, with the bytes it inflates to."""
    out = []
    pos = PAYLOAD_OFF if d[:4] == MAGIC else 0
    while pos is not None and pos < len(d) - 1:
        nxt = find_stream(d, pos)
        if nxt is None:
            break
        data, eof = inflate(d, nxt)
        if data:
            out.append((nxt, data, eof))
        pos = nxt + 2 + max(len(data) // 4, 64)
    return out


def load(path):
    """(kind, inner roceGS bytes, [(offset, size, complete), ...])."""
    d = open(path, "rb").read()
    if d[:4] == PLAIN_TAG:
        return "plain", d, []
    if d[:4] != MAGIC:
        return "unknown", d, []
    parts = streams(d)
    inner = b"".join(p for _, p, _ in parts) if parts else b""
    return "zlib", inner, [(o, len(p), e) for o, p, e in parts]


# ------------------------------------------------------------------- objects

def chunks(d, start, end):
    """Walk a little-endian chunk stream. Stops at the first bad header."""
    o = start
    while o + 16 <= end:
        tag = u32(d, o)
        if tag >> 16 != 0x8000:
            return
        ln = u32(d, o + 8)
        if o + 16 + ln > end:
            return
        yield o, tag, o + 16, ln
        o += 16 + ln


def find_root(d, window=0x200):
    """Offset where the chunk stream starts.

    A plain container starts with its root chunk at 0; an inflated one can keep
    a small prologue in front of it, so take the offset that tiles the most of
    the buffer.
    """
    best, best_len = 0, -1
    for o in range(0, min(window, len(d) - 16)):
        if u32(d, o) >> 16 != 0x8000:
            continue
        covered = sum(16 + ln for _, _, _, ln in chunks(d, o, len(d)))
        if covered > best_len:
            best, best_len = o, covered
    return best


def wrappers(d, start=None, end=None):
    """Every 0x138D object wrapper, descending through chunk payloads."""
    if end is None:
        end = len(d)
    if start is None:
        start = find_root(d)
    for o, tag, ps, ln in chunks(d, start, end):
        if tag == WRAP:
            yield o
        elif 16 <= ln and u32(d, ps) >> 16 == 0x8000:
            for w in wrappers(d, ps, ps + ln):
                yield w


def read_wrapper(d, w):
    """(key, name, refs, payload, payload_len) of one wrapper."""
    wl = u32(d, w + 8)
    key = name = payload = None
    plen = 0
    refs = []
    for o, tag, ps, ln in chunks(d, w + 16, w + 16 + wl):
        if tag == KEYC:
            seg = d[ps:ps + ln]
            key = u32(seg, 0)
            m = re.search(rb"[ -~]{2,80}\x00", seg)
            name = m.group(0)[:-1].decode("latin1") if m else None
        elif tag == REFC:
            refs = [u32(d, j + 4) for j in range(ps, ps + ln, 8)]
        elif tag == NEST:
            for o2, t2, p2, l2 in chunks(d, ps, ps + ln):
                if t2 == BODY:
                    payload = d[p2:p2 + l2]
                    plen = l2
    return key, name, refs, payload, plen


def objects(inner, tolerant=True):
    """Every named object: the strict walk first, then a tolerant sweep.

    The 3DS chunk stream is not framed exactly like the Wii one in every object,
    so a single bad header can cut the walk short. The sweep takes every
    `0x138D` tag as a wrapper start and reads the key chunk out of its own span,
    which survives headers this reader has not seen yet.
    """
    rows = [o for o in (read_wrapper(inner, w) for w in wrappers(inner)) if o[1]]
    if not tolerant:
        return rows
    seen = {r[0] for r in rows}
    for m in re.finditer(re.escape(WRAP.to_bytes(4, "little")), inner):
        w = m.start()
        ln = u32(inner, w + 8) if w + 16 <= len(inner) else 0
        end = min(len(inner), w + 16 + ln) if 16 <= ln < (1 << 24) else min(len(inner), w + 0x800)
        span = inner[w:end]
        k = span.find(KEYC.to_bytes(4, "little"))
        if k < 0:
            continue
        key = u32(span, k + 16)
        if key in seen:
            continue
        nm = re.search(rb"[ -~]{2,80}\x00", span[k + 16:k + 16 + 0x60])
        if not nm:
            continue
        seen.add(key)
        b = span.find(BODY.to_bytes(4, "little"))
        plen = u32(span, b + 8) if b >= 0 and b + 16 <= len(span) else 0
        rows.append((key, nm.group(0)[:-1].decode("latin1"), [], b"", plen))
    return rows


# ---------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("--list", action="store_true", help="print the objects")
    ap.add_argument("--name", help="with --list, keep names containing this")
    ap.add_argument("--unpack", metavar="OUT", help="write the inner roceGS stream")
    args = ap.parse_args()

    kind, inner, parts = load(args.file)
    size = os.path.getsize(args.file)
    if kind == "unknown":
        print("%s: not a roceGS container (starts %s)"
              % (args.file, open(args.file, "rb").read(4).hex()), file=sys.stderr)
        return 1
    print("%s: %d bytes, %s container" % (args.file, size,
                                          "plain little-endian" if kind == "plain"
                                          else "zlib-wrapped little-endian"))
    if kind == "zlib":
        off, unc = header(open(args.file, "rb").read())
        print("   header: payload at 0x%X, uncompressed %d bytes" % (off, unc))
        for o, n, eof in parts:
            print("   stream at 0x%06X -> %d bytes%s" % (o, n, "" if eof else " (tail cut)"))
    rows = objects(inner)
    print("   %d objects in %d bytes" % (len(rows), len(inner)))
    if args.unpack:
        open(args.unpack, "wb").write(inner)
        print("   wrote %s" % args.unpack)
    if args.list:
        for key, name, refs, payload, plen in rows:
            if args.name and args.name.lower() not in name.lower():
                continue
            print("   %-46s key=%08X payload=%-6d refs=%d"
                  % (name, key or 0, plen, len(refs)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
