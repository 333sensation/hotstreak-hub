#!/usr/bin/env python3
"""One-command setup: fetch wit, unpack your disc, make the baselines, build the image.

    python3 setup.py                  # report what this machine is missing
    python3 setup.py game.iso         # do the whole setup from a disc image
    python3 setup.py --fetch-wit      # only fetch Wiimms ISO Tool into tools/wit/
    python3 setup.py --force          # redo the steps even if they are there

The one download is Wiimms ISO Tool (the only thing that can unpack and repack a
Wii image); it lands in `tools/wit/`, which is git-ignored and found again on the
next run. You still need your own copy of the disc and Dolphin - neither is
downloaded here. Everything it writes stays in this folder.
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
TREE = os.path.join(HERE, "disc")
DATA = os.path.join(TREE, "files", "Data")
BACKUPS = os.path.join(HERE, "backups")
IMAGE = os.path.join(HERE, "hotstreak-hub.wbfs")
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

# ------------------------------------------------------------ Wiimms ISO Tool
# The only download in this project. wbfs/iso packing is not something we can
# reimplement, so: the official builds, per OS, unpacked into tools/wit/.
WIT_VERSION = "3.05a-r8638"
WIT_URL = "https://wit.wiimm.de/download/wit-v%s-%s.%s"
WIT_DIR = os.path.join(HERE, "tools", "wit")


def ok(msg):
    print("  ok      %s" % msg)


def todo(msg):
    print("  TO DO   %s" % msg)


def run(cmd):
    print("  $ %s" % " ".join(cmd))
    proc = subprocess.run(cmd)
    return proc.returncode == 0


def is_64bit():
    return sys.maxsize > 2 ** 32


def wit_flavour():
    """(flavour, extension) of the official build for this machine, or None."""
    machine = platform.machine().lower()
    system = platform.system()
    if system == "Darwin":
        return "mac", "tar.gz"          # universal: x86_64 + arm64
    if system == "Windows":
        return ("cygwin64" if is_64bit() else "cygwin32"), "zip"
    if system == "Linux":
        if machine in ("x86_64", "amd64"):
            return "x86_64", "tar.gz"
        if machine in ("i386", "i486", "i586", "i686", "x86"):
            return "i386", "tar.gz"
        return None                      # no build for arm/riscv/...
    return None


def _download(url, dest):
    print("  downloading %s" % url)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "hotstreak-hub setup"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            got = 0
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                out.write(chunk)
                got += len(chunk)
                if total:
                    pct = got * 100 // total
                    sys.stdout.write("\r  %3d%%  %.1f / %.1f MB" %
                                     (pct, got / 1e6, total / 1e6))
                    sys.stdout.flush()
        if total:
            print()
        return True
    except (urllib.error.URLError, OSError) as exc:
        print("\n  download failed: %s" % exc)
        return False


def _unpack(archive, into):
    if archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(into)
    else:
        with tarfile.open(archive) as t:
            t.extractall(into)


def _payload_root(folder):
    """The unwrapped folder that holds bin/[wit|wit.exe]."""
    for root, dirs, _files in os.walk(folder):
        if "bin" in dirs:
            return root
    return None


def _sign_macos(binaries):
    """macOS ships wit linker-signed, which arm64 refuses to execute.

    Ad-hoc signing it locally (`codesign --force --sign -`) is what makes the
    official build run; without this the kernel kills it with signal 9.
    """
    codesign = shutil.which("codesign")
    if not codesign:
        print("  codesign not found (install the Xcode command line tools)")
        return
    for path in binaries:
        subprocess.run([codesign, "--force", "--sign", "-", path],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def fetch_wit():
    """Download Wiimms ISO Tool into tools/wit/ and return the executable path."""
    flavour = wit_flavour()
    if not flavour:
        todo("no official wit build for %s/%s - get one from https://wit.wiimm.de/ "
             "and point WIT=/path/to/wit at it" % (platform.system(), platform.machine()))
        return None
    name, ext = flavour
    url = WIT_URL % (WIT_VERSION, name, ext)

    tmp = tempfile.mkdtemp(prefix="wit-fetch-")
    archive = os.path.join(tmp, "wit.%s" % ext)
    try:
        if not _download(url, archive):
            todo("wit - download failed; try again, or install it by hand from "
                 "https://wit.wiimm.de/ and set WIT=/path/to/wit")
            return None
        print("  unpacking")
        _unpack(archive, tmp)
        root = _payload_root(tmp)
        if not root:
            todo("wit - the download did not look like a wit release")
            return None
        if os.path.isdir(WIT_DIR):
            shutil.rmtree(WIT_DIR)
        shutil.copytree(root, WIT_DIR)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    bindir = os.path.join(WIT_DIR, "bin")
    exe = os.path.join(bindir, "wit.exe" if platform.system() == "Windows" else "wit")
    for entry in os.listdir(bindir):
        path = os.path.join(bindir, entry)
        if os.path.isfile(path):
            try:
                os.chmod(path, 0o755)
            except OSError:
                pass
    if platform.system() == "Darwin":
        _sign_macos([os.path.join(bindir, e) for e in os.listdir(bindir)])

    try:
        proc = subprocess.run([exe, "--version"], capture_output=True, text=True,
                              timeout=30)
        line = (proc.stdout or proc.stderr).strip().splitlines()[0]
    except (OSError, subprocess.SubprocessError, IndexError):
        todo("wit - fetched, but it will not run; try WIT=/path/to/wit")
        return None
    ok("wit %s (%s)" % (line, exe))
    return exe


def ensure_wit():
    """The wit to use: already installed, or fetched into tools/wit/."""
    found = PF.wit() if PF else shutil.which("wit")
    if found:
        return found
    if no_fetch:
        return None
    return fetch_wit()


def have(module):
    try:
        __import__(module)
        return True
    except Exception:                                        # noqa: BLE001
        return False


# set by main(); --no-fetch turns the wit download off
no_fetch = False


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
    elif wit_flavour():
        todo("wit - not here yet; it is fetched into tools/wit/ on the first run "
             "(or now: python3 setup.py --fetch-wit)")
    else:
        todo("wit - no official build for %s/%s; install it from "
             "https://wit.wiimm.de/ and set WIT=/path/to/wit"
             % (platform.system(), platform.machine()))

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
    wit = ensure_wit()
    if not wit:
        print("wit is missing and could not be fetched - install Wiimms ISO Tool "
              "from https://wit.wiimm.de/ and set WIT=/path/to/wit")
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
    wit = ensure_wit()
    if not wit:
        todo("image - skipped, wit is missing")
        return False
    return run([wit, "copy", TREE, IMAGE])


def main():
    ap = argparse.ArgumentParser(
        description="Hotstreak Hub - set this project up from your own copy of the disc.")
    ap.add_argument("iso", nargs="?", help="your Skylanders: SuperChargers Racing "
                                          "Wii image (.iso / .wbfs / .wia)")
    ap.add_argument("--force", action="store_true",
                    help="rebuild the image and the artwork even if they exist")
    ap.add_argument("--check", action="store_true", help="only report, change nothing")
    ap.add_argument("--fetch-wit", action="store_true",
                    help="only fetch Wiimms ISO Tool into tools/wit/")
    ap.add_argument("--no-fetch", action="store_true",
                    help="never download wit; use an installed one")
    args = ap.parse_args()

    global no_fetch
    no_fetch = args.no_fetch

    if args.fetch_wit:
        print("Wiimms ISO Tool %s" % WIT_VERSION)
        return 0 if fetch_wit() else 1

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
