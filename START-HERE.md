# Start here

Four things, in order. The whole setup is one double-click after step 1.

## 1. Install Python (once)

<https://www.python.org/downloads/> — run the installer and tick **"tcl/tk and
IDLE"** if it asks. That box draws the window.

Already have a terminal and Python? Skip to 2.

## 2. Have the game as a file

You need your **own** copy of *Skylanders: SuperChargers Racing* for the Wii — the
disc, copied to a file on the computer (`.iso`, `.wbfs` or `.wia`, about 1.6 GB).
Same file Dolphin or a USB loader would need.

This project does **not** include the game, and it never will — the game is
Nintendo's and Activision's, not ours. You bring the file; everything else is
free.

Where to put it: anywhere the computer can see it. `Downloads` is perfect — you
do not have to move it.

## 3. Double-click **Start Hotstreak Hub**

| | |
|---|---|
| macOS | `Start Hotstreak Hub.command` |
| Windows | `Start Hotstreak Hub.bat` |
| Linux | `./run.sh` in a terminal |

The first time it runs it does everything by itself and tells you what it is
doing, in five short steps:

1. checks Python and the window kit
2. downloads the one tool that opens Wii game files (`wit`, 2 MB, into
   `tools/wit/`)
3. finds your game file — in this folder, your Downloads, your Desktop, or on a
   plugged-in disk — and opens it
4. prepares it (about a minute)
5. builds the ready-to-play file (`hotstreak-hub.wbfs`, about 1.6 GB) and checks
   it

When it says **ALL DONE**, the launcher is open. Press **PLAY**.

If it cannot find your game file, it says so and asks you to drag the file into
the window. That is the only question it ever asks.

## 4. Play

Install [Dolphin](https://dolphin-emu.org/download/) if you have not, then press
PLAY in the launcher: it rolls a new field of opponents and boots the game.

You never install Dolphin? You can still build the image and copy it to a Wii
with a USB loader — the launcher has **EXPORT** for that.

---

## If something is wrong

| what you see | what to do |
|---|---|
| "This needs Python 3.9 or newer" | install Python from the link in step 1, tick tcl/tk |
| "I could not find it by myself" | drop your game file anywhere in this folder and double-click the starter again |
| "That file did not open as a Wii game" | the file is still downloading, or it is not a Wii dump — `.iso` / `.wbfs` / `.wia`, about 1.6 GB |
| "Dolphin is not installed yet" | install it from the link in step 4 and start again |
| the window opens but PLAY does nothing | run `python3 setup.py --check` — it names the missing piece in one line |

Everything the setup makes stays inside this folder. Nothing is installed
system-wide except Python, no admin password is needed, and deleting the folder
undoes all of it.
