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

You need: Python 3.9+ with tkinter, `pip install -r requirements.txt` (Pillow),
Dolphin to play, and [Wiimms ISO Tool](https://wit.wiimm.de/) (`wit`) to
unpack/repack the image. Nothing else is downloaded for you, and **you need your
own copy of the disc**.

```sh
python3 setup.py --check                 # what is still missing on this machine
python3 setup.py /path/to/your/game.iso  # unpack, make the baselines, build the image
./run.sh                                 # Windows: run.cmd
```

`setup.py` is the whole install: it finds `wit` and Dolphin, unpacks the image
into `disc/`, copies the four pristine `.pkz` baselines the patcher works from
into `backups/`, pulls the game's own portraits/minimaps out of the disc for the
window, and repacks `skylanders-scr-mod.wbfs`. Re-running it is safe — it only
does the steps that are missing, and `--force` rebuilds the image and the
artwork.

It takes a `.iso`, `.wbfs` or `.wia`. `DOLPHIN=/path/to/Dolphin` and
`WIT=/path/to/wit` override auto-detection; `wit` is looked for on `PATH`, in
`tools/wit/`, and in a `DolRecomp` checkout next to this folder.

Without `wit` you can still use everything except building the image, and
without Dolphin you can still patch and export for a real Wii — `setup.py`
says which of the two is missing.

`reroll.sh` and `cups.sh` do the same rolls and repack from a shell, without the
window. The launcher expects the Skylander tag dumps (1024-byte `.sky` images)
in `../skylanders-nfc-sim/data`; without them the roster side still works, only
the portal picker is empty.

## If it does not start

| what you see | what to do |
|---|---|
| `tkinter is missing` | Debian/Ubuntu `sudo apt install python3-tk`, Fedora `sudo dnf install python3-tkinter`, Windows: reinstall Python from python.org with **tcl/tk** ticked |
| `Pillow is missing` | `python3 -m pip install -r requirements.txt` |
| `wit NOT FOUND` | install Wiimms ISO Tool, put `wit` on `PATH`, or `WIT=/path/to/wit` |
| `no such disc image` | `setup.py` wants the image file itself, not a folder; `.iso`, `.wbfs` and `.wia` all work |
| the window opens but PLAY does nothing | run `python3 setup.py --check` — it names the missing piece |
| no picture in Dolphin on macOS | Dolphin's Metal backend cannot build this disc's vertex pipelines; `play-mod.sh` and the launcher force the OpenGL backend instead |
| the portal picker is empty | the toy library (`../skylanders-nfc-sim/data`) is not next to this folder — optional, only that picker needs it |

## Layout

```
setup.py      one-command install: unpack, baselines, artwork, image
run.sh        start the launcher (run.cmd on Windows)
launcher/     the window: session roll, patch, repack, launch, netplay, export
  roster.py       the 71 racer slots out of BaseGameplay.pkz
  pipeline.py     session codes + build/launch/export
  toys.py         tag library, portal folder, Dolphin's portal settings
  assets.py       joins the figure catalogue to the extracted art
  sessions.py     UDP announce/discover for the session browser
  platforms.py    per-OS Dolphin/wit paths, fonts, video backend
tools/        the pkz readers/writers (see below)
FINDINGS.md   what the engine does, with the evidence
reroll.sh     roll a cast and repack
cups.sh       roll the cup line-ups and repack
play-mod.sh   start Dolphin on the built image (OpenGL backend forced on macOS)
```

## License

MIT (see [`LICENSE`](LICENSE)) — for the code in this repo. No game files are
included or distributed here, and none are downloaded.

## The tools

Run any of them with `--help`; the docstring at the top of each one explains the
format it reads or writes.

| | |
|---|---|
| `pkz_objects.py` | parse a `.pkz`, list its objects and resolve the 32-bit ids they reference — start here |
| `pkz_refs.py` | the per-object reference tables (the character/vehicle refs live here) |
| `pkz_random_bots.py` | recast the 71 racer slots as a random cast (what the launcher runs) |
| `pkz_stats_patch.py` | rewrite the racing stats to balanced profiles |
| `pkz_cup_random.py` | re-point the three cup playlists at the disc's own circuits |
| `pkz_pool_swap.py` | move villains into the driver pools without resizing anything |
| `extract_art.py` | pull portraits, minimaps and menu backgrounds out as PNG |
| `pkz_textures.py` | list/export every texture in a container |

The rest (`pkz_ai_add`, `pkz_ai_append`, `pkz_pool_grow`, `pkz_pool_all`,
`pkz_pool_fill`, `pkz_add_test`, `pkz_pool_terrain`, `pkz_text_scan`,
`pkz_stats_scan`, `pkz_bind`) are the probes used to work out the container, and
the experiments that did not work out. They are kept because `FINDINGS.md` cites
them; several of them shift offsets and hang the game, so do not run them on a
tree you care about.

## Notes

- Every edit is **same-size**: the disc's key registry is a hash index, so adding
  objects shifts offsets and the game hangs. `FINDINGS.md` has the details.
- A racer has two refs. Swapping the character is safe; re-pointing a villain at
  its own hull is not, and is what produced corrupt racers. Villain records stay
  on the terrain's `RentAWreck_*` rental, which the Greeble dummies already use.
- No game files are distributed here. You need your own disc.
