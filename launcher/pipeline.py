#!/usr/bin/env python3
"""The roster session and the build/launch steps behind the launcher window.

The only edit this disc tolerates is a same-size one (see FINDINGS.md), so a
roster is always written into a known-good copy of `BaseGameplay.pkz`
(`backups/BaseGameplay.pkz.working-randomcast`), then the image is rebuilt with
wit - that is what makes the change visible to Dolphin and to a real Wii.

Per boot: patch the pkz in the extracted tree -> `wit copy` the tree over
`skylanders-scr-mod.wbfs` (~10 s) -> start Dolphin on the image. `export()`
writes the same patched image into the layout a USB loader expects, which is the
path for real hardware.
"""
import hashlib
import os
import random
import shutil
import socket
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

IMAGE = os.path.join(ROOT, "skylanders-scr-mod.wbfs")
TREE = os.path.join(ROOT, "disc")
GAMEPLAY = os.path.join(TREE, "files", "Data", "BaseGameplay.pkz")
COMMON = os.path.join(TREE, "files", "Data", "Common.pkz")
BASE_PKZ = os.path.join(ROOT, "backups", "BaseGameplay.pkz.working-randomcast")
sys.path.insert(0, os.path.join(ROOT, "tools"))
import pkz_cup_random as CUPS   # noqa: E402  (needs the tools/ path above)
import platforms as PF

WIT = PF.wit()      # resolved again at build time (WIT env var may change)
GAME_ID = "SKNE52"
GAME_NAME = "Skylanders SuperChargers Racing"
TERRAINS = ("air", "land", "sea")
NETPLAY_PORT = 2626

# Session codes: what the two players type to end up with the same disc.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no I/O/0/1

def code_from_seed(seed, length=6):
    seed %= 32 ** length
    out = []
    for _ in range(length):
        seed, r = divmod(seed, 32)
        out.append(CODE_ALPHABET[r])
    return "".join(reversed(out))


def seed_from_code(code):
    seed = 0
    for ch in code.strip().upper():
        seed = seed * 32 + CODE_ALPHABET.index(ch)
    return seed


def new_code():
    return code_from_seed(random.randrange(32 ** 6))


