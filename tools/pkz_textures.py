#!/usr/bin/env python3
"""List and export the textures inside a .pkz, as PNG.

Texture layout in this engine (all big-endian):

    0x0009  <-- texture group
    └─ 0x138D
       ├─ 0x138E  ResourceHeader: hash, asset type, name
       └─ 0x0191
          └─ 0x0197  TextureInfo: height, width, mips, format, cmp-size

The pixels are not there: they live in a `0x0026` asset of type 4, in its
`0x0195` child, and are linked to the TextureInfo by the ResourceHeader hash.

    0x0026 (asset)
    ├─ 0x138E  ResourceHeader (same hash)
    └─ 0x0195  pixel data

Format codes: 0 RGBA8, 1 IA8, 2 RGB5A3, 3 CMPR, 4 CMPR_A, 5 CMPR.

Usage:
    pkz_textures.py list  FrontScreen.pkz [--grep Portrait]
    pkz_textures.py extract FrontScreen.pkz -o out/textures [--grep Portrait]
    pkz_textures.py find  disc/files/Data --grep Portrait
"""
import argparse
import os
import re
import struct
import sys

import numpy as np
from PIL import Image

FORMAT_NAMES = {0: "RGBA8", 1: "IA8", 2: "RGB5A3", 3: "CMPR", 4: "CMPR_A", 5: "CMPR"}
FMT_RGBA8, FMT_IA8, FMT_RGB5A3 = 0, 1, 2


# ------------------------------------------------------------------ chunks
def children(buf, off):
    """Direct child chunks of the chunk at `off`, as (type, offset, size)."""
    _idw, _ver, _flags, _rsv, size = struct.unpack_from(">IHHII", buf, off)
    end = off + 16 + size
    out, p = [], off + 16
    while p + 16 <= end:
        idw, _ver, _flags, _rsv, csize = struct.unpack_from(">IHHII", buf, p)
        if not idw & 0x80000000 or p + 16 + csize > end:
            break
        out.append((idw & 0x7FFFFFFF, p, csize))
        p += 16 + csize
    return out


def find(kids, want):
    return next((k for k in kids if k[0] == want), None)


def resource_header(buf, off):
    """(hash, asset type, name) from a 0x138E payload."""
    p = off + 16
    h, atype = struct.unpack_from(">II", buf, p)
    name = buf[p + 28:p + 92].split(b"\x00", 1)[0].decode("latin1", "replace")
    return h, atype, name


def root_children(buf):
    return children(buf, 0)


def textures(buf):
    """Yield one dict per texture that has both metadata and pixel data."""
    payloads = {}
    for tid, off, _size in root_children(buf):
        if tid != 0x0026:
            continue
        kids = children(buf, off)
        hdr, pix = find(kids, 0x138E), find(kids, 0x0195)
        if hdr and pix:
            h, atype, _name = resource_header(buf, hdr[1])
            if atype == 4:
                payloads[h] = (pix[1] + 16, pix[2])

    for tid, off, _size in root_children(buf):
        if tid != 0x0009:
            continue
        for cid, coff, _csize in children(buf, off):
            if cid != 0x138D:
                continue
            sub = children(buf, coff)
            hdr, grp = find(sub, 0x138E), find(sub, 0x0191)
            if not hdr or not grp:
                continue
            h, _atype, name = resource_header(buf, hdr[1])
            info = find(children(buf, grp[1]), 0x0197)
            if not info or info[2] < 20:
                continue
            height, width, mips, fmt, csize = struct.unpack_from(">5I", buf, info[1] + 16)
            if h not in payloads:
                continue
            p_off, p_len = payloads[h]
            yield {
                "name": name, "hash": h, "w": width, "h": height,
                "mips": mips, "fmt": fmt, "csize": csize,
                "off": p_off, "len": p_len,
            }


# ---------------------------------------------------------------- decoders
def _detile(blocks, w, h, tw, th, ch):
    bw, bh = (w + tw - 1) // tw, (h + th - 1) // th
    img = blocks.reshape(bh, bw, th, tw, ch).transpose(0, 2, 1, 3, 4)
    return img.reshape(bh * th, bw * tw, ch)[:h, :w]


