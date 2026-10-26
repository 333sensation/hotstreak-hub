#!/usr/bin/env python3
"""Join the figure catalogue to the art extracted from the disc.

Figures come from `BaseSkylander.pkz` (the catalogue object that carries the
charId a `RacerAIInfo` points at); art comes from `assets/art.json`, written by
`tools/extract_art.py`. The big `ICON_Portrait_<Figure>_Large_DA` art is
preferred over the 64x64 HUD portrait, variants (S1/S2/EE/...) fall back to the
base figure.
"""
import difflib
import hashlib
import json
import os
import re
import struct
import sys
from functools import lru_cache

from PIL import Image

import roster as R

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ASSETS = os.path.join(HERE, "assets")
CACHE = os.path.join(HERE, "cache")


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _art_index():
    art = json.load(open(os.path.join(ASSETS, "art.json")))
    out = {}
    for key, info in art.items():
        rel = info.get("portrait")
        if not rel:
            continue
        path = os.path.join(ASSETS, rel)
        try:
            with Image.open(path) as im:
                size = im.size[0]
        except OSError:
            continue
        out[key] = {"key": key, "path": rel, "size": size}
    return out


def _pick(art, name):
    """Best art for a figure name.

    Exact name, then variant (`Bash_S1`), then the `Villain` spelling the game
    uses for its bosses, then the closest name by similarity (the catalogue and
    the texture names disagree about a few spellings, e.g. `Bushwhack` vs
    `Bushwack`, `PainYata` vs `PainYatta`).
    """
    want = norm(re.sub(r"^Driver", "", name))
    plain = norm(R.base_name(re.sub(r"^Driver", "", name)))
    idx = {}                       # normalised name -> art entries
    for k, a in art.items():
        n = norm(k)
        idx.setdefault(n, []).append(a)
        idx.setdefault(re.sub(r"^villain", "", n), []).append(a)

    def best(cands):
        cands.sort(key=lambda a: (-a["size"], len(a["key"])))
        return cands[0]["path"]

    for probe in (want, "villain" + want, plain):
        if probe in idx:
            return best(list(idx[probe]))
    for probe in (want, "villain" + want, plain):
        cands = [a for n, v in idx.items() if n.startswith(probe) or probe.startswith(n)
                 for a in v]
        if cands:
            return best(cands)
    close = difflib.get_close_matches(want, list(idx), n=4, cutoff=0.84)
    for c in close:
        cands = [a for n, v in idx.items() if n == c or n.startswith(c) for a in v]
        if cands:
            return best(cands)
    return None


def build(force=False):
    """figures: [{name, display, key, art, group}] - cached on the pkz hashes."""
    gp_path = os.path.join(ROOT, "disc", "files", "Data", "BaseGameplay.pkz")
    cat_path = os.path.join(ROOT, "disc", "files", "Data", "BaseSkylander.pkz")
    stamp = hashlib.sha1()
    stamp.update(b"catalog-v5")   # bump when the join/filtering changes
    for p in (gp_path, cat_path):
        with open(p, "rb") as f:
            stamp.update(hashlib.sha1(f.read()).digest())
    stamp.update(json.dumps(sorted(_art_index())).encode())
    cache_path = os.path.join(CACHE, "figures.json")
    os.makedirs(CACHE, exist_ok=True)
    if not force and os.path.exists(cache_path):
        try:
            cached = json.load(open(cache_path))
            if cached.get("stamp") == stamp.hexdigest():
                return cached
        except (ValueError, OSError):
            pass

    cat = open(cat_path, "rb").read()
    gameplay = open(gp_path, "rb").read()
    art = _art_index()
    slot_list = R.slots(gameplay)
    with_stats = R.stats_backed(cat)

    figs = []
    for name, key in R.figures(cat):
        disp = R.display(name)
        if disp == "Greeble":      # test dummy the rentals are built on
            continue
        figs.append({
            "name": name,
            "display": disp,
            "base": R.display(R.base_name(name)),
            "key": key,
            "stats": name in with_stats,
            "art": _pick(art, disp),
            "group": norm(disp),
        })

    data = {
        "stamp": stamp.hexdigest(),
        "figures": figs,
        "slots": [
            {"info": s["info"], "terrain": s["terrain"], "kind": s["kind"],
             "slot": s["slot"]}
            for s in slot_list
        ],
        "terrain_counts": {
            t: sum(1 for s in slot_list if s["terrain"] == t)
            for t in ("air", "land", "sea")
        },
    }
    json.dump(data, open(cache_path, "w"), indent=1)
    return data


if __name__ == "__main__":
    d = build(force=True)
    figs = d["figures"]
    print("figures %d, with art %d, slots %d %s"
          % (len(figs), sum(1 for f in figs if f["art"]), len(d["slots"]),
             d["terrain_counts"]))
    for f in figs:
        if not f["art"]:
            print("  no art:", f["display"])
