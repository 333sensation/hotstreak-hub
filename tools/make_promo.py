#!/usr/bin/env python3
"""Render the promo clip for this mod: game art, game audio, one MP4.

Everything on screen is the disc's own artwork (the title logo, the front-screen
background, the `_Large` character portraits). The soundtrack is streamed audio
pulled out of `Streams2.dat` with SSCR-Audio-Tool; `--audio` takes that WAV.

    python3 tools/make_promo.py --audio /path/to/music.wav
    python3 tools/make_promo.py --audio music.wav --gif docs/promo.gif
    python3 tools/make_promo.py --audio music.wav --stills   # a few PNG frames

Frames are rendered with Pillow and piped straight into ffmpeg (no PNG dumps),
so a 32 s, 720p clip takes about a minute.
"""
import argparse
import json
import math
import os
import random
import subprocess
import sys

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

BG = (8, 11, 18)
BG_SOFT = (13, 19, 30)
CARD = (19, 27, 42)
LINE = (32, 44, 68)
INK = (232, 238, 252)
DIM = (127, 140, 168)
ACCENT = (255, 180, 0)
ACCENT_2 = (86, 200, 255)

W, H = 1280, 720
FPS = 30
DURATION = 32.0

SCENES = (("logo", 5.0), ("slots", 6.0), ("features", 6.0), ("roll", 8.0),
          ("outro", 7.0))
DIP = 0.30          # seconds of fade to black on each side of a cut


# --------------------------------------------------------------------- helpers
def clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else hi if v > hi else v


def ease_out(t):
    t = clamp(t)
    return 1 - (1 - t) ** 3


def ease_in_out(t):
    t = clamp(t)
    return 0.5 - 0.5 * math.cos(math.pi * t)


def font(size, heavy=False, mono=False):
    if mono:
        cands = ["/System/Library/Fonts/Menlo.ttc",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
                 "C:/Windows/Fonts/consola.ttf"]
    elif heavy:
        cands = ["/System/Library/Fonts/Supplemental/Arial Black.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "C:/Windows/Fonts/ariblk.ttf",
                 "/System/Library/Fonts/Supplemental/Arial Bold.ttf"]
    else:
        cands = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "C:/Windows/Fonts/arialbd.ttf"]
    for path in cands:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size)
    except TypeError:                       # Pillow < 10
        return ImageFont.load_default()


def rounded(im, size, radius=14):
    im = im.convert("RGBA").resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1],
                                           radius=radius, fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(im, (0, 0), mask)
    return out


def cover(im, size):
    want_w, want_h = size
    scale = max(want_w / im.width, want_h / im.height)
    im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))),
                   Image.LANCZOS)
    left = (im.width - want_w) // 2
    top = (im.height - want_h) // 2
    return im.crop((left, top, left + want_w, top + want_h))


def tracked(draw, xy, text, fnt, fill, spacing=2, alpha=255, anchor_left=True):
    """Letter-spaced text (Pillow has no tracking)."""
    x, y = xy
    total = sum(draw.textlength(ch, font=fnt) + spacing for ch in text) - spacing
    if not anchor_left:
        x -= total / 2
    for ch in text:
        draw.text((x, y), ch, font=fnt, fill=fill + (alpha,))
        x += draw.textlength(ch, font=fnt) + spacing
    return total


def glow_text(base, xy, text, fnt, fill, alpha=255, glow=ACCENT, radius=18):
    """Text with a soft coloured halo behind it."""
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.text(xy, text, font=fnt, fill=glow + (alpha,))
    layer = layer.filter(ImageFilter.GaussianBlur(radius))
    base.alpha_composite(layer)
    ImageDraw.Draw(base).text(xy, text, font=fnt, fill=fill + (alpha,))


