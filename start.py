#!/usr/bin/env python3
"""Start Hotstreak Hub. This is the file the double-click starter runs.

It does the four things a new machine needs, in order, in plain language:

    1. is Python new enough, and does it have its window kit
    2. is Pillow there (installed quietly if not - no admin, no prompts)
    3. has this folder been set up from the game yet (setup.py --auto does it,
       including finding the game file)
    4. open the launcher window

    python3 start.py              # the whole thing
    python3 start.py --setup-only # stop after step 3
    python3 start.py --check      # say what is missing, change nothing

Nothing here downloads the game. You bring your own copy of the disc; this
project ships tools, never the game's files.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.join(HERE, "setup.py")
LAUNCHER = os.path.join(HERE, "launcher", "SkylandersLauncher.py")
IMAGE = os.path.join(HERE, "hotstreak-hub.wbfs")


def have(module):
    try:
        __import__(module)
        return True
    except Exception:                                        # noqa: BLE001
        return False


def say(text=""):
    print(text)
    sys.stdout.flush()


def pause_if_double_clicked():
    """Keep the window open so a double-clicked error can actually be read."""
    if sys.stdin is None or not sys.stdin.isatty():
        return
    try:
        input("\nPress Enter to close this window.")
    except (EOFError, KeyboardInterrupt):
        pass


def main(argv):
    check_only = "--check" in argv
    setup_only = "--setup-only" in argv

    say("Hotstreak Hub")
    say("=============")

    if sys.version_info < (3, 9):
        say("")
        say("This needs Python 3.9 or newer, and this computer has %s."
            % sys.version.split()[0])
        say("Get the new one from https://www.python.org/downloads/ - when it asks,")
        say("leave the 'tcl/tk' box ticked. Then start this again.")
        pause_if_double_clicked()
        return 1

    if not have("tkinter"):
        say("")
        say("Python is here, but the part that draws windows (tkinter) is not.")
        say("  Windows/macOS: reinstall Python from python.org and keep 'tcl/tk' ticked.")
        say("  Debian/Ubuntu: sudo apt install python3-tk")
        say("  Fedora:        sudo dnf install python3-tkinter")
        pause_if_double_clicked()
        return 1

    ready = os.path.exists(IMAGE) and os.path.exists(
        os.path.join(HERE, "disc", "files", "Data", "BaseGameplay.pkz"))
    if check_only:
        subprocess.run([sys.executable, SETUP, "--check"])
        say("")
        say("Image and setup: %s" % ("ready" if ready else "not built yet"))
        say("Pillow:          %s" % ("installed" if have("PIL") else "missing"))
        return 0

    if not ready:
        # setup.py knows how to install Pillow and how to find the game; let it
        rc = subprocess.call([sys.executable, SETUP, "--auto"])
        if rc != 0:
            pause_if_double_clicked()
            return rc
    else:
        say("Everything is already set up.")

    if not have("PIL"):
        say("")
        say("Pillow is still missing, so the window cannot open.")
        say("Paste this in a terminal and start again:")
        say("    %s -m pip install --user pillow" % sys.executable)
        pause_if_double_clicked()
        return 1

    if setup_only:
        say("Setup finished.")
        return 0

    say("")
    say("Opening the launcher...")
    return subprocess.call([sys.executable, LAUNCHER])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
