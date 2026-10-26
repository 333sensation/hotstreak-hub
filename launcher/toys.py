#!/usr/bin/env python3
"""The toy library: real Skylanders tag dumps, and putting one on the portal.

This disc does not take the figure you race as from the pkz files - the game
reads it off the Portal of Power, and Dolphin emulates that portal. So the
"which Skylander do I play" choice belongs here, not in the disc patch:

* `../skylanders-nfc-sim/data` holds 782 real tag images (1024 bytes each, the
  size Dolphin's emulated portal expects: `FIGURE_SIZE = 0x40 * 0x10`);
  `roster.json` names them - 429 figures, 35 vehicles, plus traps/crystals.
* `install()` writes the chosen toys into `portal/`, which is pointed at with
  Dolphin's `SkylandersCollectionPath`, so they show up in the portal window.
* `enable_portal()` flips `EmulateSkylanderPortal` on in `Dolphin.ini` (backup
  kept once), so the emulated portal is there when the game asks for one.

Nothing here touches the disc, so the choice is live: swap in the portal window
while the game is running.
"""
import gzip
import json
import os
import re
import shutil

import platforms as PF

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(os.path.dirname(ROOT), "skylanders-nfc-sim", "data")
DUMP_SIZE = 0x40 * 0x10          # Dolphin: BLOCK_COUNT * BLOCK_SIZE

PORTAL = os.path.join(HERE, "portal")
CACHE = os.path.join(HERE, "cache")
SELECTION = os.path.join(CACHE, "toys.json")

KINDS = {"figure": "Skylander", "mini": "Mini", "vehicle": "Vehicle",
         "trap": "Trap", "crystal": "Crystal", "magic": "Magic item",
         "chest": "Chest"}


class Toy:
    __slots__ = ("index", "name", "base", "variant", "game", "kind", "uid", "element")

    def __init__(self, index, entry):
        self.index = index
        self.name = entry.get("n") or "?"
        self.base = entry.get("b") or self.name
        self.variant = entry.get("v") or ""
        self.game = entry.get("gn") or ""
        self.kind = entry.get("t") or "figure"
        self.uid = entry.get("u") or ""
        self.element = entry.get("e") or ""

    @property
    def label(self):
        return self.name

    @property
    def kind_label(self):
        return KINDS.get(self.kind, self.kind.title())

    def __repr__(self):
        return "<Toy %s %s %s>" % (self.kind, self.label, self.uid)


_roster = None
_dumps = None


def _load():
    global _roster, _dumps
    if _roster is not None:
        return
    with open(os.path.join(DATA, "roster.json")) as f:
        entries = json.load(f)
    with gzip.open(os.path.join(DATA, "dumps.bin.gz"), "rb") as f:
        raw = f.read()
    if len(raw) != len(entries) * DUMP_SIZE:
        raise RuntimeError("toy library is malformed: %d bytes for %d entries"
                           % (len(raw), len(entries)))
    _roster = [Toy(i, e) for i, e in enumerate(entries)]
    _dumps = raw


def all_toys():
    _load()
    return list(_roster)


def of_kind(kind):
    _load()
    return [t for t in _roster if t.kind == kind]


def figures():
    _load()
    return [t for t in _roster if t.kind in ("figure", "mini")]


def vehicles():
    return of_kind("vehicle")


def dump(toy):
    """The 1024-byte tag image for one toy."""
    _load()
    start = toy.index * DUMP_SIZE
    return _dumps[start:start + DUMP_SIZE]


def slug(name):
    s = re.sub(r"[^A-Za-z0-9]+", " ", name).strip()
    return s or "toy"


# ------------------------------------------------------------------ the portal
def _write(toy, folder):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "%s (%s).sky" % (slug(toy.name), toy.uid))
    data = dump(toy)
    if len(data) != DUMP_SIZE:
        raise RuntimeError("dump for %s is %d bytes" % (toy.name, len(data)))
    with open(path, "wb") as f:
        f.write(data)
    return path


