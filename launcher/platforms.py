#!/usr/bin/env python3
"""Everything that differs between Windows, Linux and macOS.

The launcher core (roster, patching, sessions) is plain Python and identical
everywhere; only the emulator, the disc tool, the fonts and the pointer cursor
change per platform. Android has no tkinter, so this UI cannot run there - the
modules under it can, which is why the platform bits are kept in here.
"""
import os
import platform
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"

# --------------------------------------------------------------------- fonts
UI = {"Darwin": "Helvetica Neue", "Windows": "Segoe UI"}.get(platform.system(), "DejaVu Sans")
MONO = {"Darwin": "Menlo", "Windows": "Consolas"}.get(platform.system(), "DejaVu Sans Mono")
HAND = "pointinghand" if IS_MAC else "hand2"


def ui_font(size=11, bold=False):
    return (UI, size, "bold") if bold else (UI, size)


def mono_font(size=10, bold=False):
    return (MONO, size, "bold") if bold else (MONO, size)


def _existing(paths):
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


# ------------------------------------------------------------------- dolphin
def dolphin():
    """Path to the Dolphin executable on this machine (or None)."""
    env = os.environ.get("DOLPHIN")
    if env and os.path.exists(env):
        return env
    if IS_MAC:
        return _existing(["/Applications/Dolphin.app/Contents/MacOS/Dolphin",
                          os.path.expanduser("~/Applications/Dolphin.app/Contents/MacOS/Dolphin")])
    if IS_WIN:
        roots = [os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                 os.environ.get("LOCALAPPDATA", "")]
        cands = []
        for r in roots:
            cands += [os.path.join(r, "Dolphin-x64", "Dolphin.exe"),
                      os.path.join(r, "Dolphin", "Dolphin.exe"),
                      os.path.join(r, "Dolphin", "DolphinQt2.exe")]
        return _existing(cands) or shutil.which("Dolphin.exe") or shutil.which("dolphin-emu.exe")
    return (_existing(["/usr/bin/dolphin-emu", "/usr/games/dolphin-emu", "/snap/bin/dolphin-emu"])
            or shutil.which("dolphin-emu"))


def dolphin_command(image, backend=True):
    """argv that boots `image`, with a video backend that works on this OS."""
    exe = dolphin()
    if not exe:
        raise RuntimeError("Dolphin not found - set the DOLPHIN environment variable")
    cmd = [exe]
    if backend:
        # Metal fails to build this disc's vertex pipelines on macOS; the other
        # platforms pick their own sane default, so only macOS is forced.
        if IS_MAC:
            cmd += ["-v", "ogl"]
    return cmd + ["-e", image]


# ----------------------------------------------------------------------- wit
def wit():
    """Wiimms ISO Tool: WIT env var, a bundled copy, then PATH.

    The tree is repacked with it after every roster change, so Windows and
    Linux users need the binary for their OS (wiimms-iso-tools releases).
    """
    exe = "wit.exe" if IS_WIN else "wit"
    env = os.environ.get("WIT")
    cands = [env,
             os.path.join(ROOT, "tools", "wit", "wit"),
             os.path.join(ROOT, "tools", "wit", exe),
             # `python3 setup.py --fetch-wit` unpacks the official build here
             os.path.join(ROOT, "tools", "wit", "bin", exe),
             os.path.join(ROOT, "..", "DolRecomp", "extern", "wit", "bin", exe)]
    found = _existing([c for c in cands if c])
    if found:
        return found
    return shutil.which("wit") or shutil.which("wit.exe")


# --------------------------------------------------------------------- misc
def home_dir():
    return os.path.expanduser("~")


def dolphin_config_dir():
    """Where Dolphin keeps `Dolphin.ini` on this OS (first one that exists)."""
    home = home_dir()
    cands = [
        os.environ.get("DOLPHIN_CONFIG_DIR"),
        os.path.join(home, "Library", "Application Support", "Dolphin", "Config") if IS_MAC else None,
        os.path.join(os.environ.get("APPDATA", ""), "Dolphin Emulator", "Config") if IS_WIN else None,
        os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"),
                     "dolphin-emu") if IS_LINUX else None,
    ]
    found = _existing([c for c in cands if c])
    if found:
        return found
    # nothing exists yet: name the path Dolphin would create
    return [c for c in cands if c][0] if any(cands) else None


def dolphin_ini():
    d = dolphin_config_dir()
    return os.path.join(d, "Dolphin.ini") if d else None


def platform_name():
    return {"Darwin": "macOS", "Windows": "Windows"}.get(platform.system(), platform.system())
