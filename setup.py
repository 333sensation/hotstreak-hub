#!/usr/bin/env python3
"""One-command setup: fetch wit, unpack your disc, make the baselines, build the image.

    python3 setup.py                  # guided setup - finds your game file itself
    python3 setup.py game.iso         # do the whole setup from a disc image
    python3 setup.py --auto           # the guided setup, no questions asked
    python3 setup.py --check          # only report what this machine is missing
    python3 setup.py --verify-rip     # only check your game file, change nothing
    python3 setup.py --fetch-wit      # only fetch Wiimms ISO Tool into tools/wit/
    python3 setup.py --force          # redo the steps even if they are there

The guided setup opens your game file with `wit` and checks it *before* it
unpacks anything (right game, right region, whole dump), so a half-finished
download or another region says so in one line instead of failing a minute later.

The one download is Wiimms ISO Tool (the only thing that can unpack and repack a
Wii image); it lands in `tools/wit/`, which is git-ignored and found again on the
next run. You still need your own copy of the disc and Dolphin - neither is
downloaded here, and this project never ships the game itself. Everything it
writes stays in this folder.
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


def run(cmd, quiet=False):
    """Run a step. quiet=True keeps the tool's chatter for the failure case only."""
    print("  $ %s" % " ".join(cmd))
    sys.stdout.flush()
    if quiet:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            tail = [ln for ln in ((proc.stdout or "") + (proc.stderr or "")).splitlines()
                    if ln.strip()][-6:]
            if tail:
                print("\n".join("  " + ln for ln in tail))
        return proc.returncode == 0
    return subprocess.run(cmd).returncode == 0


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


# --------------------------------------------------- finding the game yourself
# A ten-year-old should not have to type a path. These are the places a Wii dump
# actually ends up: next to this folder, in the usual home folders, and on a
# mounted external disk or SD card.
IMAGE_SUFFIXES = (".iso", ".wbfs", ".wia")
GAME_WORDS = ("skylander", "supercharger", "super charger", "super_chargers",
              "skne", "racing")
MIN_IMAGE = 100 * 1000 * 1000          # smaller than this is not a game disc
MAX_IMAGE = 9 * 1000 * 1000 * 1000     # a dual-layer Wii disc is 8.5 GB


def _subdirs(path, depth=1):
    """Directories under `path`, `depth` levels deep, skipping hidden ones."""
    try:
        entries = sorted(os.listdir(path))
    except OSError:
        return
    for name in entries:
        if name.startswith("."):
            continue
        full = os.path.join(path, name)
        if not os.path.isdir(full):
            continue
        yield full
        if depth > 1:
            for sub in _subdirs(full, depth - 1):
                yield sub


def search_places():
    """Folders worth looking in, most likely first."""
    home = os.path.expanduser("~")
    places = [HERE, os.path.dirname(HERE), os.getcwd(),
              os.path.join(home, "Downloads"),
              os.path.join(home, "Desktop"),
              os.path.join(home, "Documents"),
              home]
    if platform.system() == "Darwin":
        places += [os.path.join("/Volumes", d) for d in _names("/Volumes")]
    elif platform.system() == "Linux":
        for root in ("/media", "/run/media", "/mnt"):
            places += [os.path.join(root, d) for d in _names(root)]
            for user in _names(root):
                places += [os.path.join(root, user, d)
                           for d in _names(os.path.join(root, user))]
    out, seen = [], set()
    for p in places:
        real = os.path.realpath(p)
        if os.path.isdir(real) and real not in seen:
            seen.add(real)
            out.append(real)
    return out


def _names(path):
    try:
        return [n for n in sorted(os.listdir(path)) if not n.startswith(".")]
    except OSError:
        return []