def install(pair, folder=PORTAL):
    """Put a figure and a vehicle in the collection folder (and drop older ones).

    `pair` maps kind -> Toy (usually {"figure": ..., "vehicle": ...}); anything
    not in it is removed, so the collection Dolphin shows is the current choice.
    """
    os.makedirs(folder, exist_ok=True)
    keep = set()
    for toy in pair.values():
        if toy is not None:
            keep.add(os.path.basename(_write(toy, folder)))
    for name in os.listdir(folder):
        if name.endswith(".sky") and name not in keep:
            try:
                os.remove(os.path.join(folder, name))
            except OSError:
                pass
    return sorted(keep)


def installed(folder=PORTAL):
    if not os.path.isdir(folder):
        return []
    return sorted(n for n in os.listdir(folder) if n.endswith(".sky"))


# ------------------------------------------------------- Dolphin configuration
def _ini_set(text, section, key, value):
    """Set one `key = value` inside `[section]`, keeping the rest byte-identical."""
    lines = text.splitlines()
    header = "[%s]" % section
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == header)
    except StopIteration:
        if text and not text.endswith("\n"):
            text += "\n"
        return text + header + "\n" + "%s = %s\n" % (key, value)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("[")),
               len(lines))
    for i in range(start + 1, end):
        if re.match(r"\s*%s\s*=" % re.escape(key), lines[i]):
            new = lines[:i] + ["%s = %s" % (key, value)] + lines[i + 1:]
            return "\n".join(new) + "\n"
    new = lines[:end] + ["%s = %s" % (key, value)] + lines[end:]
    return "\n".join(new) + "\n"


def _ini_drop(text, section, key):
    """Remove a key from a section (cleanup for keys written in the wrong place)."""
    lines = text.splitlines()
    header = "[%s]" % section
    if header not in [l.strip() for l in lines]:
        return text
    start = next(i for i, line in enumerate(lines) if line.strip() == header)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("[")),
               len(lines))
    keep = [l for i, l in enumerate(lines)
            if not (start < i < end and re.match(r"\s*%s\s*=" % re.escape(key), l))]
    return "\n".join(keep) + "\n"


def enable_portal(collection=PORTAL, enable=True):
    """Point Dolphin at the collection and turn the emulated portal on.

    Returns a note for the status line; raises nothing if Dolphin has never run
    on this machine (the settings are simply written where it would read them).
    """
    ini = PF.dolphin_ini()
    if not ini:
        return "no Dolphin config directory for this OS"
    text = ""
    if os.path.exists(ini):
        with open(ini, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        backup = ini + ".launcher-backup"
        if not os.path.exists(backup):
            shutil.copy2(ini, backup)
    # Dolphin's own keys: the toggle lives in [EmulatedUSBDevices], the folder
    # in [General] (MainSettings: MAIN_EMULATE_SKYLANDER_PORTAL / MAIN_SKYLANDERS_PATH)
    text = _ini_set(text, "EmulatedUSBDevices", "EmulateSkylanderPortal",
                    "True" if enable else "False")
    text = _ini_set(text, "General", "SkylandersCollectionPath",
                    os.path.abspath(collection))
    text = _ini_drop(text, "Core", "SkylandersCollectionPath")
    os.makedirs(os.path.dirname(ini), exist_ok=True)
    with open(ini, "w", encoding="utf-8") as f:
        f.write(text)
    return "Dolphin portal ready (%s)" % os.path.basename(ini)


# ------------------------------------------------------------------- selection
def load_selection():
    try:
        with open(SELECTION) as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return {}, {}
    toys = {(t.kind, t.name): t for t in all_toys()}
    picked = {}
    for kind, name in saved.items():
        toy = toys.get((kind, name))
        if toy is not None:
            picked[kind] = toy
    return picked, saved


def save_selection(pair):
    os.makedirs(CACHE, exist_ok=True)
    with open(SELECTION, "w") as f:
        json.dump({k: t.name for k, t in pair.items() if t is not None}, f, indent=1)


if __name__ == "__main__":
    toys = all_toys()
    print("toys %d: %s" % (len(toys), ", ".join(
        "%s %d" % (KINDS[k], n) for k, n in
        ((k, sum(1 for t in toys if t.kind == k)) for k in KINDS))))
    spyro = next((t for t in toys if t.name.lower().startswith("spyro")), toys[0])
    print("first:", spyro, len(dump(spyro)), "bytes")
    print("installed:", installed())
    print(enable_portal())
