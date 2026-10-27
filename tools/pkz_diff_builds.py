#!/usr/bin/env python3
"""Compare the 3DS build's data against the Wii disc, to see what the Wii lacks.

Both builds ship the same 782 file names, so anything the 3DS has and the Wii does
not is *inside* a file. Finding it is not a straight object walk, because the two
containers are not read the same way:

* the Wii files are big-endian roceGS containers that `pkz_pool_swap` and
  `pkz_objects` parse object for object;
* a 3DS file is a header, a per-0x4000-block package map at 0x30, a package count
  at 0x20, and then one zlib stream per package whose output is a *piece* of the
  little-endian roceGS stream. The map's rows do not line up with the stream
  starts for every file (`Common.pkz` lines up for 53 of its 112 packages), so the
  reader here uses `pkz_3ds.recover()`, which keeps every zlib stream whose output
  carries roceGS structure regardless of where the map says packages are.

A name found that way is then tested against the *whole* Wii data tree, not just
the matching file: a name that is only missing from one Wii file is usually just
that file's business, and only a name absent from all 786 files is something the
Wii build genuinely does not have.

Usage:
    pkz_diff_builds.py                    # multiplayer-relevant names, all files
    pkz_diff_builds.py FrontScreen.pkz    # just this file, still checked globally
    pkz_diff_builds.py --playlists        # cups and multiplayer playlists, both builds
    pkz_diff_builds.py --keyword "Online" # narrow the report
    pkz_diff_builds.py --list-files       # the file-name diff
    pkz_diff_builds.py --d3-root DIR --wii-root DIR
"""
import argparse
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pkz_3ds as P3                      # noqa: E402
import pkz_cup_random as CR               # noqa: E402
import pkz_objects as PO                  # noqa: E402
import pkz_pool_swap as pw                # noqa: E402

ROOT = os.path.dirname(HERE)
WII_DATA = os.path.join(ROOT, "disc", "files", "Data")
WII_PRISTINE_CUPS = os.path.join(ROOT, "backups", "Common.pkz.pristine")
D3_DATA = os.path.expanduser(
    "~/Library/Application Support/AzaharPlus/dump/romfs/"
    "0004000000165E00/Data")

ID = re.compile(rb"^[A-Za-z][A-Za-z0-9_]{3,60}$")
RUN = re.compile(rb"[A-Za-z][A-Za-z0-9_]{3,60}")
MULTI = re.compile(r"(Multi|Split|Player|Online|Cup|Race|Toy|HUD|Portal|Signal)", re.I)
DEFAULT_FILES = ("FrontScreen.pkz", "MultiplayerHuds.pkz", "Common.pkz",
                 "BaseGameplay.pkz")


def d3_names(path):
    """Names in a 3DS file, read from every piece that survives the recovery walk."""
    out = set()
    for _off, piece in P3.recover(open(path, "rb").read()):
        for w in P3.wrappers(piece):
            nm = P3.read_wrapper(piece, w)[1]
            if nm and ID.match(nm.encode("latin1", "ignore")):
                out.add(nm)
        for _k, nm, *_r in P3.objects([piece]):
            if nm and ID.match(nm.encode("latin1", "ignore")):
                out.add(nm)
    return out


def wii_names(path):
    """Names in one Wii file, both ways this repo reads them."""
    raw = open(path, "rb").read()
    out = set()
    for w in pw.wrappers(raw):
        nm = pw.read_wrapper(raw, w)[1]
        if nm and ID.match(nm.encode("latin1", "ignore")):
            out.add(nm)
    for o in PO.parse_objects(path):
        if ID.match(o.name.encode("latin1", "ignore")):
            out.add(o.name)
    return out


def wii_tree_has(root, wanted):
    """(still_missing, names_seen) after scanning every file for `wanted`.

    Every identifier run in every file is a candidate, not just the objects a walk
    resolves: the question is whether the *string* exists on the Wii at all, and a
    looser search can only make an absence claim harder to hold.
    """
    missing = set(wanted)
    seen = 0
    for fn in sorted(os.listdir(root)):
        p = os.path.join(root, fn)
        if not os.path.isfile(p):
            continue
        try:
            raw = open(p, "rb").read()
        except OSError:
            continue
        found = {m.group(0).decode("latin1") for m in RUN.finditer(raw)}
        seen += len(found)
        missing -= found
        if not missing:
            break
    return missing, seen