def image_md5():
    h = hashlib.md5()
    with open(IMAGE, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def local_ip():
    """Best guess at the LAN address (a UDP connect does not send anything)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


class Session:
    """One roster: which figure sits in every racer slot."""

    def __init__(self):
        import assets
        import roster as R

        self.R = R
        self.data = assets.build()
        self.figures = self.data["figures"]
        self.by_display = {f["display"]: f for f in self.figures}
        self.gameplay = open(BASE_PKZ, "rb").read()
        self.slots = R.slots(self.gameplay)
        self.pins = []
        self.assign = {}
        self.roll()

    # ------------------------------------------------------------------ rolling
    def roll(self, seed=None, use_pins=True, stats_only=False):
        pool = [f for f in self.figures if f.get("stats")] if stats_only else self.figures
        if len(pool) < len(self.slots):
            pool = self.figures
        figs = [(f["name"], f["key"]) for f in pool]
        # pins are a solo-play convenience: a netplay cast has to be reproducible
        # from the session code alone, so both players ignore them
        pins = self.pins if use_pins else []
        self.assign = self.R.roll(self.slots, figs, seed=seed, pins=pins)
        self.seed = seed
        return self.assign

    def toggle_pin(self, display_name):
        if display_name in self.pins:
            self.pins.remove(display_name)
        else:
            self.pins.append(display_name)
        return display_name in self.pins

    # ------------------------------------------------------------------- views
    def figure_of(self, index):
        name, key = self.assign[index]
        disp = self.R.display(name)
        fig = self.by_display.get(disp) or {}
        return {
            "display": disp,
            "art": fig.get("art"),
            "info": self.slots[index]["info"],
            "kind": self.slots[index]["kind"],
            "pinned": disp in self.pins,
        }

    def groups(self):
        out = {t: [] for t in TERRAINS}
        for i, s in enumerate(self.slots):
            out[s["terrain"]].append(self.figure_of(i))
        return out

    def summary(self):
        g = self.groups()
        return {t: [f["display"] for f in g[t]] for t in TERRAINS}

    def patched_bytes(self):
        out, changed = self.R.apply(self.gameplay, self.slots, self.assign)
        if len(out) != len(self.gameplay):
            raise RuntimeError("patch changed the pkz size - refusing")
        return out, changed


class Pipeline:
    """Writes the roster out and gets the game running."""

    def __init__(self, log=None):
        self.log = log or (lambda line: None)

    def patch_tree(self, gameplay_bytes):
        with open(GAMEPLAY, "rb") as f:
            if f.read() == gameplay_bytes:
                self.log("roster already on disk")
                return False
        with open(GAMEPLAY, "wb") as f:
            f.write(gameplay_bytes)
        self.log("wrote BaseGameplay.pkz (%d bytes, size unchanged)" % len(gameplay_bytes))
        return True

    def patch_cups(self, seed=None, mirrors=False):
        """Roll a fresh track line-up into every cup (same file size).

        `seed` is what makes two netplay discs identical: the session code is
        turned into one, so both players get the same cups. Without a seed a
        new one is drawn, which is the solo "different every launch" case.
        """
        if seed is None:
            seed = random.randrange(32 ** 6)
        with open(COMMON, "rb") as f:
            src = f.read()
        out, report = CUPS.apply(src, seed, mirrors)
        if out == src:
            self.log("cups already rolled for this seed")
            return False
        with open(COMMON, "wb") as f:
            f.write(out)
        for terrain, _cup, _old, _new, _n in report:
            self.log("%s cup tracks rerolled (seed %s)" % (terrain, seed))
        return True

    def restore_cups(self):
        """Put the shipped cup line-ups back (the checkbox was turned off)."""
        pristine = os.path.join(ROOT, "backups", "Common.pkz.pristine")
        if not os.path.exists(pristine):
            return False
        with open(pristine, "rb") as f:
            want = f.read()
        with open(COMMON, "rb") as f:
            if f.read() == want:
                return False
        with open(COMMON, "wb") as f:
            f.write(want)
        self.log("cup tracks back to the shipped order")
        return True

    def build_image(self):
        wit = PF.wit()
        if not wit:
            raise RuntimeError(
                "wit (Wiimms ISO Tool) is required to rebuild the image - set the WIT "
                "environment variable to the wit binary for this OS")
        self.log("rebuilding image ...")
        proc = subprocess.run([wit, "copy", TREE, IMAGE, "--overwrite"],
                              capture_output=True, text=True)
        tail = [l.strip() for l in ((proc.stdout or "") + (proc.stderr or "")).splitlines()
                if l.strip() and not l.startswith("*****")]
        for line in tail[-2:]:
            self.log(line)
        if proc.returncode != 0:
            raise RuntimeError("wit copy failed (%d)" % proc.returncode)
        self.log("image ready (%.2f GB)" % (os.path.getsize(IMAGE) / 1e9))

    def verify_image(self):
        """`wit verify`: does the Wii see a well-formed disc?"""
        wit = PF.wit()
        if not wit:
            return True
        proc = subprocess.run([wit, "verify", IMAGE], capture_output=True, text=True)
        out = (proc.stdout or "") + (proc.stderr or "")
        for line in out.splitlines():
            if "+OK" in line or "DATA" in line:
                self.log(line.strip())
        return "+OK" in out

    def launch(self):
        self.log("starting Dolphin")
        subprocess.Popen(PF.dolphin_command(IMAGE),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def export(self, dest):
        folder = os.path.join(dest, "wbfs", "%s [%s]" % (GAME_NAME, GAME_ID))
        os.makedirs(folder, exist_ok=True)
        target = os.path.join(folder, "%s.wbfs" % GAME_ID)
        self.log("copying image to %s" % target)
        shutil.copy2(IMAGE, target)
        self.log("copied %.2f GB" % (os.path.getsize(target) / 1e9))
        return target


if __name__ == "__main__":
    s = Session()
    print("slots", len(s.slots), "pinned", s.pins)
    out, changed = s.patched_bytes()
    print("records rewritten:", changed, "size ok:", len(out) == len(s.gameplay))
    for t, names in s.summary().items():
        print("%-4s %d: %s" % (t, len(names), ", ".join(names)))
