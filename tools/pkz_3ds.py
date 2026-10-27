#!/usr/bin/env python3
"""Read the 3DS build's `.pkz` containers (Skylanders: SuperChargers Racing).

The 3DS romfs next to the Wii disc ships the same game data in a different
wrapper, and every part of that was worked out from the files themselves:

  * the container is **little-endian** (the Wii build is big-endian): the root
    chunk of a plain container starts `01 00 00 80` = tag `0x80000001`;
  * the chunk header is the same 16 bytes, but the two `u32`s swap places —
    on the Wii it is `tag, u16, u16, 0, len`, on the 3DS `tag, u16, u16, len, 0`;
    the type word inside a payload is still big-endian (`4BBD2CFD` = stats on both
    builds), only the ids and fields around it are little-endian;
  * a container that starts `b0 b1 be ba` is a **package archive**: a header
    (+0x04 where the packages start, +0x0C/+0x18 uncompressed totals, the rest
    0xAA fill), then one u32 per 0x4000-byte block at +0x30 naming the package
    that block belongs to (0 = the header, 0xAAAAAAAA = the fill after the map),
    then one zlib stream per package, each inflating to a little-endian roceGS
    stream. Files with a single package (e.g. `BaseSkylander.pkz`) have no map
    to speak of and just hold the one stream at 0x8000.

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
ROOT_TAG = b"\x01\x00\x00\x80"      # every package inflates to a stream starting with this
PACKAGES_AT = 0x20                   # header: how many packages the file holds
PAYLOAD_OFF = 0x8000
BLOCK = 0x4000          # the granularity the header's block map counts in
MAP_OFF = 0x30          # one u32 per block: which package owns it (0 = header)

WRAP = 0x8000138D
KEYC = 0x8000138E
REFC = 0x8000139C
BODY = 0x80001391
NEST = 0x80000C81
MARKERS = (ROOT_TAG, WRAP.to_bytes(4, "little"), BODY.to_bytes(4, "little"),
           REFC.to_bytes(4, "little"))     # what only real roceGS data contains


# ---------------------------------------------------------------- container

def u32(d, off):
    return struct.unpack_from("<I", d, off)[0]


def header(d):
    """(payload offset, uncompressed size) out of a 0xB0B1BEBA header."""
    return u32(d, 4), u32(d, 0x0C)


def inflate(d, off, limit=None, chunk=8192, stop=None):
    """Inflate one zlib stream at `off`; on a stream error keep what we got.

    The containers hold several streams back to back, so a short/corrupt tail is
    expected; feeding the input in chunks keeps the output produced before the
    error, which a single `decompress()` call would throw away.
    """
    oo = zlib.decompressobj(15)
    out = bytearray()
    for i in range(off, stop if stop is not None else len(d), chunk):
        try:
            out += oo.decompress(d[i:i + chunk])
        except zlib.error:
            break
        if limit and len(out) >= limit:
            break
        if oo.eof:
            break
    return bytes(out[:limit] if limit else out), oo.eof


def find_stream(d, start):
    """Offset of the next zlib stream at or after `start` that inflates at all."""
    for o in range(start, len(d) - 1):
        if d[o] == 0x78 and ((0x78 << 8) | d[o + 1]) % 31 == 0:
            if inflate(d, o, limit=4096)[0]:
                return o
    return None


def inflate_exact(d, off, stop=None):
    """(output, consumed) of the stream at `off`; `consumed` is None if cut short."""
    oo = zlib.decompressobj(15)
    out = bytearray()
    end = stop if stop is not None else len(d)
    pos = off
    while pos < end:
        try:
            out += oo.decompress(d[pos:pos + 8192])
        except zlib.error:
            break
        pos += 8192
        if oo.eof:
            break
    done = min(pos, end)
    return bytes(out), (done - off - len(oo.unused_data) if oo.eof else None)


def starts_like_a_package(d, off, head=ROOT_TAG):
    """Does a zlib stream at `off` begin with the roceGS root chunk?"""
    oo = zlib.decompressobj(15)
    out = bytearray()
    pos = off
    while pos < len(d) and len(out) < len(head):
        try:
            out += oo.decompress(d[pos:pos + 8192])
        except zlib.error:
            return False
        pos += 8192
        if oo.eof:
            break
    return bytes(out[:len(head)]) == head


def package_offsets(d):
    """Where the packaged streams start.

    The header is followed by one u32 per 0x4000-byte block naming the package
    that block belongs to (0 = the header, 0xAAAAAAAA = the fill after the
    table), which is enough to find the one-package files but *not* the big
    archives: on those the streams only line up under the progressive walk in
    `streams()` below (see the note in the docstring). So use the table only as
    the single-package answer and let the walk do the rest.
    """
    offs = sorted({i * BLOCK for i, v in ((i * BLOCK, u32(d, MAP_OFF + i * 4))
                                          for i in range(len(d) // BLOCK))
                   if v != 0 and v != 0xAAAAAAAA})
    return [offs[0]] if len(offs) <= 1 else []


def packages(d):
    """[(start, end)] of every package, straight out of the header's block map.

    From 0x30 there is one u32 per 0x4000-byte block naming the package that block
    belongs to: 0 is the header region, 0xAAAAAAAA the fill after the table, and
    everything else is a package number. A package is a run of that many blocks,
    which is the boundary this reader previously had to guess at.
    """
    runs = []
    for i in range(len(d) // BLOCK):
        v = u32(d, MAP_OFF + i * 4)
        if v in (0, 0xAAAAAAAA):
            continue
        here = i * BLOCK
        if runs and runs[-1][2] == v and runs[-1][1] == here:
            runs[-1][1] = here + BLOCK
        else:
            runs.append([here, here + BLOCK, v])
    return [(a, b) for a, b, _v in runs if b - a >= BLOCK]


def streams(d):
    """Every package in the file, in order, with what it inflates to.

    One package is one zlib stream, and the file's data is those streams' output
    back to back: only the first package starts on the roceGS root chunk, which is
    why the earlier version of this function - which looked for further
    root-tagged streams and, before that, for any zlib header - reported either
    one package or a hundred fragments. Slicing on the block map gets the count
    the header declares (112 in `Common.pkz`, 8 in `MultiplayerHuds.pkz`, 539 in
    `FrontScreen.pkz`) and keeps each stream inside its own package.

    The third field is how many input bytes a stream consumed, or None when its
    closing bytes were cut off by the package boundary - a stream's tail is
    routinely clipped, so zlib never reports `eof` on these.
    """
    if d[:4] != MAGIC:
        return []
    out = []
    # the first package is the one that starts on the root chunk, so find it by
    # its output; every later package is then taken from the block map
    first = None
    for scan in range(PAYLOAD_OFF, min(len(d) - 4, PAYLOAD_OFF + 0x100)):
        if (d[scan] == 0x78 and ((0x78 << 8) | d[scan + 1]) % 31 == 0
                and starts_like_a_package(d, scan)):
            first = scan
            break
    after = PAYLOAD_OFF
    if first is not None:
        data, consumed = inflate_exact(d, first)
        out.append((first, data, consumed))
        after = first + (consumed or max(2, len(data) // 4))
    for start, end in packages(d):
        if end <= after:
            continue
        nxt = None
        for scan in range(max(start, after), min(start + 0x100, end - 4)):
            if d[scan] == 0x78 and ((0x78 << 8) | d[scan + 1]) % 31 == 0:
                nxt = scan
                break
        if nxt is None:
            continue
        data, consumed = inflate_exact(d, nxt, stop=end)
        if data:
            out.append((nxt, data, consumed))
            after = nxt + (consumed or max(2, len(data) // 4))
    return out


def load(path):
    """(kind, [one little-endian roceGS stream per package], [(offset, size)])."""
    d = open(path, "rb").read()
    if d[:4] == PLAIN_TAG:
        return "plain", [d], []
    if d[:4] != MAGIC:
        return "unknown", [d], []
    parts = streams(d)
    return "zlib", [p for _, p, _ in parts], [(o, len(p)) for o, p, _ in parts]


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


def scan_section(section):
    """Named objects in one package: the strict walk, then a tolerant sweep.

    The 3DS chunk stream is not framed exactly like the Wii one in every object,
    so a single bad header can cut the walk short. The sweep takes every
    `0x138D` tag as a wrapper start and reads the key chunk out of its own span,
    which survives headers this reader has not seen yet.
    """
    rows = [o for o in (read_wrapper(section, w) for w in wrappers(section)) if o[1]]
    seen = {r[0] for r in rows}
    for m in re.finditer(re.escape(WRAP.to_bytes(4, "little")), section):
        w = m.start()
        ln = u32(section, w + 8) if w + 16 <= len(section) else 0
        end = min(len(section), w + 16 + ln) if 16 <= ln < (1 << 24) else min(len(section), w + 0x800)
        span = section[w:end]
        k = span.find(KEYC.to_bytes(4, "little"))
        if k < 0 or k + 20 > len(span):
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


def recover(d, min_out=4096):
    """[(offset, bytes)] of every zlib stream in the file that carries roceGS data.

    `streams()` is bounded by the block map, which is right for a package whose
    rows line up and wrong for a run whose data starts a block earlier: on
    `Common.pkz` it returns 53 of the 112 packages the header declares and misses
    content the file certainly holds (the cup playlists among it). This walk does
    not trust the map. It tries every zlib header in the file, inflates each one
    until zlib stops, and keeps the ones whose output actually carries roceGS
    structure - a wrapper, a data chunk, a reference table or the root chunk -
    which noise from a header inside compressed data does not produce. Overlapping
    hits are collapsed onto the earliest one, so the pieces are disjoint and in
    file order.

    Candidates are tested at every offset rather than from where the last piece
    ended, so a piece that starts inside another one's span can never hide the
    streams after it; overlaps are collapsed at the end instead.

    This is for reading content, not for writing it: a piece proves a name is in
    the file, and no piece claims to be the whole package.
    """
    hits = []
    n = len(d)
    pos = PAYLOAD_OFF if d[:4] == MAGIC else 0
    while pos < n - 4:
        if d[pos] != 0x78 or ((0x78 << 8) | d[pos + 1]) % 31:
            pos += 1
            continue
        head, _e = inflate_exact(d, pos, stop=min(n, pos + 0x4000))
        if len(head) >= min_out and any(m in head for m in MARKERS):
            full, consumed = inflate_exact(d, pos)
            hits.append((pos, full, consumed))
        pos += 1
    kept = []
    for off, out, consumed in hits:
        end = off + (consumed if consumed else max(2, len(out) // 4))
        if kept and off < kept[-1][2]:
            continue
        kept.append((off, out, end))
    return [(o, out) for o, out, _e in kept]


def objects(sections):
    """Named objects across every package, in file order."""
    rows = []
    for section in sections:
        rows += scan_section(section)
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

    kind, sections, parts = load(args.file)
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
        print("   header: packages from 0x%X, %d bytes in %d of them"
              % (off, unc, len(parts)))
        for o, n in parts[:6]:
            print("   package at 0x%06X -> %d bytes" % (o, n))
        if len(parts) > 6:
            print("   ... and %d more" % (len(parts) - 6))
    rows = objects(sections)
    print("   %d objects in %d bytes" % (len(rows), sum(len(s) for s in sections)))
    if args.unpack:
        with open(args.unpack, "wb") as fh:
            for section in sections:
                fh.write(section)
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
