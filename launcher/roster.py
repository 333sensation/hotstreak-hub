#!/usr/bin/env python3
"""The roster: which figures the 71 racer slots point at, and how to write it.

Every racer opponent a race can field is a `RacerAIInfo` object inside
`BaseGameplay.pkz`: 56 `Driver<Figure>_<Terrain>_AIInfo` records (the ones that
carry the racer AI template) plus 15 villain records that the same pools
reference. Rewriting their `charId` in place is safe - the file stays the same
size, which is the only kind of edit this container tolerates (see FINDINGS.md).

So a "roster" here is a figure for each of those 71 slots. The engine picks
which of them it actually races against, so a new roster every boot means a new
field every boot.
"""
import os
import random
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(os.path.dirname(HERE), "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import pkz_pool_swap as pw  # noqa: E402

INFO_TYPE = 0x45BA524C
CATALOG_TYPE = 0x5DA30426
STATS_TYPE = 0x4BBD2CFD

VEHICLE_RE = re.compile(r"(Plane|Car|Boat)_Stats$|^RentAWreck_", re.I)
PART_RE = re.compile(r"_(Body|Legs|Arms|Head|Top|Bottom|Wheels?|Wings?|Turret|Weapon"
                     r"|Chassis|Hull|Frame|Bumper|Spoiler|Exhaust)$", re.I)
# Toy number ranges in the catalogue. Only these are figures a racer can be:
#   00xx Spyro's Adventure   01xx Giants      04xx Trap Team     05xx minis
#   30xx Trap Team           34xx SuperChargers
# Everything else in the catalogue is something else:
#   02xx magic items   03xx adventure packs   10xx/20xx SWAP Force halves
#   32xx vehicles + items (incl. 3222-3241 vehicles and 3500/3502 packs,
#   33xx level packs, 3503 the Kaos trophy)
FIGURE_NUMBERS = {"00", "01", "04", "05", "30", "34"}
NOT_A_FIGURE = re.compile(r"^\d{4}_Driver", re.I)
VARIANT = re.compile(r"_(S\d|Series\d|EE|EonsElite|LG|Dark|Lightcore|Legendary|Nitro|Volcanic"
                     r"|Polar|Royal|MegaRam|Springtime|Ninja|QuickDraw|Enchanted|Elite|AD|Christmas"
                     r"|Easter|Halloween|Jade|Molten|Scarlet|Golden|DARK|GOLD|SPECIAL)$", re.I)
DRIVER_RE = re.compile(r"^Driver(.+)_(Air|Land|Sea)_AIInfo$")
GREEBLE = (("air", "GreeblePlaneInfo"), ("land", "GreebleCarInfo"), ("sea", "GreebleBoatInfo"))
TERRAIN_POOLS = (
    ("EnemyAIList_Air_ActionPack", "air"),
    ("EnemyAIList_Land_ActionPack", "land"),
    ("EnemyAIList_Sea_ActionPack", "sea"),
)


def display(name):
    """'0016_Spyro' -> 'Spyro'."""
    return re.sub(r"^\d{4}_", "", name).replace("_", " ").strip()


def catalogue(catalog_bytes):
    """Every figure entry in the toy catalogue, with its charId.

    The catalogue is what the game resolves a toy to, so an entry here can be
    named by a `RacerAIInfo`. That is the full roster: the standalone game is
    forward compatible, so this includes every earlier figure plus the
    SuperChargers (and the variants: Series 2/3, LightCore, Eon's Elite, Dark...).
    """
    char_id, stats = {}, set()
    for w in pw.wrappers(catalog_bytes):
        key, name, roff, rlen, doff, dlen = pw.read_wrapper(catalog_bytes, w)
        if not name or doff is None:
            continue
        typ = struct.unpack_from(">I", catalog_bytes, doff + 20)[0]
        if typ == CATALOG_TYPE and re.match(r"^\d{4}_[A-Za-z]", name):
            if (name[:2] not in FIGURE_NUMBERS or PART_RE.search(name)
                    or NOT_A_FIGURE.search(name)):
                continue
            char_id[name] = key
        elif typ == STATS_TYPE and not VEHICLE_RE.search(name):
            base = re.sub(r"_?Stats$", "", name)
            if not PART_RE.search(base):
                stats.add(base)
    return char_id, stats


def figures(catalog_bytes):
    """Every fieldable figure: the catalogue entry with the stats (if any)."""
    char_id, stats = catalogue(catalog_bytes)
    return [(n, char_id[n]) for n in sorted(char_id)]


def stats_backed(catalog_bytes):
    """Names that ship their own stats object (the variants without one inherit
    the base figure's numbers at runtime)."""
    char_id, stats = catalogue(catalog_bytes)
    return {n for n in char_id if n in stats}


def base_name(name):
    """'0000_Whirlwind_Polar' -> '0000_Whirlwind'; used to reuse the base art."""
    n = name
    while True:
        m = VARIANT.search(n)
        if not m:
            return n
        n = n[:m.start()]


def slots(gameplay):
    """Every racer AI info a pool can field, with where its fields live."""
    infos, pools = {}, {}
    for w in pw.wrappers(gameplay):
        key, name, roff, rlen, doff, dlen = pw.read_wrapper(gameplay, w)
        if not name or doff is None:
            continue
        typ = struct.unpack_from(">I", gameplay, doff + 20)[0]
        if typ == INFO_TYPE:
            infos[name] = (w, key, roff, rlen, doff, dlen)
        elif typ == pw.LIST_TYPE:
            pools[name] = pw.body_fields(gameplay, doff)[4]

    villain_terrain = {}
    for pname, terrain in TERRAIN_POOLS:
        for k in pools.get(pname, []):
            for iname, spec in infos.items():
                if spec[1] == k and "_AIInfo" not in iname:
                    villain_terrain.setdefault(iname, terrain)

    out = []
    for iname, (w, key, roff, rlen, doff, dlen) in infos.items():
        m = DRIVER_RE.match(iname)
        if m:
            out.append({"info": iname, "terrain": m.group(2).lower(),
                        "kind": "driver", "slot": m.group(1),
                        "char_off": doff + 16 + 12,
                        "ref_off": roff, "ref_len": rlen})
        elif iname in villain_terrain:
            out.append({"info": iname, "terrain": villain_terrain[iname],
                        "kind": "villain", "slot": iname,
                        "char_off": doff + 16 + 12,
                        "ref_off": roff, "ref_len": rlen})
    out.sort(key=lambda s: (s["terrain"], s["kind"], s["info"]))
    return out


def current_roster(gameplay, slot_list, fig_by_key):
    cur = {}
    for i, s in enumerate(slot_list):
        fig = struct.unpack_from(">I", gameplay, s["char_off"])[0]
        cur[i] = fig_by_key.get(fig, "%08X" % fig)
    return cur


def character(name):
    """'0108_PopFizz_Series3_LovePotion' -> '0108': the toy, not the paint job."""
    m = re.match(r"^(\d{4})_", name)
    return m.group(1) if m else display(name)


def roll(slot_list, fig_list, seed=None, pins=(), avoid=None):
    """A figure for every slot, no repeats, `pins` guaranteed a seat.

    One figure per *character*: the catalogue holds 224 entries over 122 toys,
    so picking names freely puts a Series 2 and a LightCore of the same figure in
    one field, which reads as two identical racers. Each info is one racer, so a
    pool that lists an info twice still shows that figure twice - the pools
    themselves are deduplicated by `tools/pkz_pool_swap.py`.
    """
    rng = random.Random(seed)
    by_norm = {}
    for name, key in fig_list:
        by_norm.setdefault(norm(display(name)), (name, key))

    pinned = []
    for p in pins:
        hit = by_norm.get(norm(p))
        if hit and hit not in pinned:
            pinned.append(hit)
    if len(pinned) > len(slot_list):
        pinned = pinned[:len(slot_list)]

    pool = [f for f in fig_list if f not in pinned]
    rng.shuffle(pool)
    # least-recently-used first, so consecutive rolls keep moving
    if avoid:
        pool.sort(key=lambda f: avoid.get(f[0], 0))

    chosen = list(pinned)
    seen = {character(f[0]) for f in chosen}
    while len(chosen) < len(slot_list) and pool:
        fig = pool.pop()
        model = character(fig[0])
        if model in seen:
            continue
        seen.add(model)
        chosen.append(fig)
    while len(chosen) < len(slot_list):
        chosen.append(rng.choice(fig_list))
    rng.shuffle(chosen)

    # pins keep their seat, the rest fill around them
    assign = {}
    seats = sorted(range(len(slot_list)))
    rng.shuffle(seats)
    for pin in pinned:
        assign[seats.pop()] = pin
    for seat in seats:
        assign[seat] = chosen.pop()
    return assign


def apply(gameplay, slot_list, assign):
    """Write `charId` in place. Returns #changed.

    Only the character moves. The vehicle each info drives is already the one
    that is known to work on this disc (the drivers' own sub/buggy/plane, and the
    per-terrain `RentAWreck_*` on the villain infos), so it is never rewritten
    here - see `tools/pkz_random_bots.py` for how the base image sets it.
    """
    d = bytearray(gameplay)
    changed = 0
    for i, s in enumerate(slot_list):
        fig_name, fig_key = assign[i]
        old_char = struct.unpack_from(">I", d, s["char_off"])[0]
        if old_char != fig_key:
            struct.pack_into(">I", d, s["char_off"], fig_key)
            for j in range(s["ref_off"], s["ref_off"] + s["ref_len"], 8):
                if struct.unpack_from(">I", d, j + 4)[0] == old_char:
                    struct.pack_into(">I", d, j + 4, fig_key)
            changed += 1
    return bytes(d), changed


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())