def find_images():
    """Game images that look like this game, best guess first.

    Whole-disc dumps are large, so this is a stat call per file, not a read: a
    folder of a few hundred ROMs costs nothing. Folders reached twice are folded
    together by real path, and files whose name says nothing about this game are
    dropped as long as at least one name does.
    """
    found, seen = [], set()
    for place in search_places():
        for folder in [place] + list(_subdirs(place, depth=2)):
            if folder == TREE or folder.startswith(TREE + os.sep):
                continue                      # our own unpacked tree
            for name in _names(folder):
                low = name.lower()
                if not low.endswith(IMAGE_SUFFIXES):
                    continue
                path = os.path.join(folder, name)
                real = os.path.realpath(path)
                if real in seen:
                    continue                  # same file twice
                if (os.path.basename(path) == os.path.basename(IMAGE)
                        and os.path.exists(os.path.join(DATA, "BaseGameplay.pkz"))):
                    # our own build - skipped so a second run does not unpack the
                    # image it just made. With no tree yet it is the only file we
                    # have, so a release download with that name still counts.
                    continue
                try:
                    size = os.path.getsize(path)
                except OSError:
                    continue
                if not MIN_IMAGE < size < MAX_IMAGE:
                    continue
                seen.add(real)
                score = sum(1 for w in GAME_WORDS if w in low)
                found.append((score, size, real))
    if any(score for score, _s, _p in found):
        found = [f for f in found if f[0]]      # drop the ones with no hint in the name
    found.sort(key=lambda t: (-t[0], -t[1], t[2]))
    return found


