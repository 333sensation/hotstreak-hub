# Skylanders SuperChargers Racing — roster launcher

A launcher window for the modded image in `scr-wii/`. It holds the game, rolls a
new cast of opponents before every boot, writes that cast into the disc and
starts it. All artwork in the window is the game's own, pulled out of the disc by
`tools/extract_art.py` (556 portraits, 216 minimap icons, the title logo).

## Run it

From the repo root: `./run.sh` (Windows: `run.cmd`). It starts this folder's
`run.sh`, which checks Python, tkinter and Pillow before opening the window.

| OS | start |
|---|---|
| macOS | `./"Skylanders Launcher.command"` or `./run.sh` |
| Linux | `./run.sh` |
| Windows | `run.cmd` |

First run on a new machine: `./run.sh --check` (or `run.cmd --check`) prints
whether Python, tkinter, Pillow, Dolphin and `wit` were found and where.

Requirements: Python 3.9+ with tkinter (`apt install python3-tk` on
Debian/Ubuntu, `dnf install python3-tkinter` on Fedora, the python.org installer
on Windows), `pip install pillow`, Dolphin, and Wiimms ISO Tool (`wit`).

Paths are found automatically; override them with environment variables when the
auto-detect guesses wrong:

    DOLPHIN=/path/to/Dolphin      WIT=/path/to/wit

## What the buttons do

| | |
|---|---|
| **PLAY** | rolls a cast, patches `BaseGameplay.pkz`, rebuilds `skylanders-scr-mod.wbfs` (~10 s) and starts Dolphin |
| **ROLL NEW CAST** | rolls without booting, so you can look at the field first |
| **PIN FIGURES** | figures that must appear in every solo cast (click a portrait in the grid to pin it) |
| **PLAY WITH A FRIEND** | netplay session browser — see below |
| **YOUR SKYLANDER** | picks the figure *you* race as and its vehicle, and puts them on Dolphin's emulated portal — see below |
| **EXPORT TO SD CARD** | writes the patched image to `<card>/wbfs/Skylanders SuperChargers Racing [SKNE52]/SKNE52.wbfs` for a real Wii |
| *new cast every launch* | on by default — every PLAY writes a different roster |

## How big the cast pool is

Every figure the disc's toy catalogue knows: **224 entries over 122 distinct toy
numbers** (the gap is the variant line — Series 2/3/4, LightCore, Eon's Elite,
Dark, Legendary, seasonal), 221 of them with a portrait on the disc. 111 ship
their own stats object; the other 113 inherit their base figure's numbers at
runtime, so the launcher rolls over all 224 — one figure per **character**, so
the same toy never lines up twice (a Series 2 and a LightCore of one figure look
alike on the grid). Vehicles, magic items, adventure
and level packs, SWAP Force halves and the racing trophies are not figures and
are excluded (see `../FINDINGS.md` for the toy-number ranges).

The 71 spots are 56 driver records, 12 villain records and the 3 `Greeble*Info`
test dummies. Vehicles are **not** re-pointed when a figure moves in: the driver
records keep the hull the disc pairs them with, and the twelve villain records
sit on that terrain's `RentAWreck_*` (the rental the Greeble dummies already
drive) - a swapped figure under a villain's own hull is what comes up as a
corrupt racer, see `../FINDINGS.md`. The visible cost: on the sea grid the four
sea villains share one boat, so a few opponents look alike. That is the safe
configuration, not a broken pool.

## Your Skylander and vehicle (the portal)

Who *you* race as is not in the pkz files: the game reads the figure off the
Portal of Power, and Dolphin emulates that portal. So this is a separate,
**live** choice that needs no disc rebuild:

* **YOUR SKYLANDER** opens a browser of every toy in the tag library
  (`../../skylanders-nfc-sim/data`: 448 figures/minis, 35 vehicles, real
  1024-byte tag dumps — the size Dolphin's emulated portal reads).
* Clicking a figure installs its tag image into `portal/`, clicking a vehicle
  adds that too; the launcher points Dolphin's `SkylandersCollectionPath` at
  that folder and turns `EmulateSkylanderPortal` on (the ini is backed up once
  as `Dolphin.ini.launcher-backup`).
* In Dolphin: **Emulation → Show Skylanders Portal**, then put the toy from the
  collection on the portal — while the game is running, at any menu.

The choice is remembered in `cache/toys.json` and re-installed on every PLAY.

## Play with a friend (netplay)

The Wii build has no online mode to connect to (see `../FINDINGS.md`), so
distance play uses the game's own **split-screen 2P** through Dolphin netplay:
both machines run the same race, one player per controller.

That only works if both sides run the *identical disc*, and this disc's roster is
random per boot — so both players derive the roster from a six-character
**session code**. Same code, same figures, byte-identical image
(`md5` shown in the window; both sides must match).

1. **Host** presses HOST: the launcher builds the disc, starts announcing the
   session on the LAN and shows code, address, port and md5.
2. The friend's launcher lists that session under **ACTIVE SESSIONS ON YOUR
   NETWORK** as soon as it is announced — no server, no sign-up, it is a UDP
   broadcast on port 9797. Click it (or type the code) and press JOIN.
3. In Dolphin: **Tools → Start Netplay → Host / Connect**, pick
   `skylanders-scr-mod.wbfs`, port 2626. Across the internet, forward port 2626
   on the host.
4. In game, player 2 presses a button on the second controller for split-screen.

Pins are a solo-play feature and are ignored for netplay casts, otherwise the
two discs would differ.

## Platforms

The core (`roster.py`, `pipeline.py`, `assets.py`, `sessions.py`) is plain
Python and identical on every OS; `platforms.py` holds what differs — Dolphin
location, `wit` location, video backend, fonts, cursor, wheel events.

- **macOS** — Dolphin is forced to OpenGL (`-v ogl`) because Metal fails to build
  this disc's vertex pipelines.
- **Linux** — Dolphin is started without a forced backend; `wit` from your
  distro or the wiimms-iso-tools release goes on `PATH` or in `WIT=`.
- **Windows** — `Dolphin.exe` is looked for in `Program Files`, and `wit.exe` in
  `tools\wit\` or on `PATH`.
- **Android** — not supported: there is no tkinter on Android, so this UI cannot
  run there. The modules below it are UI-free, which is what a future Android
  front end would reuse; that front end does not exist yet.

## Files

- `SkylandersLauncher.py` — the window (`--check` for diagnostics)
- `pipeline.py` — session (roll/patch/netplay codes) and build/launch/export
- `roster.py` — parses the 71 racer slots out of `BaseGameplay.pkz` and rewrites them
- `assets.py` — joins the figure catalogue to the extracted art (cached in `cache/`)
- `toys.py` — the tag library, the portal folder and Dolphin's portal settings
- `sessions.py` — LAN announce/discover for the session browser
- `platforms.py` — per-OS paths, fonts, backends
- `assets/` — extracted art; regenerate with `python3 ../tools/extract_art.py`
