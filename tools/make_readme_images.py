#!/usr/bin/env python3
"""Compose the README images out of the disc's own artwork.

Every pixel comes from the game: the title logo, the front-screen background and
the `_Large` character portraits that `tools/extract_art.py` pulls out of the
`.pkz` files. Nothing is drawn by hand, so the README shows what the disc ships.

    python3 tools/make_readme_images.py
    python3 tools/make_readme_images.py --assets launcher/assets --out docs
"""
import argparse
import json
import os

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

BG_COLOUR = (8, 11, 18, 255)          # the launcher's background colour
LINE = (28, 39, 64, 255)

# Recognisable figures first; whatever is on the disc fills the rest of the grid.
PREFERRED = [
    "Spyro", "Eruptor", "StealthElf", "GillGrunt", "TriggerHappy", "ChopChop",
    "Bash", "Terrafin", "Whirlwind", "SonicBoom", "Hex", "Cynder", "Drobot",
    "PrismBreak", "Zook", "DoubleTrouble", "Warnado", "Camo", "Sunburn",
    "Voodood", "GhostRoaster", "Boomer", "StumpSmash", "Flameslinger",
    "DinoRang", "LightningRod", "Zap", "WhamShell", "SlamBam", "Countdown",
    "PopFizz", "JetVac", "FrightRider", "HotDog", "EyeBrawl", "Thumpback",
    "Ninjini", "Shroomboom", "Chill", "Flashwing", "Swarm", "Crusher",
]


def load_index(assets):
    art = json.load(open(os.path.join(assets, "art.json")))
    out = {}
    for key, info in art.items():
        rel = info.get("portrait")
        if not rel or not rel.endswith("_Large.png"):
            continue
        if os.path.exists(os.path.join(assets, rel)):
            out[key] = os.path.join(assets, rel)
    return out


def resolve(index, name):
    """The art entry for one figure: its plain portrait if it has one.

    The catalogue is keyed by variant (`Spyro_S1_Large`, `Bash_LG_Large`, ...),
    so a bare figure name has to be looked up by prefix, preferring the version
    without a variant suffix.
    """
    if name in index:
        return name
    for suffix in ("_Large", "_Driver_Large", "_S1_Large", "_Alt_Large",
                   "_LG_Large", "_EE_Large"):
        if name + suffix in index:
            return name + suffix
    cands = [k for k in index if k.startswith(name + "_")]
    return sorted(cands, key=len)[0] if cands else None


def pick(index, count):
    """Preferred figures that exist, then an even spread over the rest."""
    chosen = []
    for name in PREFERRED:
        key = resolve(index, name)
        if key and key not in chosen:
            chosen.append(key)
    if len(chosen) > count:
        chosen = chosen[:count]
    rest = [k for k in sorted(index) if k not in chosen]
    need = count - len(chosen)
    if need > 0 and rest:
        step = max(1, len(rest) // need)
        chosen += rest[::step][:need]
    return chosen


def rounded(im, size, radius=14):
    im = im.convert("RGBA").resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1],
                                           radius=radius, fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(im, (0, 0), mask)
    return out


def cover(im, size):
    """Scale and centre-crop to fill `size` (background use)."""
    want_w, want_h = size
    scale = max(want_w / im.width, want_h / im.height)
    im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))),
                   Image.LANCZOS)
    left = (im.width - want_w) // 2
    top = (im.height - want_h) // 2
    return im.crop((left, top, left + want_w, top + want_h))


def banner(assets, index, out):
    width, height = 1280, 420
    backdrop = Image.open(os.path.join(assets, "bg",
                                       "FrontscreenBackground_D[Mid].png"))
    bg = cover(backdrop.convert("RGB"), (width, height))
    bg = bg.filter(ImageFilter.GaussianBlur(2.5))
    bg = ImageEnhance.Brightness(bg).enhance(0.22)
    bg = ImageEnhance.Color(bg).enhance(0.6)
    canvas = Image.new("RGBA", (width, height), BG_COLOUR)
    canvas.paste(bg.convert("RGBA"), (0, 0))

    logo_path = os.path.join(assets, "bg", "ICON_GameTitle_DA.png")
    logo = Image.open(logo_path).convert("RGBA")
    logo = logo.resize((470, int(logo.height * 470 / logo.width)), Image.LANCZOS)
    canvas.alpha_composite(logo, (56, 26))

    figures = pick(index, 6)
    x, y, size = 56, 268, 112
    for key in figures:
        art = rounded(Image.open(index[key]), size + 8, radius=16)
        frame = Image.new("RGBA", (size + 8, size + 8), (0, 0, 0, 0))
        ImageDraw.Draw(frame).rounded_rectangle([0, 0, size + 7, size + 7],
                                                radius=16, outline=LINE, width=2)
        frame.alpha_composite(art, (0, 0))
        canvas.alpha_composite(frame, (x, y))
        x += size + 26

    ImageDraw.Draw(canvas).line([(0, height - 1), (width, height - 1)],
                                fill=LINE, width=1)
    canvas.convert("RGB").save(out, optimize=True)
    return figures


def roster(assets, index, out, cols=10, rows=5, cell=96, gap=8):
    figures = pick(index, cols * rows)
    width = cols * cell + (cols + 1) * gap
    height = rows * cell + (rows + 1) * gap
    canvas = Image.new("RGB", (width, height), BG_COLOUR[:3])
    for i, key in enumerate(figures):
        row, col = divmod(i, cols)
        art = rounded(Image.open(index[key]), cell, radius=12)
        canvas.paste(art, (gap + col * (cell + gap), gap + row * (cell + gap)), art)
    canvas.save(out, optimize=True)
    return figures


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--assets", default=os.path.join(ROOT, "launcher", "assets"))
    ap.add_argument("--out", default=os.path.join(ROOT, "docs"))
    args = ap.parse_args()

    index = load_index(args.assets)
    if not index:
        print("no art in %s - run tools/extract_art.py first" % args.assets)
        return 1
    os.makedirs(args.out, exist_ok=True)

    base = banner(args.assets, index, os.path.join(args.out, "banner.png"))
    grid = roster(args.assets, index, os.path.join(args.out, "roster.png"))
    clean = lambda keys: ", ".join(k.replace("_Large", "") for k in keys)
    print("banner.png  %d figures: %s" % (len(base), clean(base)))
    print("roster.png  %d figures from %s" % (len(grid), os.path.basename(args.assets)))
    for name in ("banner.png", "roster.png"):
        path = os.path.join(args.out, name)
        print("  %-10s %5d KB  %s" % (name, os.path.getsize(path) // 1024, path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
