#!/usr/bin/env python3
"""Pull the game's own 2D art out of the disc: character portraits and menu art.

The character files carry `ICON_Portrait_<Figure>_<Variant>_DA` (64x64, CMPR_A)
and `ICON_Minimap_<Figure>_<Variant>_DA` (32x32) textures next to the model, so
every figure we can field has real artwork on the disc. `FrontScreen.pkz` holds
the front-end backgrounds.

    tools/extract_art.py                       # extract into launcher/assets/
    tools/extract_art.py --data OTHER_DIR --out OTHER_DIR
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pkz_textures as tx

from PIL import Image

PORTRAIT_RE = re.compile(r"^ICON_Portrait_(.+?)_DA$", re.I)
MINIMAP_RE = re.compile(r"^ICON_Minimap_(.+?)_DA$", re.I)
# variants shipped per figure, most wanted first
VARIANT_RANK = ("", "_S1", "_S2", "_S3", "_EE", "_LG", "_Dark", "_Main")


def figure_of(stem):
    """'Spyro_S2' -> ('Spyro', 'S2'); 'VillainWolfgang' -> ('VillainWolfgang', '')."""
    m = re.match(r"^(.*?)_(S\d|EE|LG|Dark|Main|Nitro|Volcanic|Polar|Royal|Series\d|"
                 r"MegaRam|Springtime|Ninja|QuickDraw|Enchanted|Elite)$", stem)
    if m:
        return m.group(1), m.group(2)
    return stem, ""


def rank(stem):
    fig, var = figure_of(stem)
    if not var:
        return 0
    for i, v in enumerate(VARIANT_RANK):
        if v.lstrip("_") == var:
            return i + 1
    return 99


def extract(data_dir, out_dir):
    files = sorted(f for f in os.listdir(data_dir) if f.lower().endswith(".pkz"))
    pdir = os.path.join(out_dir, "portraits")
    mdir = os.path.join(out_dir, "minimaps")
    os.makedirs(pdir, exist_ok=True)
    os.makedirs(mdir, exist_ok=True)

    best = {}      # figure -> (rank, png bytes, source)
    mini = {}
    for fn in files:
        path = os.path.join(data_dir, fn)
        try:
            buf = open(path, "rb").read()
            found = list(tx.textures(buf))
        except Exception:  # noqa: BLE001 - a broken pkz shouldn't stop the sweep
            continue
        for t in found:
            m = PORTRAIT_RE.match(t["name"]) or MINIMAP_RE.match(t["name"])
            if not m:
                continue
            stem = m.group(1)
            fig, _var = figure_of(stem)
            bucket = best if t["name"].lower().startswith("icon_portrait") else mini
            r = rank(stem)
            if fig in bucket and bucket[fig][0] <= r:
                continue
            try:
                img = tx.decode(buf, t)
            except Exception:  # noqa: BLE001
                continue
            bucket[fig] = (r, img, "%s:%s" % (fn, t["name"]))

    manifest = {}
    for fig, (r, img, src) in sorted(best.items()):
        p = os.path.join(pdir, "%s.png" % tx.safe(fig))
        Image.fromarray(img, "RGBA").save(p)
        manifest[fig] = {"portrait": "portraits/%s.png" % tx.safe(fig), "source": src}
    for fig, (r, img, src) in sorted(mini.items()):
        p = os.path.join(mdir, "%s.png" % tx.safe(fig))
        Image.fromarray(img, "RGBA").save(p)
        if fig in manifest:
            manifest[fig]["minimap"] = "minimaps/%s.png" % tx.safe(fig)

    with open(os.path.join(out_dir, "art.json"), "w") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
    print("portraits: %d   minimaps: %d   -> %s" % (len(best), len(mini), out_dir))
    return manifest


def extract_backgrounds(data_dir, out_dir, min_px=512, limit=24):
    """Big textures from the front-end, usable as launcher backdrops."""
    bdir = os.path.join(out_dir, "bg")
    os.makedirs(bdir, exist_ok=True)
    kept = []
    for fn in ("FrontScreen.pkz", "MultiplayerHuds.pkz"):
        path = os.path.join(data_dir, fn)
        if not os.path.exists(path):
            continue
        buf = open(path, "rb").read()
        for t in tx.textures(buf):
            if max(t["w"], t["h"]) < min_px or t["w"] < t["h"]:
                continue
            try:
                img = tx.decode(buf, t)
            except Exception:  # noqa: BLE001
                continue
            p = os.path.join(bdir, "%s.png" % tx.safe(t["name"]))
            Image.fromarray(img, "RGBA").save(p)
            kept.append((os.path.getsize(p), t["name"], t["w"], t["h"]))
    kept.sort(reverse=True)
    for sz, name, w, h in kept[:limit]:
        print("  bg %-46s %4dx%-4d %6.1f MB" % (name, w, h, sz / 1e6))
    print("backgrounds: %d candidates (all kept)" % len(kept))
    return kept


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--data", default=os.path.join(here, "disc", "files", "Data"))
    ap.add_argument("--out", default=os.path.join(here, "launcher", "assets"))
    ap.add_argument("--no-bg", action="store_true")
    args = ap.parse_args()
    extract(args.data, args.out)
    if not args.no_bg:
        extract_backgrounds(args.data, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