# ---------------------------------------------------------------------- assets
class Art:
    def __init__(self, assets, seed=7):
        self.dir = assets
        art = json.load(open(os.path.join(assets, "art.json")))
        self.art = art
        keys = []
        for key, info in art.items():
            rel = info.get("portrait") or ""
            if rel.endswith("_Large.png") and os.path.exists(os.path.join(assets, rel)):
                keys.append(key)
        self.keys = sorted(keys)
        self._cache = {}
        rng = random.Random(seed)
        self.cast = rng.sample(self.keys, min(len(self.keys), 90))

        logo = Image.open(os.path.join(assets, "bg", "ICON_GameTitle_DA.png"))
        self.logo = logo.convert("RGBA")
        back = Image.open(os.path.join(assets, "bg",
                                       "FrontscreenBackground_D[Mid].png"))
        back = cover(back.convert("RGB"), (1920, 1080))
        # the front screen has the game's own logo baked into its top half; crop
        # below it so the promo's logo is the only logo on screen
        back = back.crop((0, 330, 1920, 1080)).resize((1920, 1080), Image.LANCZOS)
        self.backdrop = ImageEnhance.Brightness(
            back.filter(ImageFilter.GaussianBlur(9))
        ).enhance(0.30).convert("RGBA")

    def portrait(self, key, size):
        got = self._cache.get((key, size))
        if got is None:
            path = os.path.join(self.dir, self.art[key]["portrait"])
            got = rounded(Image.open(path), size)
            self._cache[(key, size)] = got
        return got

    def scaled_logo(self, width):
        key = ("logo", width)
        got = self._cache.get(key)
        if got is None:
            got = self.logo.resize((width, int(self.logo.height * width / self.logo.width)),
                                   Image.LANCZOS)
            self._cache[key] = got
        return got

    def canvas(self, zoom, y_offset=0):
        """The moving backdrop: a slow zoom on the blurred front screen."""
        z = 1.06 + 0.10 * zoom
        w, h = int(1920 / z), int(1080 / z)
        left = (1920 - w) // 2
        top = (1080 - h) // 2 + int(y_offset)
        crop = self.backdrop.crop((left, top, left + w, top + h))
        frame = Image.new("RGBA", (W, H), BG + (255,))
        frame.paste(crop.resize((W, H), Image.BILINEAR), (0, 0))
        shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(shade)
        d.rectangle([0, 0, W, H], fill=(4, 6, 11, 120))
        frame.alpha_composite(shade)
        return frame