def ask_for_image(announce=True):
    """Pick a game file: the obvious one if there is one, a numbered list if not."""
    cands = find_images()
    if not cands:
        return None
    best = cands[0]
    clear_winner = len(cands) == 1 or best[0] > cands[1][0]
    if clear_winner:
        if announce:
            print("  found it: %s  (%.1f GB)" % (best[2], best[1] / 1e9))
        return best[2]
    print("  I found %d game files:" % len(cands))
    for i, (_score, size, path) in enumerate(cands[:8], 1):
        print("    %d. %s  (%.1f GB)" % (i, path, size / 1e9))
    try:
        answer = input("  Which one? Type its number and press Enter: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    if answer.isdigit() and 1 <= int(answer) <= min(len(cands), 8):
        return cands[int(answer) - 1][2]
    print("  not a number from the list - no problem, nothing was changed")
    return None


def verify_image(path=None):
    """Run wit's own check on the built file. Returns (ok, the line it printed)."""
    path = path or IMAGE
    if not os.path.exists(path):
        return False, "no game file was built"
    wit = ensure_wit()
    if not wit:
        return False, "wit is missing"
    proc = subprocess.run([wit, "verify", path], capture_output=True, text=True)
    text = (proc.stdout or "") + (proc.stderr or "")
    lines = [ln.strip() for ln in text.replace("\r", "\n").splitlines() if ln.strip()]
    good = any("+OK" in ln for ln in lines) and any("SKNE52" in ln for ln in lines)
    detail = (next((ln for ln in lines if "+OK" in ln and "SKNE52" in ln), None)
              or next((ln for ln in lines if "+OK" in ln), None)
              or next((ln for ln in lines if "SKNE52" in ln), None)
              or (lines[-1] if lines else "no output from wit"))
    return good, detail


# -------------------------------------------------- checking your own game file
# `wit id` reads the six bytes at the start of a Wii disc: three letters for the
# game, the fourth for the region. That alone separates "a Wii game" from "a Wii
# game that is not this one"; `wit verify` then reads every block, and
# `wit files` (which only reads the file table) confirms the containers this mod
# edits are in there. No unpacking, nothing written.
GAME_CODE = "SKN"
GAME_TITLE = "Skylanders: SuperChargers Racing"
GAME_ID = "SKNE52"                 # the release this mod was built from
REGIONS = {"E": "USA", "P": "Europe", "J": "Japan", "K": "Korea"}
MOD_FILES = ("files/Data/BaseGameplay.pkz", "files/Data/BaseSkylander.pkz",
             "files/Data/Common.pkz")


def wit_id(wit, path):
    """The disc's six-byte game id, or None if wit cannot read the header."""
    proc = subprocess.run([wit, "id", path], capture_output=True, text=True,
                          timeout=300)
    for line in ((proc.stdout or "") + (proc.stderr or "")).splitlines():
        token = line.strip()
        if len(token) == 6 and token.isalnum() and token == token.upper():
            return token
    return None


def wit_files(wit, path):
    """Every file name inside the disc, straight out of its file table."""
    proc = subprocess.run([wit, "files", path], capture_output=True, text=True,
                          timeout=600)
    out = set()
    for line in (proc.stdout or "").splitlines():
        name = line.strip()
        while name.startswith("./"):
            name = name[2:]
        if name:
            out.add(name)
    return out


def check_rip(wit, path):
    """Look at one game file and judge it.

    Returns (verdict, [(whether it is good news, one line)], what to name in the
    failure case). verdict is one of: missing, not-wii, other-game, other-region,
    damaged, incomplete, good.
    """
    notes = []
    if not (path and os.path.isfile(path)):
        return "missing", notes, path
    ident = wit_id(wit, path)
    if not ident:
        return "not-wii", notes, None
    notes.append((True, "it is a Wii disc"))
    region = REGIONS.get(ident[3], "region %s" % ident[3])
    if ident[:3] != GAME_CODE:
        return "other-game", notes, ident
    if ident[3] != GAME_ID[3]:
        notes.append((True, "%s (%s)" % (GAME_TITLE, region)))
        return "other-region", notes, ident
    notes.append((True, "%s (%s)" % (GAME_TITLE, region)))

    proc = subprocess.run([wit, "verify", path], capture_output=True, text=True,
                          timeout=3600)
    text = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0 or "+OK" not in text:
        complaint = next((ln.strip().lstrip("!").strip() for ln in text.splitlines()
                          if ln.strip().startswith("!!") and "ERROR #" not in ln), "")
        return "damaged", notes, complaint or "wit stopped reading it"
    notes.append((True, "every block reads back without errors"))

    listed = wit_files(wit, path)
    gone = [os.path.basename(f) for f in MOD_FILES if f not in listed]
    if gone:
        notes.append((False, "%s %s missing from it"
                      % (" and ".join(gone), "are" if len(gone) > 1 else "is")))
        return "incomplete", notes, gone
    notes.append((True, "the three containers this mod edits are in it"))
    return "good", notes, ident


def verify_rip(path=None, guided=False):
    """Check the user's own game file and say, in plain words, what it is.

    `guided` is the setup's step 3: it already printed where it found the file,
    so that run only reports the findings, without the closing "you can start
    now" - the setup has four more steps to go before that is true.
    """
    try:                                  # keep our lines in order next to wit's
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass
    print("Checking your game file")
    wit = ensure_wit()
    if not wit:
        print("  I need wit to open game files, and it is not here.")
        print("  Run: python3 setup.py --fetch-wit")
        return False
    path = path or ask_for_image(announce=False)
    if not path:
        print("  I could not find a game file to check.")
        print("  Point me at yours:\n"
              "    python3 setup.py --verify-rip /path/to/your/game.iso")
        return False
    if not os.path.isfile(path):
        print("  There is no file at %s" % path)
        return False
    if not guided:
        print("  file   %s" % path)
        print("  size   %.2f GB" % (os.path.getsize(path) / 1e9))
    print("  reading it - about ten seconds for a full disc")
    sys.stdout.flush()

    verdict, notes, detail = check_rip(wit, path)
    for good, line in notes:
        ok(line) if good else todo(line)
    print()

    if verdict == "good":
        if not guided:
            print("GOOD - your game file is exactly what this mod needs (id %s)."
                  % detail)
            print("Nothing was changed and nothing needs fixing.")
            print("Double-click \"Start Hotstreak Hub\" and press PLAY.")
        return True

    if verdict == "missing":
        print("  I cannot check a file that is not there.\n"
              "  Full instructions: RIP-GUIDE.md")
    elif verdict == "not-wii":
        print("  That file is not a Wii game.\n"
              "  Either it is still downloading, or it is not a disc image.\n"
              "  A working file is named .iso, .wbfs or .wia and is about "
              "1.6 GB or more.")
        print("  How to make one from your own disc: RIP-GUIDE.md")
    elif verdict == "other-game":
        print("  That is a different game (id %s)." % detail)
        print("  This mod only works with %s for the Wii." % GAME_TITLE)
        print("  How to make the right file: RIP-GUIDE.md")
    elif verdict == "other-region":
        adjective = {"E": "American", "P": "European", "J": "Japanese",
                     "K": "Korean"}.get(detail[3], REGIONS.get(detail[3], "other-region"))
        print("  Right game, wrong region: that is the %s disc (%s)."
              % (adjective, detail))
        print("  This mod was built from the %s release (%s). The containers have "
              "the same names in every region but do not hold the same bytes, so "
              "patching another region gives you a disc that will not boot."
              % (REGIONS[GAME_ID[3]], GAME_ID))
        print("  RIP-GUIDE.md says which disc you need.")
    elif verdict == "damaged":
        print("  The file is incomplete or damaged: it stops partway through.")
        if detail:
            print("  (what wit said: %s)" % detail)
        print("  Dump the disc again (or let the download finish), then run this "
              "again.")
    elif verdict == "incomplete":
        print("  The file opens, but files are missing from inside it.")
        print("  That happens when a rip leaves parts out. Copy the whole disc "
              "again - RIP-GUIDE.md.")
    print("\n  Nothing was changed on your computer.")
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
        print("  wit is missing and could not be fetched - install Wiimms ISO Tool "
              "from https://wit.wiimm.de/ and set WIT=/path/to/wit")
        return False
    if os.path.exists(os.path.join(DATA, "BaseGameplay.pkz")):
        print("  disc tree already unpacked: %s" % TREE)
        ok("disc tree")
        return True
    if not os.path.isfile(iso):
        print("  There is no file at %s" % iso)
        return False
    print("  opening %s" % os.path.basename(iso))
    sys.stdout.flush()
    if not run([wit, "extract", iso, TREE], quiet=True):
        print("\n  That file did not open as a Wii game.")
        print("  Either it is still downloading, or it is not a Wii disc dump.")
        print("  A working file is named .iso, .wbfs or .wia and is about "
              "1.6 GB or more.")
        return False
    if not os.path.exists(os.path.join(DATA, "BaseGameplay.pkz")):
        print("  %s opened, but it is not Skylanders: SuperChargers Racing." % TREE)
        print("  This mod only works with that one game (Wii, SKNE52).")
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


# ------------------------------------------------------------- guided setup
TOTAL_STEPS = 5


def step(n, what):
    print("\n[%d/%d] %s" % (n, TOTAL_STEPS, what))
    sys.stdout.flush()


def ready():
    """Everything that matters is in place."""
    return (os.path.exists(os.path.join(DATA, "BaseGameplay.pkz"))
            and os.path.exists(IMAGE))


def auto(force=False, iso=None, verified=False):
    """The whole setup, in five steps, asking nothing if it can help it.

    This is what the double-click starter runs: find the game, open it, build the
    ready-to-play file, check it, say it is ready. `iso` skips the search, and
    `verified` skips the check because start.py has already run it on that file.
    """
    print("Hotstreak Hub - setup")
    print("=" * 20)

    step(1, "Checking this computer")
    if sys.version_info < (3, 9):
        print("  Python %s is too old. Install Python 3.9 or newer from "
              "https://www.python.org/downloads/" % sys.version.split()[0])
        return False
    ok("Python %s" % sys.version.split()[0])
    if not have("tkinter"):
        print("  Python is here but its window kit (tkinter) is not.")
        print("  Windows/macOS: reinstall Python from python.org, keeping the "
              "\"tcl/tk\" box ticked.")
        print("  Debian/Ubuntu: sudo apt install python3-tk   Fedora: sudo dnf "
              "install python3-tkinter")
        return False
    ok("the window kit")
    if not have("PIL"):
        print("  One small extra is missing; installing it now (no admin needed).")
        if not install_pillow():
            return False
    ok("Pillow %s" % __import__("PIL").__version__)

    step(2, "Getting the tool that opens Wii game files")
    wit = ensure_wit()
    if not wit:
        print("  I could not download it.")
        print("  Check your internet, then run this again - or install Wiimms ISO "
              "Tool by hand from https://wit.wiimm.de/ and set WIT=/path/to/wit")
        return False
    ok("ready")

    step(3, "Finding your game")
    if os.path.exists(os.path.join(DATA, "BaseGameplay.pkz")):
        ok("already opened - nothing to do")
    else:
        iso = iso or ask_for_image()
        if not iso:
            print("  I could not find it by myself.")
            print("  Drop your game file into this folder (%s) and run this again," % HERE)
            print("  or drag the file into this window and press Enter:")
            try:
                typed = input("  game file: ").strip().strip("'\"")
            except (EOFError, KeyboardInterrupt):
                typed = ""
            if typed and os.path.isfile(typed):
                iso = typed
            else:
                print("\n  No game file yet - that is the one part you have to bring.")
                print("  Full instructions: START-HERE.md")
                return False
        if not verified and not verify_rip(iso, guided=True):
            print("\n  Nothing was unpacked - fix the file above and run this again.")
            return False
        if not extract(iso):
            return False

    step(4, "Preparing the game (about a minute)")
    baselines()
    if force and os.path.exists(ART):
        os.remove(ART)
    art()

    step(5, "Building the ready-to-play file (a few minutes, about 1.5 GB)")
    if force and os.path.exists(IMAGE):
        os.remove(IMAGE)
    if not image():
        print("  The build did not finish. Run this again - it picks up where it "
              "stopped.")
        return False
    good, detail = verify_image()
    if good:
        ok("checked: %s" % detail)
    else:
        print("  The file was built but the check said: %s" % detail)
        print("  Run this again; if it repeats, delete %s and run it once more."
              % os.path.basename(IMAGE))
        return False

    print("\n" + "=" * 20)
    print("ALL DONE. Double-click \"Start Hotstreak Hub\" and press PLAY.")
    if not (PF.dolphin() if PF else None):
        print("\nOne more thing: Dolphin (the program that plays it) is not "
              "installed yet.\nGet it from https://dolphin-emu.org/download/ - "
              "then start this again.")
    return True


def install_pillow():
    """pip install --user pillow, trying the variants that fresh machines need."""
    attempts = [[sys.executable, "-m", "pip", "install", "--user", "--upgrade",
                 "pillow"],
                [sys.executable, "-m", "pip", "install", "--user",
                 "--break-system-packages", "--upgrade", "pillow"]]
    for cmd in attempts:
        print("  $ %s" % " ".join(cmd[1:]))
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0 and have("PIL"):
            return True
        if "externally-managed-environment" not in (proc.stdout + proc.stderr):
            break
    print("  That did not work. Paste this in a terminal, then run this again:")
    print("    %s -m pip install --user pillow" % sys.executable)
    return False


def main():
    ap = argparse.ArgumentParser(
        description="Hotstreak Hub - set this project up from your own copy of the disc.")
    ap.add_argument("iso", nargs="?", help="your Skylanders: SuperChargers Racing "
                                          "Wii image (.iso / .wbfs / .wia)")
    ap.add_argument("--auto", action="store_true",
                    help="guided setup: find the game file yourself and build the image")
    ap.add_argument("--force", action="store_true",
                    help="rebuild the image and the artwork even if they exist")
    ap.add_argument("--check", action="store_true", help="only report, change nothing")
    ap.add_argument("--verify-rip", action="store_true",
                    help="only check your game file: right game, right region, "
                         "whole dump - change nothing")
    ap.add_argument("--already-checked", action="store_true",
                    help="the game file has been checked already (start.py does "
                         "it before the setup starts); skip checking it again")
    ap.add_argument("--fetch-wit", action="store_true",
                    help="only fetch Wiimms ISO Tool into tools/wit/")
    ap.add_argument("--no-fetch", action="store_true",
                    help="never download wit; use an installed one")
    args = ap.parse_args()

    try:                                  # keep our lines in order next to wit's
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass

    global no_fetch
    no_fetch = args.no_fetch

    if args.fetch_wit:
        print("Wiimms ISO Tool %s" % WIT_VERSION)
        return 0 if fetch_wit() else 1

    if args.verify_rip:
        return 0 if verify_rip(args.iso) else 1

    if args.auto or (not args.iso and not args.check and not ready()):
        return 0 if auto(force=args.force, iso=args.iso,
                         verified=args.already_checked) else 1

    report()
    if args.check or not args.iso:
        if not args.iso and not os.path.exists(os.path.join(DATA, "BaseGameplay.pkz")):
            print("\nGive it your disc image to get started:\n"
                  "    python3 setup.py /path/to/Skylanders.iso")
        elif not args.iso:
            print("\nReady. Double-click \"Start Hotstreak Hub\" (this folder), "
                  "or run ./run.sh")
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
