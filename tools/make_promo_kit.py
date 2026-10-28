#!/usr/bin/env python3
"""Render the social set for this mod: Instagram posts, a story, a reel, a flyer.

Same rules as `tools/make_promo.py`: every pixel is the disc's own artwork (title
logo, front-screen background, `_Large` portraits), the numbers on the cards are
read out of the patched `BaseGameplay.pkz` / `BaseSkylander.pkz` / `Common.pkz`
rather than typed in, and Pillow frames are piped straight into ffmpeg.

    python3 tools/make_promo_kit.py                # everything
    python3 tools/make_promo_kit.py --posts        # the five 1080x1080 cards
    python3 tools/make_promo_kit.py --story --flyer
    python3 tools/make_promo_kit.py --reel         # 1080x1920, reuses promo.mp4's audio

Output lands in `promo/instagram/` (posts + story), `promo/flyer.png` /
`promo/flyer.pdf` (A4, 300 dpi) and `promo/reel.mp4`.
"""
import argparse
import json
import math
import os
import random
import struct
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import make_promo as MP                    # noqa: E402  (colours, fonts, art)
import pkz_cup_random as CUPS              # noqa: E402
import pkz_ai_speed as SPEED               # noqa: E402
import pkz_pool_swap as pw                 # noqa: E402

BG, CARD, LINE = MP.BG, MP.CARD, MP.LINE
INK, DIM, ACCENT, ACCENT_2 = MP.INK, MP.DIM, MP.ACCENT, MP.ACCENT_2
DATA = os.path.join(ROOT, "disc", "files", "Data")
OUT = os.path.join(ROOT, "promo")
IG = os.path.join(OUT, "instagram")
BRAND = "HOTSTREAK HUB"
REPO = "github.com/333sensation/hotstreak-hub"

STATS_TYPE = 0x4BBD2CFD
STAT_NAMES = ("TOP SPEED", "ACCEL", "ARMOR", "HANDLING", "FIREPOWER")


