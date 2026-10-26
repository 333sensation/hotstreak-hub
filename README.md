# Skylanders: SuperChargers Racing (Wii) — roster mod + launcher

Tooling and a desktop launcher for modding **Skylanders: SuperChargers Racing**
(Wii, game id `SKNE52`) *inside the disc's own `.pkz` containers*, plus the notes
from working out how the engine stores racers.

The game ships **71 racer slots** — 56 driver records and 12 villain records, one
per terrain (air / land / sea), plus 3 `Greeble*Info` test dummies — and every
slot is two object refs: the **character** and the **vehicle** it drives. This
repo rewrites the character ref of each slot in place, so the container keeps its
exact size and the disc keeps loading.

## What it does

| | |
|---|---|
| **Random cast** | every boot fields a different set of opponents: `launcher/` rolls a cast over the disc's 224 catalogue figures and patches the 71 slots, then repacks the image (~10 s) |
| **Balanced stats** | `tools/pkz_stats_patch.py` rewrites the 194 character stat records to five balanced profiles (flattens the roster — that is the point) |
| **Random cups** | `tools/pkz_cup_random.py` re-points the three cup playlists at a fresh order of the disc's own circuits |
| **Launcher** | a tkinter window: PLAY (roll + patch + repack + boot), pin figures, netplay session codes for two-machine split-screen, export to an SD card layout for a real Wii |
| **Your Skylander** | the figure *you* race as comes from the Portal of Power, not the pkz — the launcher installs the chosen 1024-byte tag image into the emulated portal and enables it in Dolphin |

Documented in [`FINDINGS.md`](FINDINGS.md) (the engine findings, including the
attempts that broke the disc and why) and [`launcher/README.md`](launcher/README.md)
(launcher usage, platforms, netplay).

## What is in the repo — and what is not

Committed: the Python tools, the launcher, the shell front ends, and the findings.
**Not** committed (see `.gitignore`): the extracted disc (`disc/`), the pkz
baselines (`backups/`), the rebuilt `*.wbfs`, extracted text (`text/`), and the
artwork the launcher draws with — all of that is game data, extracted from a disc
you own.

## Setup

Requirements: Python 3.9+ with tkinter, `pip install pillow`, Dolphin, and
[Wiimms ISO Tool](https://wit.wiimm.de/) (`wit`) to unpack/repack the image.

```sh
# 1. unpack your own disc into ./disc (the tree wit EXTRACT produces)
wit extract "/path/to/Skylanders SuperChargers Racing.iso" disc

# 2. the launcher patches a known-good baseline instead of the pristine file
mkdir -p backups
cp disc/files/Data/BaseGameplay.pkz  backups/BaseGameplay.pkz.pristine
cp disc/files/Data/BaseGameplay.pkz  backups/BaseGameplay.pkz.working-randomcast
cp disc/files/Data/BaseSkylander.pkz backups/BaseSkylander.pkz.pristine
cp disc/files/Data/Common.pkz        backups/Common.pkz.pristine

# 3. optional: the launcher's portraits/minimaps are the game's own art
python3 tools/extract_art.py

# 4. build the image once, so PLAY has something to boot
wit copy disc skylanders-scr-mod.wbfs

# 5. run it
./launcher/run.sh          # --check prints where it found Python, Pillow, Dolphin, wit
```

`DOLPHIN=` and `WIT=` override auto-detection. `reroll.sh` and `cups.sh` do the
same rolls and repack from a shell, without the window. The launcher expects the
Skylander tag dumps (1024-byte `.sky` images) in `../skylanders-nfc-sim/data`;
without them the roster side still works, only the portal picker is empty.

## Layout

```
launcher/     the window: session roll, patch, repack, launch, netplay, export
  roster.py       the 71 racer slots out of BaseGameplay.pkz
  pipeline.py     session codes + build/launch/export
  toys.py         tag library, portal folder, Dolphin's portal settings
  assets.py       joins the figure catalogue to the extracted art
  sessions.py     UDP announce/discover for the session browser
  platforms.py    per-OS Dolphin/wit paths, fonts, video backend
tools/        the pkz readers/writers (objects, refs, pools, stats, cups, bots)
FINDINGS.md   what the engine does, with the evidence
reroll.sh     roll a cast and repack
cups.sh       roll the cup line-ups and repack
play-mod.sh   start Dolphin on the built image (OpenGL backend forced on macOS)
```

## Notes

- Every edit is **same-size**: the disc's key registry is a hash index, so adding
  objects shifts offsets and the game hangs. `FINDINGS.md` has the details.
- A racer has two refs. Swapping the character is safe; re-pointing a villain at
  its own hull is not, and is what produced corrupt racers. Villain records stay
  on the terrain's `RentAWreck_*` rental, which the Greeble dummies already use.
- No game files are distributed here. You need your own disc.
