#!/usr/bin/env python3
"""Roll a new track line-up for every cup.

The cups are not scripted - `Common.pkz` holds them as plain playlists:

    LandCupPlaylist / SeaCupPlaylist / SkyCupPlaylist       5 track ids
    L_/S_/A_RacePlayList_Multiplayer                         the same 5
    L_/S_/A_RacePlayList_Multiplayer_ActionPack              14 ids = the pool

Payload layout (type `27EB0086`), verified against the file:

    key:4  type:4  0:4  0x0004:2  count:2  ids[count]:4

and the object's `0x139C` table repeats the same ids as (0x15, id) pairs. So a
cup can be re-pointed at any track of its own terrain by rewriting the ids -
count, chunk length and file size stay identical, which is the only kind of edit
this disc accepts (see FINDINGS.md).

Tracks are grouped per terrain, and every terrain pool holds 7 circuits plus 7
mirror variants; `--mirrors` mixes the reversed versions in as well.

    tools/pkz_cup_random.py --seed 12 --print
    tools/pkz_cup_random.py --seed 12 --dry-run
"""
import argparse
import os
import random
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pkz_pool_swap as pw  # noqa: E402

ROOT = os.path.dirname(HERE)
TARGET = os.path.join(ROOT, "disc", "files", "Data", "Common.pkz")

# launcher terrain -> (playlist prefix, cup page name)
TERRAINS = {
    "land": ("L", "LandCupPlaylist"),
    "sea": ("S", "SeaCupPlaylist"),
    "air": ("A", "SkyCupPlaylist"),
}
PLAYLIST_TYPE = 0x27EB0086


def objects(d):
    out = {}
    for w in pw.wrappers(d):
        key, name, roff, rlen, doff, dlen = pw.read_wrapper(d, w)
        if name and key is not None and name not in out:
            out[name] = {"key": key, "ref_off": roff, "ref_len": rlen,
                         "data_off": doff, "data_len": dlen}
    return out


def read_list(d, rec):
    """(ids, ids_offset) of one playlist payload."""
    if rec["data_off"] is None:
        raise ValueError("playlist has no payload")
    body = rec["data_off"] + 16
    typ = struct.unpack_from(">I", d, body + 4)[0]
    if typ != PLAYLIST_TYPE:
        raise ValueError("unexpected playlist type 0x%08X" % typ)
    count = struct.unpack_from(">H", d, body + 14)[0]
    if rec["data_len"] != 16 + 4 * count:
        raise ValueError("payload length %d does not match count %d"
                         % (rec["data_len"], count))
    ids = list(struct.unpack_from(">%dI" % count, d, body + 16))
    return ids, body + 16


def write_list(d, rec, old, new):
    """Point one playlist at `new`, keeping the record's ref table in step."""
    ids, off = read_list(d, rec)
    if len(ids) != len(new):
        raise ValueError("cannot change the number of tracks in %s" % rec.get("name"))
    struct.pack_into(">%dI" % len(new), d, off, *new)
    if rec["ref_off"] is None:
        return
    mapping = {}
    for i, old_id in enumerate(ids):
        mapping.setdefault(old_id, new[i])
    for i in range(rec["ref_off"], rec["ref_off"] + rec["ref_len"], 8):
        word, value = struct.unpack_from(">II", d, i)
        if word == 0x15 and value in mapping:
            struct.pack_into(">I", d, i + 4, mapping[value])


def apply(src, seed, mirrors=False):
    """Return (patched bytes, [(terrain, cup, old ids, new ids, pool size)]).

    Same size, and a pure function of (file, seed) - a session code therefore
    gives both players the same cups, and rolling the same seed twice writes
    nothing new.
    """
    d = bytearray(src)
    objs = objects(src)
    rng = random.Random(seed)
    report = []
    for terrain, (prefix, cup_name) in TERRAINS.items():
        cup = objs.get(cup_name)
        pool_rec = objs.get("%s_RacePlayList_Multiplayer_ActionPack" % prefix)
        if cup is None or pool_rec is None:
            continue
        pool_ids, _ = read_list(src, pool_rec)
        # the pool is the circuits followed by their reversed versions, so the
        # split is by position - a few of these ids have no readable name and
        # a name test would let the mirror tracks through
        half = len(pool_ids) // 2
        keep = list(pool_ids) if mirrors else list(pool_ids[:half])
        if len(keep) < 5:
            continue

        old_ids, _ = read_list(src, cup)
        count = len(old_ids)
        pool = sorted(set(keep))
        picks = rng.sample(pool, min(count, len(pool)))
        report.append((terrain, cup_name, list(old_ids), picks, len(pool)))

        write_list(d, cup, old_ids, picks)
        # the multiplayer race list is the same five tracks; keep them together
        # so the cup page and the races it starts agree
        mp = objs.get("%s_RacePlayList_Multiplayer" % prefix)
        if mp is not None:
            mp_ids, _ = read_list(src, mp)
            if len(mp_ids) == count:
                write_list(d, mp, mp_ids, picks)

    out = bytes(d)
    if len(out) != len(src):
        raise RuntimeError("cup patch changed the file size")
    return out, report


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", default=TARGET)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--mirrors", action="store_true",
                    help="include the reversed (mirror) circuits in the pool")
    ap.add_argument("--print", dest="show", action="store_true",
                    help="show the id -> name table and the new line-ups")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    src = open(args.src, "rb").read()
    objs = objects(src)
    names = {r["key"]: n for n, r in objs.items()}

    if args.show:
        print("tracks per terrain")
        for terrain, (prefix, _) in TERRAINS.items():
            rec = objs.get("%s_RacePlayList_Multiplayer_ActionPack" % prefix)
            if rec is None:
                continue
            ids, _ = read_list(src, rec)
            print("  %-4s %s" % (terrain, ", ".join(
                names.get(i, "0x%08X" % i) for i in ids)))
        print()

    out, report = apply(src, args.seed, args.mirrors)
    for terrain, cup_name, old, new, n in report:
        print("%-4s %-18s pool %d -> %s" % (
            terrain, cup_name, n,
            ", ".join(names.get(i, "0x%08X" % i) for i in new)))
        if args.show:
            print("%-4s %-18s was    %s" % (
                "", "", ", ".join(names.get(i, "0x%08X" % i) for i in old)))

    diff = sum(1 for a, b in zip(src, out) if a != b)
    print("\n%d cup(s) rolled, %d bytes changed, size unchanged" % (len(report), diff))
    if args.dry_run:
        print("dry run - nothing written")
        return 0
    if not report:
        print("nothing to do")
        return 0
    open(args.src, "wb").write(out)
    print("wrote %s" % args.src)
    return 0


if __name__ == "__main__":
    sys.exit(main())