# ---------------------------------------------------------------------- scenes
def scene_logo(art, t, span):
    frame = art.canvas(t / span, y_offset=-10 * t / span)
    d = ImageDraw.Draw(frame)
    a = int(255 * ease_out(t / 1.2))
    logo = art.scaled_logo(600)
    frame.alpha_composite(logo, ((W - logo.width) // 2, 150 - int(12 * (1 - ease_out(t / 1.4)))))

    sub = font(30, heavy=True)
    d2 = ImageDraw.Draw(frame)
    tracked(d2, (W // 2, 470), "ROSTER MOD", sub, ACCENT,
            spacing=9, alpha=a, anchor_left=False)
    small = font(21)
    tracked(d2, (W // 2, 520), "SKYLANDERS: SUPERCHARGERS RACING  \u00b7  WII",
            small, DIM, spacing=3, alpha=int(255 * ease_out((t - 0.6) / 1.2)),
            anchor_left=False)
    return frame


def scene_slots(art, t, span):
    frame = art.canvas(0.15 + t / span * 0.1)
    d = ImageDraw.Draw(frame)
    head = font(76, heavy=True)
    a = int(255 * ease_out((t - 0.1) / 0.6))
    glow_text(frame, (72, 96), "71 RACER SLOTS", head, INK, alpha=a, glow=ACCENT)
    d = ImageDraw.Draw(frame)
    line = font(26)
    d.text((78, 196), "56 drivers + 12 villains + 3 test dummies, every terrain",
           font=line, fill=DIM + (a,))
    d.text((78, 234), "one figure per character, no repeats in a grid",
           font=line, fill=DIM + (a,))

    size = 126
    strip = art.cast[:max(1, min(9, (W - 156 + 14) // (size + 14)))]
    for i, key in enumerate(strip):
        local = (t - 0.5 - i * 0.09) / 0.55
        if local <= 0:
            continue
        p = ease_out(local)
        card = art.portrait(key, size)
        x = 78 + i * (size + 14)
        y = 340 + int(70 * (1 - p))
        frame.alpha_composite(_with_frame(card, size), (x, y))
        d.rectangle([x, y + size + 8, x + int(size * p), y + size + 12],
                    fill=ACCENT + (140,))

    d.text((78, 560), "rolled from the disc's own catalogue", font=font(30),
           fill=INK + (int(255 * ease_out((t - 1.6) / 0.8)),))
    d.text((78, 604), "224 figures", font=font(54, heavy=True),
           fill=ACCENT + (int(255 * ease_out((t - 1.9) / 0.8)),))
    return frame


def _with_frame(card, size):
    frame = Image.new("RGBA", (size + 8, size + 8), (0, 0, 0, 0))
    ImageDraw.Draw(frame).rounded_rectangle([0, 0, size + 7, size + 7],
                                            radius=18, outline=LINE, width=2)
    frame.alpha_composite(card, (4, 4))
    return frame


FEATURES = (
    ("RANDOM CAST", "a new field of opponents every boot, ~10 s to rebuild"),
    ("BALANCED STATS", "194 records rewritten to five even profiles"),
    ("RANDOM CUPS", "the five circuits of each cup, reshuffled"),
    ("YOUR SKYLANDER", "the figure you race as, on the emulated portal"),
)


def scene_features(art, t, span):
    frame = art.canvas(0.25 + t / span * 0.08)
    d = ImageDraw.Draw(frame)
    head = font(34, heavy=True)
    tracked(d, (78, 92), "WHAT THE MOD DOES", head, ACCENT, spacing=7,
            alpha=int(255 * ease_out(t / 0.4)))
    title = font(58, heavy=True)
    d.text((74, 146), "Four edits, all same-size,", font=title, fill=INK + (255,))
    d.text((74, 212), "so the disc keeps loading.", font=title, fill=(176, 188, 212, 235))

    for i, (name, detail) in enumerate(FEATURES):
        local = (t - 0.6 - i * 0.55) / 0.5
        if local <= 0:
            continue
        p = ease_out(local)
        y = 318 + i * 92
        x = 78 - int(60 * (1 - p))
        alpha = int(255 * p)
        d.rounded_rectangle([x, y, x + W - 156, y + 76], radius=14,
                            fill=CARD + (int(210 * p),), outline=LINE + (alpha,), width=1)
        d.rounded_rectangle([x, y, x + 6, y + 76], radius=3, fill=ACCENT + (alpha,))
        d.text((x + 28, y + 10), name, font=font(30, heavy=True), fill=INK + (alpha,))
        d.text((x + 28, y + 46), detail, font=font(20), fill=DIM + (alpha,))
    return frame


def scene_roll(art, t, span):
    frame = art.canvas(0.35 + t / span * 0.1)
    d = ImageDraw.Draw(frame)
    head = font(40, heavy=True)
    tracked(d, (W // 2, 70), "THE FIELD, ROLLED", head, ACCENT, spacing=8,
            alpha=255, anchor_left=False)
    d.text((W // 2, 126), "the cast a race fields changes with every launch",
           font=font(24), fill=DIM + (255,), anchor="mm")

    cols, rows, size, gap = 6, 2, 132, 16
    total_w = cols * size + (cols - 1) * gap
    x0 = (W - total_w) // 2
    y0 = 196
    rng = random.Random(11)
    for i in range(cols * rows):
        c, r = i % cols, i // cols
        x = x0 + c * (size + gap)
        y = y0 + r * (size + gap)
        stop = 0.8 + (i / (cols * rows)) * 2.6          # when this card locks
        if t < stop:
            speed = 26 if t < stop - 0.6 else 9
            key = art.cast[int((t * speed + i * 7) * 13) % len(art.cast)]
            blur = 1 - clamp((stop - t) / 0.6) if t > stop - 0.6 else 0
        else:
            key = art.cast[(i * 5 + 3) % len(art.cast)]
            blur = 0
        card = art.portrait(key, size)
        if blur:
            card = card.filter(ImageFilter.GaussianBlur(1.5 * (1 - blur) + 0.3))
        frame.alpha_composite(_with_frame(card, size), (x, y))

    p = ease_out((t - 3.6) / 0.6)
    if p > 0:
        d.text((W // 2, 560), "71 slots  \u00b7  one figure per character",
               font=font(34, heavy=True), fill=INK + (int(255 * p),), anchor="mm")
        d.text((W // 2, 606), "pin your favourites, or let it roll",
               font=font(22), fill=DIM + (int(255 * p),), anchor="mm")
    return frame


def scene_outro(art, t, span):
    frame = art.canvas(0.45 + t / span * 0.05)
    logo = art.scaled_logo(360)
    frame.alpha_composite(logo, ((W - logo.width) // 2 - 200, 96))

    d = ImageDraw.Draw(frame)
    p = ease_out((t - 0.2) / 0.7)
    d.text((W - 300, 150), "github.com/", font=font(40, heavy=True),
           fill=INK + (int(255 * p),), anchor="ra")
    d.text((W - 300, 200), "333sensation/", font=font(40, heavy=True),
           fill=ACCENT + (int(255 * p),), anchor="ra")
    d.text((W - 300, 250), "skylanders-scr-mod", font=font(40, heavy=True),
           fill=ACCENT + (int(255 * p),), anchor="ra")

    q = ease_out((t - 0.9) / 0.7)
    d.text((72, 470), "one command, your own disc", font=font(30),
           fill=DIM + (int(255 * q),))
    d.rounded_rectangle([72, 516, 72 + 620, 516 + 62], radius=12,
                        fill=CARD + (235,), outline=LINE + (255,), width=1)
    d.text((94, 528), "python3 setup.py", font=font(26, mono=True),
           fill=ACCENT + (int(255 * q),))
    d.text((94 + 300, 528), "your-disc.iso", font=font(26, mono=True),
           fill=DIM + (int(255 * q),))

    if t > 1.4:
        g = ease_out((t - 1.4) / 0.9)
        strip = art.cast[9:19]
        size = 96
        x = 72
        for key in strip:
            frame.alpha_composite(_with_frame(art.portrait(key, size), size).resize(
                (int((size + 8) * 0.9), int((size + 8) * 0.9)), Image.LANCZOS),
                (x, 600))
            x += int((size + 8) * 0.9) + 8

    fade = clamp((t - (span - 0.9)) / 0.9)
    if fade > 0:
        frame.alpha_composite(Image.new("RGBA", (W, H), (0, 0, 0, int(255 * fade))))
    return frame


RENDERERS = {
    "logo": scene_logo,
    "slots": scene_slots,
    "features": scene_features,
    "roll": scene_roll,
    "outro": scene_outro,
}


# ------------------------------------------------------------------------ main
def render(art, seconds, fps):
    timeline = []
    at = 0.0
    for name, span in SCENES:
        timeline.append((at, at + span, name))
        at += span
    total = at
    scale = seconds / total if seconds else 1.0
    timeline = [(s * scale, e * scale, n) for s, e, n in timeline]

    black = Image.new("RGB", (W, H), BG)
    frames = int(round(seconds * fps))
    for f in range(frames):
        t = f / fps
        for start, end, name in timeline:
            if start <= t < end or (name == timeline[-1][2] and t >= start):
                local = t - start
                img = RENDERERS[name](art, local, end - start).convert("RGB")
                # cut through black: two text-heavy layouts never overlap
                k = min(ease_in_out(local / DIP), ease_in_out((end - t) / DIP))
                yield Image.blend(black, img, clamp(k))
                break


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--assets", default=os.path.join(ROOT, "launcher", "assets"))
    ap.add_argument("--audio", help="music bed (WAV) - e.g. a stream from Streams2.dat")
    ap.add_argument("--out", default=os.path.join(ROOT, "promo", "promo.mp4"))
    ap.add_argument("--gif", help="also write a silent GIF preview here")
    ap.add_argument("--seconds", type=float, default=DURATION)
    ap.add_argument("--fps", type=int, default=FPS)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--stills", metavar="DIR",
                    help="write a handful of PNG stills instead of a video")
    args = ap.parse_args()

    art = Art(args.assets, seed=args.seed)

    if args.stills:
        os.makedirs(args.stills, exist_ok=True)
        at = 0.0
        for name, span in SCENES:
            local = span * 0.72
            img = RENDERERS[name](art, local, span)
            path = os.path.join(args.stills, "%s.png" % name)
            img.convert("RGB").save(path, optimize=True)
            print(path)
            at += span
        return 0

    if not args.audio:
        print("need --audio: a music bed WAV (see tools/README or promo/README.md)")
        return 1
    if not os.path.exists(args.audio):
        print("no such audio file: %s" % args.audio)
        return 1

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (W, H),
           "-r", str(args.fps), "-i", "-",
           "-i", args.audio,
           "-af", "afade=in:st=0:d=0.6,afade=out:st=%.2f:d=1.2" % (args.seconds - 1.2),
           "-c:v", "libx264", "-preset", "slow", "-crf", "20",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart",
           "-c:a", "aac", "-b:a", "192k", "-shortest", args.out]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for img in render(art, args.seconds, args.fps):
            proc.stdin.write(img.tobytes())
    except BrokenPipeError:
        pass
    finally:
        if proc.stdin:
            proc.stdin.close()
    code = proc.wait()
    if code != 0:
        print("ffmpeg failed (%d)" % code)
        return 1
    print("wrote %s (%.1f MB)" % (args.out, os.path.getsize(args.out) / 1e6))

    if args.gif:
        gif = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", args.out, "-t", "9.5",
             "-vf", "fps=13,scale=640:-1:flags=lanczos,split[a][b];"
                    "[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer",
             args.gif])
        if gif.returncode == 0:
            print("wrote %s (%.1f MB)" % (args.gif, os.path.getsize(args.gif) / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
