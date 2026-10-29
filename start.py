#!/usr/bin/env python3
"""Start Hotstreak Hub. This is the file the double-click starter runs.

It does the five things a new machine needs, in order, in plain language:

    1. is Python new enough, and does it have its window kit
    2. is the game file the right one, and is it whole (read only - nothing is
       unpacked yet, so a bad file costs ten seconds and not a minute)
    3. has this folder been set up from the game yet (setup.py --auto then does
       the heavy part: unpack, baselines, artwork, build, verify)
    4. is Pillow there (installed silently if not - no admin, no prompts)
    5. open the launcher window

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


def preflight_game():
    """Find the game file and check it, before the setup does anything.

    Returns (ok_to_continue, path). setup.py owns both halves - this only puts
    them in front of the wizard, so a half-finished download or a European disc
    is answered before any tool is downloaded or unpacked. If setup.py cannot be
    imported (an incomplete folder), this steps aside: the setup checks the file
    itself at its step 3.
    """
    try:
        sys.path.insert(0, HERE)
        import setup                                        # noqa: PLC0415
    except Exception:                                       # noqa: BLE001
        return True, None
    say("")
    say("Is your game file the right one?")
    try:
        path = setup.ask_for_image(announce=False)
    except Exception:                                       # noqa: BLE001
        return True, None
    if not path:
        say("  I have not found it yet - the setup will ask you for it.")
        return True, None
    say("  found it: %s  (%.1f GB)" % (path, os.path.getsize(path) / 1e9))
    return setup.verify_rip(path, guided=True), path


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
        good, game = preflight_game()
        if not good:
            say("")
            say("The setup has not started: nothing was unpacked and nothing was changed.")
            pause_if_double_clicked()
            return 1
        # setup.py knows how to install Pillow and how to finish the job; the
        # file was just checked, so name it and skip checking it a second time
        args = [sys.executable, SETUP, "--auto"]
        if game:
            args += [game, "--already-checked"]
        rc = subprocess.call(args)
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
