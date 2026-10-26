#!/usr/bin/env python3
"""Fit every racer the disc has (20 drivers + 14 villains) into every AI pool.

`.pkz` is a chunk tree, and every object is serialised with an explicit length
plus a per-object reference table, so growing one object means:

    data chunk 0x1391      + 14 records * 16 bytes
    ref table   0x139C     + 14 refs    *  8 bytes   ("00000015 <key>")
    0x0C81 wrapper         + data delta
    object wrapper 0x138D  + data delta + ref delta
    group 0x80000032       + data delta + ref delta
    root 0x80000001        + data delta + ref delta

The reference table is not optional: on the shipped file it holds exactly the
set of keys found in the object's data (verified for every `RacerAIList`), which
is how the loader resolves ids to objects.

Pool body layout (`RacerAIList`, type 0xCAFB9B03):

    +00 own id | +04 type | +08 0 | +0C u16 0x14, u16 count
    +10 0 | +14 0x000C, +16 0x0014 | +18 record[0] ... record[n]
    record = u32 word | u32 key | u32 owner | u32 shared (0x91284605)
    the last record is stored truncated (word + key only)

Header fields are left untouched: `maxRacers` is 0x14 in *every* pool including
the one-entry ones, so it is a config constant, not the entry count -- the entry
count follows the payload length, which is what this tool updates.

Reads `BaseGameplay.pkz.orig` (pristine) so it is idempotent, and grows all four
driver pools, keeping each ref table in sync with its data.
"""
import argparse
import re
import struct
import sys

DATA_TAG = b"\x80\x00\x13\x91\x00\x08\x00\x00\x00\x00"
DATA_CHUNK = 0x80001391
REF_CHUNK = 0x8000139C
REF_TAG = b"\x80\x00\x13\x9c"
ROOT_TAG = 0x80000001
LIST_TYPE = 0xCAFB9B03
SHARED = 0x91284605
DRIVER_RE = re.compile(r"^Driver(.+)_(Land|Air|Sea)_AIInfo$")

GROW_TARGETS = (
    "EnemyAIList_Land_ActionPack",
    "EnemyAIList_Land_StarterPack_SheepHerder",
    "EnemyAIList_Sea_ActionPack",
    "ActionPackPersonalityList",
)


# ---------------------------------------------------------------- chunk tree
def child_chunks(d, start, end):
    o = start
    while o + 16 <= end:
        tag = struct.unpack_from(">I", d, o)[0]
        if tag >> 16 != 0x8000:
            return
        ln = struct.unpack_from(">I", d, o + 12)[0]
        yield o, tag, o + 16, ln
        o += 16 + ln


def path_to(d, target):
    out, o, end = [], 0, len(d)
    while True:
        found = None
        for off, tag, ps, ln in child_chunks(d, o, end):
            if off <= target < off + 16 + ln:
                found = (off, tag, ps, ln)
                break
        if found is None:
            return out
        out.append(found)
        o, end = found[2], found[0] + 16 + found[3]


def tiles(d, start, end):
    """True if chunk headers starting at `start` land exactly on `end`."""
    o = start
    while o < end:
        if o + 16 > end:
            return False
        if struct.unpack_from(">I", d, o)[0] >> 16 != 0x8000:
            return False
        o += 16 + struct.unpack_from(">I", d, o + 12)[0]
    return o == end


def tree_ok(d, path=()):
    """Root must cover the file, and every chunk on `path` must tile its payload."""
    ln = struct.unpack_from(">I", d, 12)[0]
    if ln != len(d) - 16:
        return "root length %d != filesize-16 %d" % (ln, len(d) - 16)
    if not tiles(d, 16, len(d)):
        return "top-level chunks do not tile the file"
    for off, tag, ps, ln2 in path:
        if ln2 < 16 or struct.unpack_from(">I", d, ps)[0] >> 16 != 0x8000:
            continue  # leaf payload (data / ref table / key chunk)
        if not tiles(d, ps, ps + ln2):
            return "chunk 0x%X (tag %08X) does not tile its payload" % (off, tag)
    return None


# ------------------------------------------------------------------- objects
def objects(d):
    for m in re.finditer(re.escape(DATA_TAG), d):
        s = m.start()
        ln = struct.unpack_from(">I", d, s + 12)[0]
        typ = struct.unpack_from(">I", d, s + 20)[0]
        end = d.find(b"\x80\x00\x13\x8d", s)
        if end < 0:
            continue
        nm = re.search(rb"[ -~]{2,80}\x00", d[end:end + 0x100])
        if not nm:
            continue
        yield s, typ, s + 16, ln, nm.group(0)[:-1].decode("latin1")


def obj_key(d, off):
    seg = d[off:off + 0x800]
    m = re.search(rb"\x80\x00\x13\x8e", seg)
    if not m or m.start() + 0x14 > len(seg):
        return None
    return struct.unpack_from(">I", seg, m.start() + 0x10)[0]


def ref_chunk(d, s):
    """Nearest 0x139C reference chunk that ends at or before the data chunk."""
    lo = max(0, s - 0x400)
    for m in reversed([m.start() + lo for m in re.finditer(re.escape(REF_TAG), d[lo:s])]):
        ln = struct.unpack_from(">I", d, m + 12)[0]
        if m + 16 + ln <= s and ln % 8 == 0 and ln < 0x1000:
            return m, ln
    return None, 0