def _rgb565(c):
    r = ((c >> 11) & 31).astype(np.uint16)
    g = ((c >> 5) & 63).astype(np.uint16)
    b = (c & 31).astype(np.uint16)
    return np.stack([r * 255 // 31, g * 255 // 63, b * 255 // 31], -1).astype(np.uint8)


def decode_cmpr(buf, w, h):
    """GX CMPR: 8x8 macrotiles of four 4x4 DXT1 blocks, TL TR BL BR."""
    n = ((w + 7) // 8) * ((h + 7) // 8) * 4
    need = n * 8
    if len(buf) < need:
        raise ValueError("CMPR short: %d < %d" % (len(buf), need))
    a = np.frombuffer(buf[:need], np.uint8).reshape(n, 8)
    c0 = (a[:, 0].astype(np.uint16) << 8) | a[:, 1]
    c1 = (a[:, 2].astype(np.uint16) << 8) | a[:, 3]
    p0, p1 = _rgb565(c0).astype(np.int16), _rgb565(c1).astype(np.int16)
    opaque = c0 > c1
    pal = np.zeros((n, 4, 4), np.uint8)
    pal[:, 0, :3], pal[:, 0, 3] = p0, 255
    pal[:, 1, :3], pal[:, 1, 3] = p1, 255
    pal[:, 2, :3] = np.where(opaque[:, None], (2 * p0 + p1) // 3, (p0 + p1) // 2)
    pal[:, 3, :3] = np.where(opaque[:, None], (p0 + 2 * p1) // 3, 0)
    pal[:, 3, 3] = np.where(opaque, 255, 0)
    idx = a[:, 4:8]
    sel = np.stack([(idx >> 6) & 3, (idx >> 4) & 3, (idx >> 2) & 3, idx & 3], -1)
    tex = pal[np.arange(n)[:, None, None], sel]
    tex = tex.reshape(((w + 7) // 8) * ((h + 7) // 8), 2, 2, 4, 4, 4).transpose(0, 1, 3, 2, 4, 5)
    return _detile(tex.reshape(-1, 8, 8, 4), w, h, 8, 8, 4)


def decode_i8(buf, w, h):
    bw, bh = (w + 7) // 8, (h + 3) // 4
    need = bw * bh * 32
    if len(buf) < need:
        raise ValueError("I8 short: %d < %d" % (len(buf), need))
    a = np.frombuffer(buf[:need], np.uint8).reshape(bw * bh, 4, 8, 1)
    return _detile(a, w, h, 8, 4, 1)[:, :, 0]


def decode_rgb5a3(buf, w, h):
    bw, bh = (w + 3) // 4, (h + 3) // 4
    need = bw * bh * 32
    if len(buf) < need:
        raise ValueError("RGB5A3 short: %d < %d" % (len(buf), need))
    c = np.frombuffer(buf[:need], dtype=">u2").reshape(-1)
    out = np.zeros((c.size, 4), np.uint8)
    op = (c & 0x8000) != 0
    out[op, 0] = ((c[op] >> 10) & 31) * 255 // 31
    out[op, 1] = ((c[op] >> 5) & 31) * 255 // 31
    out[op, 2] = (c[op] & 31) * 255 // 31
    out[op, 3] = 255
    out[~op, 0] = ((c[~op] >> 8) & 15) * 17
    out[~op, 1] = ((c[~op] >> 4) & 15) * 17
    out[~op, 2] = (c[~op] & 15) * 17
    out[~op, 3] = ((c[~op] >> 12) & 7) * 255 // 7
    return _detile(out.reshape(bw * bh, 4, 4, 4), w, h, 4, 4, 4)


def decode_ia8(buf, w, h):
    bw, bh = (w + 3) // 4, (h + 3) // 4
    need = bw * bh * 32
    if len(buf) < need:
        raise ValueError("IA8 short: %d < %d" % (len(buf), need))
    a = np.frombuffer(buf[:need], np.uint8).reshape(bw * bh, 4, 4, 2)
    out = np.zeros((bw * bh, 4, 4, 4), np.uint8)
    out[..., 0] = out[..., 1] = out[..., 2] = a[..., 1]
    out[..., 3] = a[..., 0]
    return _detile(out, w, h, 4, 4, 4)


def decode_rgba8(buf, w, h):
    bw, bh = (w + 3) // 4, (h + 3) // 4
    need = bw * bh * 64
    if len(buf) < need:
        raise ValueError("RGBA8 short: %d < %d" % (len(buf), need))
    a = np.frombuffer(buf[:need], np.uint8).reshape(bw * bh, 2, 4, 4, 2)
    out = np.zeros((bw * bh, 4, 4, 4), np.uint8)
    out[..., 3], out[..., 0] = a[:, 0, :, :, 0], a[:, 0, :, :, 1]
    out[..., 1], out[..., 2] = a[:, 1, :, :, 0], a[:, 1, :, :, 1]
    return _detile(out, w, h, 4, 4, 4)


def decode(buf, t):
    payload = buf[t["off"]:t["off"] + t["len"]]
    fmt = t["fmt"]
    if fmt in (3, 4, 5):
        img = decode_cmpr(payload, t["w"], t["h"])
        if fmt == 4:
            alpha = decode_i8(payload[t["csize"]:], t["w"], t["h"])
            if alpha.shape == img.shape[:2]:
                img = img.copy()
                img[:, :, 3] = alpha
        return img
    if fmt == FMT_RGB5A3:
        return decode_rgb5a3(payload, t["w"], t["h"])
    if fmt == FMT_IA8:
        return decode_ia8(payload, t["w"], t["h"])
    if fmt == FMT_RGBA8:
        return decode_rgba8(payload, t["w"], t["h"])
    raise NotImplementedError("format %d" % fmt)


# -------------------------------------------------------------------- main
SAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def safe(name):
    return SAFE.sub("_", name).strip(" .") or "unnamed"


def load(path):
    return open(path, "rb").read()


def cmd_list(args):
    buf = load(args.pkz)
    rx = re.compile(args.grep, re.I) if args.grep else None
    n = 0
    for t in textures(buf):
        if rx and not rx.search(t["name"]):
            continue
        n += 1
        print("%-58s %4dx%-4d %-7s mips=%d" % (t["name"][:58], t["w"], t["h"],
                                               FORMAT_NAMES.get(t["fmt"], "?%d" % t["fmt"]),
                                               t["mips"]))
    print("-- %d texture(s)" % n)
    return 0


def cmd_extract(args):
    buf = load(args.pkz)
    rx = re.compile(args.grep, re.I) if args.grep else None
    os.makedirs(args.out, exist_ok=True)
    n = skipped = 0
    for t in textures(buf):
        if rx and not rx.search(t["name"]):
            continue
        try:
            img = decode(buf, t)
        except Exception as e:  # noqa: BLE001 - report and keep going
            skipped += 1
            print("  skip %-40s %s" % (t["name"][:40], e), file=sys.stderr)
            continue
        path = os.path.join(args.out, "%s.png" % safe(t["name"]))
        Image.fromarray(img, "RGBA").save(path)
        n += 1
    print("wrote %d png(s) to %s (%d skipped)" % (n, args.out, skipped))
    return 0


def cmd_find(args):
    rx = re.compile(args.grep, re.I)
    files = []
    if os.path.isdir(args.pkz):
        files = [os.path.join(args.pkz, f) for f in sorted(os.listdir(args.pkz))
                 if f.lower().endswith(".pkz")]
    else:
        files = [args.pkz]
    total = 0
    for f in files:
        try:
            buf = load(f)
        except OSError:
            continue
        hits = [t for t in textures(buf) if rx.search(t["name"])]
        if hits:
            total += len(hits)
            print("%s: %d" % (os.path.basename(f), len(hits)))
            for t in hits[:args.show]:
                print("   %-56s %4dx%-4d %s" % (t["name"][:56], t["w"], t["h"],
                                                FORMAT_NAMES.get(t["fmt"], "?")))
    print("-- %d match(es) in %d file(s)" % (total, len(files)))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="print every texture in a .pkz")
    p.add_argument("pkz")
    p.add_argument("--grep")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("extract", help="decode textures to PNG")
    p.add_argument("pkz")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--grep")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("find", help="search textures by name across .pkz files")
    p.add_argument("pkz", help="a .pkz file or a directory of them")
    p.add_argument("--grep", required=True)
    p.add_argument("--show", type=int, default=8, help="examples per file")
    p.set_defaults(func=cmd_find)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