# --------------------------------------------------------------------- data bits
def stat_spreads(want=6):
    """[(figure, [5 floats])] straight out of the patched BaseSkylander.pkz."""
    d = open(os.path.join(DATA, "BaseSkylander.pkz"), "rb").read()
    out = []
    for w in pw.wrappers(d):
        key, name, roff, rlen, doff, dlen = pw.read_wrapper(d, w)
        if not name or doff is None or not name.endswith("Stats"):
            continue
        ps, ln, own, typ, keys = pw.body_fields(d, doff)
        if typ != STATS_TYPE or ln < 0x24:
            continue
        # five big-endian floats: TopSpeed, Accel, Armor, Handling, FirePower
        vals = struct.unpack_from(">5f", d, ps + 0x10)
        short = name.replace("Stats", "").split("_")[-1].strip()
        if sum(vals) < 1.0 or not short:
            continue
        out.append((short, [max(0.0, v) for v in vals]))
    seen, uniq = set(), []
    for name, vals in sorted(out):
        if name in seen:
            continue
        seen.add(name)
        uniq.append((name, vals))
    step = max(1, len(uniq) // want)
    return uniq[::step][:want]


def bot_speeds():
    """The three uniform bot speeds actually written into BaseGameplay.pkz."""
    d = open(os.path.join(DATA, "BaseGameplay.pkz"), "rb").read()
    vals = sorted({round(SPEED.speed_of(d, ps), 2) for _k, _n, ps in SPEED.personalities(d)})
    return vals or [1.18, 1.20, 1.22]


def cup_line_up():
    """The land cup's current five tracks, read from Common.pkz."""
    d = open(os.path.join(DATA, "Common.pkz"), "rb").read()
    objs = CUPS.objects(d)
    names = {r["key"]: n for n, r in objs.items()}
    rec = objs.get("LandCupPlaylist")
    ids, _off = CUPS.read_list(d, rec)
    pretty = []
    for i in ids:
        n = names.get(i, "?")
        n = n.split("_", 1)[1] if "_" in n else n
        n = n.replace("_Race_Desc", "").replace("_Race", "")
        pretty.append("".join(ch for ch in n if not ch.isdigit()))
    return pretty


# ------------------------------------------------------------------ frame helpers
def canvas(w, h, zoom=0.0, y_shift=0):
    """A dim, blurred, slowly zoomed front-screen still at any size."""
    z = 1.06 + 0.10 * zoom
    bw, bh = int(1920 / z), int(1080 / z)
    left, top = (1920 - bw) // 2, (1080 - bh) // 2 + int(y_shift)
    crop = ART.backdrop.crop((left, top, left + bw, top + bh))
    frame = Image.new("RGBA", (w, h), BG + (255,))
    frame.paste(crop.resize((w, h), Image.BILINEAR), (0, 0))
    frame.alpha_composite(Image.new("RGBA", (w, h), (4, 6, 11, 130)))
    # vignette so the type reads at thumbnail size
    vig = Image.new("L", (w, h), 0)
    vd = ImageDraw.Draw(vig)
    vd.ellipse([-w * 0.35, -h * 0.30, w * 1.35, h * 1.30], fill=120)
    vig = vig.filter(ImageFilter.GaussianBlur(min(w, h) // 12))
    frame.paste(Image.new("RGBA", (w, h), (3, 5, 9, 255)), (0, 0),
                Image.eval(vig, lambda v: 255 - v))
    return frame


def head(d, xy, text, size, fill=INK, spacing=3, alpha=255, center=None):
    """Heavy letter-spaced headline (Pillow has no tracking)."""
    f = MP.font(size, heavy=True)
    return MP.tracked(d, xy if center is None else center, text, f, fill,
                      spacing=spacing, alpha=alpha, anchor_left=center is None)


def pill(d, xy, text, size, fg=ACCENT, bg=CARD, pad=22):
    f = MP.font(size, heavy=True)
    tw = d.textlength(text, font=f)
    x, y = xy
    d.rounded_rectangle([x, y, x + tw + pad * 2, y + size + pad * 1.1],
                        radius=(size + pad) // 2, fill=bg + (235,), outline=LINE + (255,), width=2)
    d.text((x + pad, y + pad * 0.5), text, font=f, fill=fg + (255,))
    return tw + pad * 2


def brandmark(frame, alpha=210):
    """Small wordmark every card carries, bottom right."""
    d = ImageDraw.Draw(frame)
    d.text((frame.width - 56, frame.height - 52), BRAND, font=MP.font(24, heavy=True),
           fill=ACCENT + (alpha,), anchor="rs")
    return frame


def portrait_row(frame, keys, y, size, gap=14, x0=0, center_w=None, frame_them=True):
    total = len(keys) * size + (len(keys) - 1) * gap
    x = x0 if center_w is None else (center_w - total) // 2
    for k in keys:
        card = ART.portrait(k, size)
        frame.alpha_composite(MP._with_frame(card, size) if frame_them else card, (x, y))
        x += size + gap


# ------------------------------------------------------------------------ posts
def post_cast(w=1080, h=1080):
    frame = canvas(w, h, 0.05)
    d = ImageDraw.Draw(frame)
    head(d, (72, 80), "RANDOM CAST", 44, ACCENT, spacing=8)
    d.text((72, 148), "a new field every boot", font=MP.font(74, heavy=True), fill=INK + (255,))
    d.text((72, 240), "224 figures, one per character", font=MP.font(34), fill=DIM + (255,))

    keys = ART.cast[:8]
    size, gap = 220, 18
    for i, k in enumerate(keys):
        cx = 72 + (i % 4) * (size + gap)
        cy = 320 + (i // 4) * (size + gap)
        frame.alpha_composite(MP._with_frame(ART.portrait(k, size), size), (cx, cy))

    d.text((72, h - 176), "no figure repeats in a grid", font=MP.font(30), fill=INK + (255,))
    d.text((72, h - 132), "pin your favourites, or let it roll", font=MP.font(30), fill=DIM + (255,))
    return frame


def post_stats(w=1080, h=1080):
    frame = canvas(w, h, 0.2)
    d = ImageDraw.Draw(frame)
    head(d, (72, 80), "NEW STATS", 44, ACCENT_2, spacing=8)
    d.text((72, 148), "no two figures drive", font=MP.font(70, heavy=True), fill=INK + (255,))
    d.text((72, 224), "the same way", font=MP.font(70, heavy=True), fill=INK + (255,))

    # one legend, then one bar block per figure - the spreads are read out of
    # the patched BaseSkylander.pkz, so these are the numbers the game uses
    legend_x = 300
    for j, label in enumerate(("SPD", "ACC", "ARM", "HND", "FIRE")):
        d.text((legend_x, 340), label, font=MP.font(20, heavy=True),
               fill=(ACCENT if j == 0 else ACCENT_2) + (220,))
        legend_x += 152

    top, rowh = 384, 106
    for i, (name, vals) in enumerate(STAT_SPREADS):
        y = top + i * rowh
        d.text((72, y + 4), name.upper()[:13], font=MP.font(30, heavy=True), fill=INK + (255,))
        for j, v in enumerate(vals):
            col = ACCENT if j == 0 else ACCENT_2
            x = 300 + j * 152
            d.rounded_rectangle([x, y, x + 132, y + 30], radius=15, fill=(28, 36, 54, 230))
            d.rounded_rectangle([x, y, x + max(10, int(132 * min(1.0, v))), y + 30],
                                radius=15, fill=col + (240,))
    d.text((72, h - 96), "203 character records rewritten, same 3.0 budget",
           font=MP.font(26), fill=DIM + (255,))
    return frame


def post_speed(w=1080, h=1080):
    frame = canvas(w, h, 0.32)
    d = ImageDraw.Draw(frame)
    head(d, (72, 80), "BOT SPEED", 44, ACCENT, spacing=8)
    d.text((72, 148), "same speed for", font=MP.font(72, heavy=True), fill=INK + (255,))
    d.text((72, 226), "every bot", font=MP.font(72, heavy=True), fill=ACCENT + (255,))
    d.text((72, 320), "one number per difficulty", font=MP.font(30), fill=DIM + (255,))

    track_x0, track_x1 = 300, w - 200

    def bar(y, a, b, label, col, lo, hi, value=None):
        x0 = track_x0 + int((a - lo) / (hi - lo) * (track_x1 - track_x0))
        x1 = track_x0 + int((b - lo) / (hi - lo) * (track_x1 - track_x0))
        d.text((72, y - 6), label, font=MP.font(26, heavy=True), fill=INK + (255,))
        d.rounded_rectangle([track_x0, y, track_x1, y + 26], radius=13, fill=(28, 36, 54, 220))
        d.rounded_rectangle([min(x0, x1), y, max(x1, x0 + 8), y + 26], radius=13, fill=col + (240,))
        if value is not None:
            d.text((track_x1 + 24, y - 8), "%.2f" % value, font=MP.font(26, heavy=True),
                   fill=col + (255,))

    # the shipped spread, then the three uniform bands on their own, tighter scale
    bar(430, 0.80, 1.20, "BEFORE", ACCENT_2, 0.70, 1.30)
    for i, v in enumerate(BOT_SPEEDS):
        bar(520 + i * 88, 1.14, v, ["EASY", "MEDIUM", "HARD"][i % 3], ACCENT,
            1.14, 1.24, v)
    d.text((72, 800), "1.18 / 1.20 / 1.22".replace("/", "\u00b7"),
           font=MP.font(46, heavy=True), fill=INK + (255,))
    d.text((72, 862), "up to +47% over the shipped field,", font=MP.font(28), fill=DIM + (255,))
    d.text((72, 900), "still inside the game's own fastest AI", font=MP.font(28), fill=DIM + (255,))
    return frame


def post_cups(w=1080, h=1080):
    frame = canvas(w, h, 0.45)
    d = ImageDraw.Draw(frame)
    head(d, (72, 80), "RANDOM CUPS", 44, ACCENT_2, spacing=8)
    d.text((72, 148), "the same circuits,", font=MP.font(66, heavy=True), fill=INK + (255,))
    d.text((72, 222), "never the same order", font=MP.font(66, heavy=True), fill=INK + (255,))

    size, gap = 150, 18
    for i, name in enumerate(CUPS_LINE[:5]):
        x, y = 72, 330 + i * (size // 2 + 14)
        d.rounded_rectangle([x, y, w - 72, y + 76], radius=14, fill=CARD + (225,),
                            outline=LINE + (255,), width=2)
        d.text((x + 26, y + 14), "%02d" % (i + 1), font=MP.font(30, heavy=True), fill=ACCENT + (255,))
        d.text((x + 96, y + 16), name.replace("_", " "), font=MP.font(34), fill=INK + (255,))
    d.text((72, h - 118), "land \u00b7 sea \u00b7 sky cups roll on every build",
           font=MP.font(28), fill=DIM + (255,))
    d.text((72, h - 78), "mirror circuits optional", font=MP.font(28), fill=DIM + (255,))
    return frame


def post_netplay(w=1080, h=1080):
    frame = canvas(w, h, 0.55)
    d = ImageDraw.Draw(frame)
    head(d, (72, 80), "PLAY WITH A FRIEND", 40, ACCENT, spacing=6)
    d.text((72, 146), "two machines,", font=MP.font(72, heavy=True), fill=INK + (255,))
    d.text((72, 224), "one session code", font=MP.font(72, heavy=True), fill=ACCENT + (255,))
    d.text((72, 330), "the code makes both discs byte-identical, so", font=MP.font(26), fill=DIM + (255,))
    d.text((72, 364), "the netplay check passes and both see the same field", font=MP.font(26), fill=DIM + (255,))

    cols = "RACE24"
    box_w = (w - 144 - 5 * 12) // 6
    for i, ch in enumerate(cols):
        x = 72 + i * (box_w + 12)
        d.rounded_rectangle([x, 440, x + box_w, 440 + box_w], radius=16,
                            fill=CARD + (240,), outline=ACCENT + (200,), width=3)
        f = MP.font(int(box_w * 0.6), heavy=True)
        d.text((x + box_w // 2, 440 + box_w // 2), ch, font=f, fill=INK + (255,), anchor="mm")

    d.text((72, 640), "Dolphin \u2192 Tools \u2192 Start Netplay \u2192 port 2626",
           font=MP.font(30, heavy=True), fill=INK + (255,))
    portrait_row(frame, ART.cast[3:9], 720, 120, gap=14, x0=72)
    d.text((72, h - 96), "splitscreen 2P, over the internet", font=MP.font(28), fill=DIM + (255,))
    return frame


POSTS = (
    ("01-random-cast", post_cast),
    ("02-stats", post_stats),
    ("03-bot-speed", post_speed),
    ("04-cups", post_cups),
    ("05-netplay", post_netplay),
)


def story(w=1080, h=1920):
    frame = canvas(w, h, 0.1)
    d = ImageDraw.Draw(frame)
    logo = ART.scaled_logo(720)
    frame.alpha_composite(logo, ((w - logo.width) // 2, 150))
    head(d, None, BRAND, 46, ACCENT, spacing=12, center=(w // 2, 560))
    d.text((w // 2, 640), "224 figures. Random field every boot.", font=MP.font(36), fill=INK + (255,), anchor="mm")
    d.text((w // 2, 692), "Faster bots. New stats. Random cups.", font=MP.font(36), fill=INK + (255,), anchor="mm")

    keys = ART.cast[:6]
    size = (w - 144 - 2 * 16) // 3
    for i, k in enumerate(keys):
        x = 72 + (i % 3) * (size + 16)
        y = 790 + (i // 3) * (size + 16)
        frame.alpha_composite(MP._with_frame(ART.portrait(k, size), size), (x, y))

    d.rounded_rectangle([72, 1430, w - 72, 1560], radius=18, fill=CARD + (240,), outline=LINE + (255,), width=2)
    d.text((102, 1452), "python3 setup.py", font=MP.font(44, mono=True), fill=ACCENT + (255,))
    d.text((102, 1504), "your-disc.iso", font=MP.font(44, mono=True), fill=DIM + (255,))
    head(d, None, "SWIPE UP", 34, INK, spacing=10, center=(w // 2, 1610))
    d.text((w // 2, 1700), REPO, font=MP.font(28), fill=DIM + (255,), anchor="mm")
    return frame


# ------------------------------------------------------------------------ flyer
def flyer(w=2480, h=3508, s=2.30):
    """A4 at 300 dpi. `s` scales the 1080-wide layout up to print size."""
    frame = canvas(w, h, 0.15)
    d = ImageDraw.Draw(frame)
    M = 150

    logo = ART.scaled_logo(int(1150))
    frame.alpha_composite(logo, (M, 210))

    head(d, (M, 300 + logo.height), "H O T S T R E A K   H U B", 52, ACCENT, spacing=10)
    d.text((M, 380 + logo.height), "Skylanders: SuperChargers Racing  \u00b7  Wii (SKNE52)",
           font=MP.font(38), fill=DIM + (255,))

    feats = [
        ("RANDOM CAST", "224 catalogue figures rolled into the 56 driver slots, one figure per character, a new field on every boot."),
        ("STATS FOR EVERY FIGURE", "203 character records rewritten with a spiked spread each - the 148 empty stubs included."),
        ("UNIFORM, FASTER BOTS", "every bot on the same speed, one speed per difficulty: 1.18 / 1.20 / 1.22. No scrap vehicles."),
        ("RANDOM CUPS", "the land, sea and sky playlists re-ordered from the disc's own circuits."),
        ("PLAY WITH A FRIEND", "Dolphin netplay over the shipped split-screen; a session code keeps both discs identical."),
    ]
    y = 470 + logo.height
    for title, body in feats:
        d.rounded_rectangle([M, y, w - M, y + 200], radius=20, fill=CARD + (235,),
                            outline=LINE + (255,), width=3)
        d.rounded_rectangle([M, y, M + 10, y + 200], radius=5, fill=ACCENT + (255,))
        d.text((M + 44, y + 30), title, font=MP.font(44, heavy=True), fill=INK + (255,))
        # two-line wrap
        words, line, lines = body.split(), "", []
        for word in words:
            probe = (line + " " + word).strip()
            if d.textlength(probe, font=MP.font(32)) > w - 2 * M - 90:
                lines.append(line)
                line = word
            else:
                line = probe
        lines.append(line)
        for i, ln in enumerate(lines[:2]):
            d.text((M + 44, y + 100 + i * 44), ln, font=MP.font(32), fill=DIM + (255,))
        y += 224

    size = 300
    portrait_row(frame, ART.cast[:4], y + 30, size, gap=26, x0=M)
    portrait_row(frame, ART.cast[4:8], y + 30 + size + 26, size, gap=26, x0=M)

    box_y = y + 30 + 2 * size + 26 + 90
    d.rounded_rectangle([M, box_y, w - M, box_y + 150], radius=18, fill=(10, 14, 22, 240),
                        outline=ACCENT + (180,), width=3)
    d.text((M + 40, box_y + 28), "python3 setup.py", font=MP.font(48, mono=True), fill=ACCENT + (255,))
    d.text((M + 40 + d.textlength("python3 setup.py  ", font=MP.font(48, mono=True)), box_y + 28),
           "your-disc.iso", font=MP.font(48, mono=True), fill=DIM + (255,))
    d.text((M, box_y + 210), REPO, font=MP.font(40), fill=INK + (255,))
    d.text((M, box_y + 270), "MIT code \u00b7 bring your own disc \u00b7 windows / macOS / linux",
           font=MP.font(28), fill=DIM + (255,))
    d.text((w - M, h - 120), BRAND, font=MP.font(34, heavy=True), fill=ACCENT + (220,), anchor="rs")
    return frame


# ------------------------------------------------------------------------- reel
RW, RH, FPS = 1080, 1920, 30
REEL_SCENES = (("hook", 3.4), ("speed", 3.6), ("cast", 3.4), ("cta", 3.6))


def reel_hook(t, span):
    frame = canvas(RW, RH, 0.05 + 0.05 * t / span)
    d = ImageDraw.Draw(frame)
    logo = ART.scaled_logo(820)
    frame.alpha_composite(logo, ((RW - logo.width) // 2, 340))
    p = MP.ease_out(t / 0.6)
    head(d, None, "THE BOTS", 84, INK, spacing=6, center=(RW // 2, 900 + int(30 * (1 - p))))
    head(d, None, "GOT FASTER", 84, ACCENT, spacing=6, center=(RW // 2, 1010 + int(30 * (1 - p))))
    q = MP.ease_out((t - 0.8) / 0.8)
    d.text((RW // 2, 1150), "same speed for every bot", font=MP.font(40), fill=DIM + (int(255 * q),), anchor="mm")
    if q > 0:
        portrait_row(frame, ART.cast[12:16], 1270, 200, gap=18, center_w=RW)
    return frame


def reel_speed(t, span):
    frame = canvas(RW, RH, 0.25)
    d = ImageDraw.Draw(frame)
    head(d, None, "ONE SPEED", 66, INK, spacing=6, center=(RW // 2, 400))
    head(d, None, "PER DIFFICULTY", 66, ACCENT, spacing=6, center=(RW // 2, 500))
    labels = ("EASY", "MEDIUM", "HARD")
    for i, v in enumerate(BOT_SPEEDS):
        p = MP.ease_out((t - 0.3 - i * 0.35) / 0.5)
        if p <= 0:
            continue
        y = 700 + i * 250
        d.text((110, y), labels[i % 3], font=MP.font(42, heavy=True), fill=DIM + (int(255 * p),))
        full = RW - 360
        bar_w = int(full * (0.75 + 0.25 * p))
        d.rounded_rectangle([110, y + 70, 110 + full, y + 140], radius=35, fill=(26, 34, 52, 210))
        d.rounded_rectangle([110, y + 70, 110 + bar_w, y + 140], radius=35,
                            fill=(ACCENT if i == 2 else ACCENT_2) + (int(240 * p),))
        d.text((RW - 96, y + 74), "%.2f" % v, font=MP.font(56, heavy=True),
               fill=INK + (int(255 * p),), anchor="ra")
    q = MP.ease_out((t - 1.8) / 0.8)
    if q > 0:
        d.text((RW // 2, 1500), "no more 0.80 average", font=MP.font(38),
               fill=DIM + (int(255 * q),), anchor="mm")
        portrait_row(frame, ART.cast[20:25], 1600, 170, gap=16, center_w=RW)
    return frame


def reel_cast(t, span):
    frame = canvas(RW, RH, 0.4)
    d = ImageDraw.Draw(frame)
    head(d, None, "RANDOM CAST", 58, ACCENT, spacing=6, center=(RW // 2, 280))
    d.text((RW // 2, 372), "224 figures \u00b7 56 slots", font=MP.font(34), fill=DIM + (255,), anchor="mm")

    size, gap = 220, 20
    x0 = (RW - (2 * size + gap)) // 2
    for i in range(8):
        c, r = i % 2, i // 2
        stop = 0.3 + i * 0.28
        if t < stop:
            key = ART.cast[int((t * 60 + i * 13)) % len(ART.cast)]
            card = ART.portrait(key, size).filter(ImageFilter.GaussianBlur(1.2))
        else:
            key = ART.cast[(i * 7 + 5) % len(ART.cast)]
            card = ART.portrait(key, size)
        frame.alpha_composite(MP._with_frame(card, size),
                              (x0 + c * (size + gap), 450 + r * (size + gap)))
    d.text((RW // 2, 1420), "a new field every boot", font=MP.font(38), fill=INK + (255,), anchor="mm")
    d.text((RW // 2, 1480), "pin favourites, or let it roll", font=MP.font(30), fill=DIM + (255,), anchor="mm")
    return frame


def reel_cta(t, span):
    frame = canvas(RW, RH, 0.5)
    d = ImageDraw.Draw(frame)
    logo = ART.scaled_logo(600)
    frame.alpha_composite(logo, ((RW - logo.width) // 2, 320))
    p = MP.ease_out(t / 0.6)
    head(d, None, BRAND, 46, ACCENT, spacing=12, center=(RW // 2, 780))
    d.rounded_rectangle([100, 940, RW - 100, 1080], radius=20, fill=CARD + (240,), outline=LINE + (255,), width=3)
    d.text((130, 960), "python3 setup.py", font=MP.font(40, mono=True), fill=ACCENT + (int(255 * p),))
    d.text((130, 1016), "your-disc.iso", font=MP.font(40, mono=True), fill=DIM + (int(255 * p),))
    d.text((RW // 2, 1180), REPO, font=MP.font(30), fill=INK + (int(255 * p),), anchor="mm")
    portrait_row(frame, ART.cast[10:16], 1290, 170, gap=16, center_w=RW)
    d.text((RW // 2, 1540), "MIT code \u00b7 bring your own disc", font=MP.font(28),
           fill=DIM + (int(255 * p),), anchor="mm")
    return frame


REEL_RENDERERS = {"hook": reel_hook, "speed": reel_speed, "cast": reel_cast, "cta": reel_cta}


def render_reel(path, seconds=None, fps=FPS):
    total = sum(s for _n, s in REEL_SCENES)
    scale = (seconds / total) if seconds else 1.0
    timeline, at = [], 0.0
    for name, span in REEL_SCENES:
        timeline.append((at * scale, (at + span) * scale, name))
        at += span
    total *= scale
    frames = int(round(total * fps))

    audio = os.path.join(OUT, "promo.mp4")
    has_audio = os.path.exists(audio)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", "%dx%d" % (RW, RH), "-r", str(fps), "-i", "-"]
    if has_audio:
        cmd += ["-i", audio, "-map", "0:v", "-map", "1:a",
                "-af", "afade=t=in:st=0:d=0.4,afade=t=out:st=%.1f:d=1.0" % max(0.0, total - 1.2)]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    black = Image.new("RGB", (RW, RH), BG)
    try:
        for f in range(frames):
            t = f / fps
            for start, end, name in timeline:
                if start <= t < end or (name == timeline[-1][2] and t >= start):
                    local = t - start
                    img = REEL_RENDERERS[name](local, end - start).convert("RGB")
                    k = min(MP.ease_in_out(local / 0.24), MP.ease_in_out((end - t) / 0.24))
                    proc.stdin.write(Image.blend(black, img, MP.clamp(k)).tobytes())
                    break
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode:
        raise SystemExit("ffmpeg failed (%d)" % proc.returncode)
    return path


# -------------------------------------------------------------------------- main
ART = None
STAT_SPREADS = []
BOT_SPEEDS = []
CUPS_LINE = []


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--assets", default=os.path.join(ROOT, "launcher", "assets"))
    ap.add_argument("--posts", action="store_true", help="the five 1080x1080 cards")
    ap.add_argument("--story", action="store_true", help="the 1080x1920 story card")
    ap.add_argument("--flyer", action="store_true", help="A4 flyer, PNG + PDF")
    ap.add_argument("--reel", action="store_true", help="the 1080x1920 reel")
    ap.add_argument("--seconds", type=float, default=None, help="reel length override")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    global ART, STAT_SPREADS, BOT_SPEEDS, CUPS_LINE
    ART = MP.Art(args.assets)
    STAT_SPREADS = stat_spreads()
    BOT_SPEEDS = bot_speeds()
    CUPS_LINE = cup_line_up()
    print("data: %d stat spreads, bot speeds %s, cup %s"
          % (len(STAT_SPREADS), BOT_SPEEDS, ", ".join(CUPS_LINE)))

    do_all = args.all or not any((args.posts, args.story, args.flyer, args.reel))

    if do_all or args.posts:
        os.makedirs(IG, exist_ok=True)
        for name, fn in POSTS:
            path = os.path.join(IG, "%s.png" % name)
            brandmark(fn()).convert("RGB").save(path, optimize=True)
            print("  ", os.path.relpath(path, ROOT))
    if do_all or args.story:
        os.makedirs(IG, exist_ok=True)
        path = os.path.join(IG, "story.png")
        story().convert("RGB").save(path, optimize=True)
        print("  ", os.path.relpath(path, ROOT))
    if do_all or args.flyer:
        img = flyer().convert("RGB")
        png = os.path.join(OUT, "flyer.png")
        img.save(png, optimize=True)
        img.save(os.path.join(OUT, "flyer.pdf"), "PDF", resolution=300.0)
        print("  ", os.path.relpath(png, ROOT), "+ flyer.pdf")
    if do_all or args.reel:
        path = render_reel(os.path.join(OUT, "reel.mp4"), args.seconds)
        print("  ", os.path.relpath(path, ROOT))


if __name__ == "__main__":
    main()