def data_keys(body):
    if len(body) < 0x1C:
        return []
    return [struct.unpack_from(">I", body, i + 4)[0]
            for i in range(0x18, len(body) - 7, 16)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="disc/files/Data/BaseGameplay.pkz.orig")
    ap.add_argument("--dst", default="disc/files/Data/BaseGameplay.pkz")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    raw = open(args.src, "rb").read()
    print("source %s: %d bytes, tree %s" % (args.src, len(raw), tree_ok(raw) or "OK"))

    objs = list(objects(raw))
    drivers, villains = {}, {}
    for s, typ, bs, ln, name in objs:
        if typ != 0x45BA524C:
            continue
        key = obj_key(raw, s)
        if key is None:
            continue
        m = DRIVER_RE.match(name)
        if m:
            drivers.setdefault(m.group(1), {})[m.group(2).lower()] = key
        elif name.endswith("Info") and not name.endswith("_AIInfo"):
            villains[key] = name
    villain_keys = sorted(villains)
    print("drivers: %d (keys)  villains: %d" % (len(drivers), len(villain_keys)))

    d = bytearray(raw)
    key2driver = {(drv, terr): k for drv, t in drivers.items() for terr, k in t.items()}
    key_owner = {k: (drv, terr) for (drv, terr), k in key2driver.items()}

    for name in GROW_TARGETS:
        # offsets move after every growth, so re-parse each time
        cur = bytes(d)
        found = [o for o in objects(cur) if o[4] == name and o[1] == LIST_TYPE]
        if not found:
            print("error: %s not found" % name, file=sys.stderr)
            return 1
        s, typ, bs, blen, _ = found[0]
        be = bs + blen
        body = cur[bs:be]
        rk, rlen = ref_chunk(cur, s)
        if rk is None:
            print("error: no 0x139C ref table before %s" % name, file=sys.stderr)
            return 1
        if (blen - 0x18) % 16 != 8:
            print("error: %s has unexpected body shape" % name, file=sys.stderr)
            return 1
        have = data_keys(body)
        # keep one entry per character: add the missing characters with the
        # terrain variant this pool already uses (all its entries share one),
        # then every villain.
        seen = {drv for drv, t in drivers.items() if any(k in have for k in t.values())}
        terrains = [key_owner[k][1] for k in have if k in key_owner]
        terrain = max(set(terrains), key=terrains.count) if terrains else "land"
        missing = [key2driver[(drv, terrain)] if (drv, terrain) in key2driver
                   else sorted(drivers[drv].values())[0]
                   for drv in sorted(drivers) if drv not in seen]
        new_keys = missing + [k for k in villain_keys if k not in have]
        print("\n%s @0x%X body=%d entries=%d refs=%d" % (name, s, blen, len(have), rlen // 8))
        if not new_keys:
            print("  already complete (%d entries)" % len(have))
            continue
        rec_blob = b"".join(struct.pack(">4I", 0, k, struct.unpack_from(">I", body, 0)[0], SHARED)
                            for k in new_keys)
        ref_blob = b"".join(b"\x00\x00\x00\x15" + struct.pack(">I", k) for k in new_keys)
        print("  +%d records (%d B) into data, +%d refs (%d B) into the table"
              % (len(new_keys), len(rec_blob), len(new_keys), len(ref_blob)))
        chain = path_to(cur, s)
        for off, tag, ps, ln in chain:
            extra = len(rec_blob) + len(ref_blob)
            if tag == DATA_CHUNK:
                extra = len(rec_blob)
            print("    +0x%06X tag=%08X len=%-7d -> %d" % (off, tag, ln, ln + extra))
        if not args.apply:
            continue

        # 1. lengths first (all these offsets precede the insertions)
        for off, tag, ps, ln in chain:
            add = len(rec_blob) + len(ref_blob)
            if tag == DATA_CHUNK:
                add = len(rec_blob)
            elif tag == REF_CHUNK:
                add = len(ref_blob)
            struct.pack_into(">I", d, off + 12, ln + add)
        struct.pack_into(">I", d, rk + 12, rlen + len(ref_blob))
        # 2. insert, highest offset first so earlier offsets stay valid
        d[be - 8:be - 8] = rec_blob          # keep the truncated record last
        d[rk + 16 + rlen:rk + 16 + rlen] = ref_blob

    if not args.apply:
        print("\ndry run - pass --apply to write")
        return 0

    # verify
    out = bytes(d)
    print("\nerrors: tree %s" % (tree_ok(out) or "OK"))
    bad = []
    checked = 0
    for s3, typ3, bs3, blen3, name3 in objects(out):
        if typ3 != LIST_TYPE:
            continue
        keys = data_keys(out[bs3:bs3 + blen3])
        rk3, rlen3 = ref_chunk(out, s3)
        if rk3 is None:
            bad.append((name3, -1))
            continue
        refs = {struct.unpack_from(">I", out, j + 4)[0] for j in range(rk3 + 16, rk3 + 16 + rlen3, 8)}
        checked += 1
        if not set(keys) <= refs:
            bad.append((name3, len(set(keys) - refs)))
    print("RacerAIList objects with data keys missing from their ref table: %d of %d"
          % (len(bad), checked))
    for n, c in bad[:5]:
        print("   %s (%s missing)" % (n, c))
    for name in GROW_TARGETS:
        o = [x for x in objects(out) if x[4] == name][0]
        keys = data_keys(out[o[2]:o[2] + o[3]])
        print("%-44s entries=%d unique=%d" % (name, len(keys), len(set(keys))))
    if bad or tree_ok(out):
        print("error: verification failed, not writing", file=sys.stderr)
        return 1
    open(args.dst, "wb").write(out)
    print("\nwrote %s (%d bytes, +%d)" % (args.dst, len(out), len(out) - len(raw)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