def playlists_3ds(path):
    """Every track list in a 3DS file, as the ids it holds."""
    blob = b"".join(p for _o, p in P3.recover(open(path, "rb").read()))
    sig = struct.pack("<I", CR.PLAYLIST_TYPE)
    out = []
    for m in range(len(blob)):
        if not blob.startswith(sig, m):
            continue
        i = m - 4                      # the record's key word sits before the type
        count = struct.unpack_from("<H", blob, i + 14)[0]
        if 1 <= count <= 32 and i + 16 + 4 * count <= len(blob):
            out.append(list(struct.unpack_from("<%dI" % count, blob, i + 16)))
    return out


def playlists_wii(path):
    """{name: ids} for every track list on the Wii side."""
    raw = open(path, "rb").read()
    out = {}
    for name, rec in CR.objects(raw).items():
        try:
            out[name] = CR.read_list(raw, rec)[0]
        except Exception:
            continue
    return out


def main():
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="data file names (default: the "
                                             "multiplayer-relevant ones)")
    ap.add_argument("--playlists", action="store_true",
                    help="compare the cups and multiplayer playlists")
    ap.add_argument("--wii-cups", default=WII_PRISTINE_CUPS,
                    help="Wii Common.pkz to compare the cups against "
                         "(default: the pristine backup, since the working file's "
                         "cups are rolled per play by the launcher)")
    ap.add_argument("--list-files", action="store_true")
    ap.add_argument("--keyword", default=None,
                    help="only report names matching this (default: multiplayer)")
    ap.add_argument("--all-names", action="store_true",
                    help="report every 3DS-only name, not just the keyword hits")
    ap.add_argument("--wii-root", dest="wii_root", default=WII_DATA)
    ap.add_argument("--d3-root", dest="d3_root", default=D3_DATA)
    args = ap.parse_args()

    if args.list_files:
        wii_all = sorted(os.listdir(args.wii_root))
        d3_all = sorted(os.listdir(args.d3_root))
        print("file names: Wii %d, 3DS %d, only on 3DS %d, only on Wii %d"
              % (len(wii_all), len(d3_all),
                 len([n for n in d3_all if n not in wii_all]),
                 len([n for n in wii_all if n not in d3_all])))
        for n in wii_all:
            if n not in d3_all:
                print("   only Wii: %s" % n)
        for n in d3_all:
            if n not in wii_all:
                print("   only 3DS: %s" % n)

    if args.playlists:
        tds = playlists_3ds(os.path.join(args.d3_root, "Common.pkz"))
        wwii = playlists_wii(args.wii_cups)
        print("playlists: 3DS %d records, Wii %d records (%s)"
              % (len(tds), len(wwii), os.path.relpath(args.wii_cups, ROOT)))
        left = list(tds)
        for name in sorted(wwii):
            ids = wwii[name]
            hit = next((k for k, v in enumerate(left) if v == ids), None)
            print("   %-44s %2d ids  %s"
                  % (name, len(ids), "identical 3DS record" if hit is not None
                     else "NO identical 3DS record"))
            if hit is not None:
                left.pop(hit)
        print("   3DS records with no identical Wii record: %d" % len(left))
        for v in left:
            print("      %s" % " ".join("%08X" % x for x in v))

    if args.files or not (args.list_files or args.playlists):
        files = args.files or list(DEFAULT_FILES)
        keyword = MULTI if args.keyword is None else re.compile(args.keyword, re.I)
        cands = {}
        for fn in files:
            p = os.path.join(args.d3_root, fn)
            if not os.path.exists(p):
                print("%s: not in the 3DS dump" % fn)
                continue
            wp = os.path.join(args.wii_root, fn)
            here = d3_names(p)
            in_file = here - (wii_names(wp) if os.path.exists(wp) else set())
            cands[fn] = {n for n in in_file if keyword.search(n)}
            print("%-22s %5d names read on the 3DS | %4d not in the same Wii file"
                  % (fn, len(here), len(in_file)))

        wanted = set().union(*cands.values()) if cands else set()
        print("\nchecking %d candidate names against all %d Wii data files..."
              % (len(wanted), len(os.listdir(args.wii_root))))
        missing, seen = wii_tree_has(args.wii_root, wanted)
        print("scanned %d identifier runs; %d of the candidates are absent from "
              "the whole Wii build\n" % (seen, len(missing)))
        for fn in files:
            if fn not in cands:
                continue
            gone = sorted(cands[fn] & missing)
            print("== %s: %d absent from the Wii build ==" % (fn, len(gone)))
            for n in gone:
                print("   + %s" % n)
        print("\n(total 3DS-only names, keyword-filtered: %d)" % len(missing))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
