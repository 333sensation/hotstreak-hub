#!/usr/bin/env python3
"""One-command setup: unpack your disc, make the baselines, build the image.

    python3 setup.py                  # report what this machine is missing
    python3 setup.py game.iso         # do the whole setup from a disc image
    python3 setup.py --force          # redo the steps even if they are there

Nothing here downloads anything: you need your own copy of the disc, `wit`
(Wiimms ISO Tool) and Dolphin. Everything it writes stays in this folder and is
git-ignored - the disc tree, the pkz baselines and the built `.wbfs`.
"""
import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TREE = os.path.join(HERE, "disc")
DATA = os.path.join(TREE, "files", "Data")
BACKUPS = os.path.join(HERE, "backups")
IMAGE = os.path.join(HERE, "skylanders-scr-mod.wbfs")
ART = os.path.join(HERE, "launcher", "assets", "art.json")
TOYS = os.path.join(os.path.dirname(HERE), "skylanders-nfc-sim", "data")

# baselines the launcher and the tools patch from; each is a copy of the file
# the disc ships, made once
BASELINES = (
    ("BaseGameplay.pkz", "BaseGameplay.pkz.pristine"),
    ("BaseGameplay.pkz", "BaseGameplay.pkz.working-randomcast"),
    ("BaseSkylander.pkz", "BaseSkylander.pkz.pristine"),
    ("Common.pkz", "Common.pkz.pristine"),
)

sys.path.insert(0, os.path.join(HERE, "launcher"))
try:
    import platforms as PF
except Exception:                                            # noqa: BLE001
    PF = None


def ok(msg):
    print("  ok      %s" % msg)


def todo(msg):
    print("  TO DO   %s" % msg)


def run(cmd):
    print("  $ %s" % " ".join(cmd))
    proc = subprocess.run(cmd)
    return proc.returncode == 0


def have(module):
    try:
        __import__(module)
        return True
    except Exception:                                        # noqa: BLE001
        return False


def report():
    """What this machine has and what it is missing."""
    print("Python  %s" % sys.version.split()[0])
    if sys.version_info < (3, 9):
        todo("Python 3.9 or newer is required")
    else:
        ok("Python 3.9+")

    ok("tkinter") if have("tkinter") else todo(
        "tkinter - Debian/Ubuntu: sudo apt install python3-tk, "
        "Fedora: sudo dnf install python3-tkinter, Windows: reinstall Python "
        "from python.org with tcl/tk checked")
    ok("Pillow") if have("PIL") else todo("Pillow - python3 -m pip install pillow")

    wit = PF.wit() if PF else shutil.which("wit")
    if wit:
        ok("wit      %s" % wit)
    else:
        todo("wit - Wiimms ISO Tool, https://wit.wiimm.de/ ; put it on PATH, in "
             "tools/wit/, or point WIT=/path/to/wit at it")

    dolphin = PF.dolphin() if PF else None
    if dolphin:
        ok("Dolphin  %s" % dolphin)
    else:
        todo("Dolphin - needed to play, not to patch: https://dolphin-emu.org/ "
             "(or set DOLPHIN=/path/to/Dolphin)")

    if os.path.exists(os.path.join(DATA, "BaseGameplay.pkz")):
        ok("disc tree  %s" % TREE)
    else:
        todo("disc tree - run: python3 setup.py /path/to/your/disc.iso")

    missing = [b for _, b in BASELINES if not os.path.exists(os.path.join(BACKUPS, b))]
    ok("baselines") if not missing else todo("baselines - %s" % ", ".join(missing))

    if os.path.exists(IMAGE):
        ok("image      %s (%.1f GB)" % (IMAGE, os.path.getsize(IMAGE) / 1e9))
    else:
        todo("image - built from the disc tree on the first PLAY, or run "
             "python3 setup.py again once the tree is there")

    if os.path.exists(ART):
        ok("artwork    extracted")
    else:
        todo("artwork - python3 tools/extract_art.py (the launcher draws with the "
             "game's own portraits)")

    if os.path.exists(os.path.join(TOYS, "dumps.bin.gz")):
        ok("toy library  %s" % TOYS)
    else:
        todo("toy library - optional, only the YOUR SKYLANDER portal picker needs "
             "it (%s)" % TOYS)


def extract(iso):
    wit = PF.wit() if PF else shutil.which("wit")
    if not wit:
        print("wit is missing - install Wiimms ISO Tool first (see above).")
        return False
    if os.path.exists(os.path.join(DATA, "BaseGameplay.pkz")):
        print("  disc tree already unpacked: %s" % TREE)
        ok("disc tree")
        return True
    if not os.path.isfile(iso):
        print("  no such disc image: %s" % iso)
        return False
    if not run([wit, "extract", iso, TREE]):
        print("  wit extract failed - is that a GameCube/Wii image?")
        return False
    if not os.path.exists(os.path.join(DATA, "BaseGameplay.pkz")):
        print("  %s was unpacked but has no files/Data/BaseGameplay.pkz" % TREE)
        return False
    ok("disc tree")
    return True


def baselines():
    os.makedirs(BACKUPS, exist_ok=True)
    made = 0
    for src, dst in BASELINES:
        target = os.path.join(BACKUPS, dst)
        source = os.path.join(DATA, src)
        if os.path.exists(target) or not os.path.exists(source):
            continue
        shutil.copy2(source, target)
        made += 1
    if made:
        ok("%d baseline%s" % (made, "" if made == 1 else "s"))
    else:
        ok("baselines")


def art():
    if os.path.exists(ART):
        ok("artwork")
        return True
    if not have("PIL"):
        todo("artwork - skipped, Pillow is missing")
        return False
    return run([sys.executable, os.path.join(HERE, "tools", "extract_art.py")])


def image():
    if os.path.exists(IMAGE):
        ok("image")
        return True
    wit = PF.wit() if PF else shutil.which("wit")
    if not wit:
        todo("image - skipped, wit is missing")
        return False
    return run([wit, "copy", TREE, IMAGE])


def main():
    ap = argparse.ArgumentParser(
        description="Set this project up from your own copy of the disc.")
    ap.add_argument("iso", nargs="?", help="your Skylanders: SuperChargers Racing "
                                          "Wii image (.iso / .wbfs / .wia)")
    ap.add_argument("--force", action="store_true",
                    help="rebuild the image and the artwork even if they exist")
    ap.add_argument("--check", action="store_true", help="only report, change nothing")
    args = ap.parse_args()

    report()
    if args.check or not args.iso:
        if not args.iso and not os.path.exists(os.path.join(DATA, "BaseGameplay.pkz")):
            print("\nGive it your disc image to get started:\n"
                  "    python3 setup.py /path/to/Skylanders.iso")
        elif not args.iso:
            print("\nReady. Start the launcher with:\n    ./run.sh          "
                  "(Windows: run.cmd)")
        return 0

    print("\nSetting up")
    if args.force and os.path.exists(TREE):
        print("  --force: rebuilding from the existing disc tree")
    if not extract(args.iso):
        return 1
    baselines()
    if args.force and os.path.exists(ART):
        os.remove(ART)
    art()
    if args.force and os.path.exists(IMAGE):
        os.remove(IMAGE)
    image()
    print("\nDone. Start the launcher with:\n    ./run.sh          (Windows: run.cmd)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
