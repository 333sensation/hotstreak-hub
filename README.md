# Hotstreak Hub

A roster mod for **Skylanders: SuperChargers Racing** on the Wii. Every race is a
different field of opponents, picked from all **224 figures** the game knows —
with real stats, a faster field, and your own Skylander on the grid.

![Skylanders: SuperChargers Racing](docs/banner.png)

The ready-to-play build is in the
[**Releases**](https://github.com/333sensation/hotstreak-hub/releases/latest)
tab: `hotstreak-hub.wbfs`, about 1.6 GB. You do not need the disc for it.

## Fast path — from download to racing

You need **Python 3.9+** ([python.org](https://www.python.org/downloads/), keep
the *tcl/tk* box ticked), **Dolphin**
([dolphin-emu.org](https://dolphin-emu.org/download/)) to play, and about **5 GB**
of free disk.

**1. Download the build.** From Releases:
`hotstreak-hub.wbfs` (~1.6 GB).

**2. Download this repo.** Green **Code** button → **Download ZIP**, then unzip
it anywhere (or `git clone https://github.com/333sensation/hotstreak-hub.git`).

**3. Put the file in the folder.** Drop `hotstreak-hub.wbfs` next to
`Start Hotstreak Hub` — the folder you just unzipped. That is the only setup
step.

**4. Start it.**

| | |
|---|---|
| macOS | double-click `Start Hotstreak Hub.command` |
| Windows | double-click `Start Hotstreak Hub.bat` |
| Linux | `python3 start.py` in a terminal (or `./run.sh` once it is set up) |

The first run takes a few minutes and says what it is doing:

1. checks Python and its window kit, installs Pillow if it is missing
2. downloads `wit` (2 MB) — the only thing that can open and repack a Wii image
3. opens the build, checks it, and unpacks it into `disc/`
4. writes the baselines and pulls the game's own portraits out for the window
5. builds the ready-to-play file from that copy (or keeps the one you
   downloaded) and verifies it — `+OK … SKNE52`

When it ends with **ALL DONE**, the launcher window is open. Press **PLAY**.

That is it. **PLAY** rolls a new field, writes it into the disc, repacks the image
(~10 s) and boots Dolphin on it. Next time you only double-click the starter
again — steps 1–5 are done.

> Why unpack at all when you already have the image? Because the launcher writes
> a *different* roster into the disc before every race, and the only way to get
> that into a Wii `.wbfs` is to repack it. `disc/` is the working copy it edits.
> If you delete the folder, nothing outside it changes.

## The buttons

| button | what it does |
|---|---|
| **▶ PLAY** | new cast, repack, boot |
| **ROLL NEW CAST** | roll the field without booting, so you can look at it first |
| **PIN FIGURES** | click a portrait to keep that figure in every cast |
| **PLAY WITH A FRIEND** | netplay — a six-letter code gives two machines the same roster |
| **YOUR SKYLANDER** | who *you* race as, installed on Dolphin's emulated Portal of Power |
| **EXPORT TO SD CARD** | writes the image in USB-loader layout, for a real Wii |

`YOUR SKYLANDER` needs the tag library in `../skylanders-nfc-sim/data`; without
it everything else works and only that picker is empty.

## Just want to boot it once?

The release build already carries the mod. Open the `.wbfs` in Dolphin
(**Open** → pick the file), or `./play-mod.sh` here — no setup needed. You get the
cast that was baked into the build; the random field per race is what the
launcher adds.

On macOS, if Dolphin shows a black or broken picture, it is using Metal — that
backend cannot draw this disc. Run it with `-v ogl` (`./play-mod.sh` does).

## If something goes wrong

| what you see | what to do |
|---|---|
| `tkinter is missing` | Debian/Ubuntu `sudo apt install python3-tk`, Fedora `sudo dnf install python3-tkinter`, Windows: reinstall Python with **tcl/tk** ticked |
| `I could not find it by myself` | the build is not in the folder, or the download is unfinished; drag the file into the terminal window when it asks |
| `That file is not a Wii game` | the download stopped early — 1.6 GB, and the check says so in one line |
| the window opens but PLAY does nothing | `python3 setup.py --check` names the missing piece |
| `wit (Wiimms ISO Tool) is required` | `python3 setup.py --fetch-wit` |
| macOS refuses to open the starter | right-click → **Open**, or `xattr -dr com.apple.quarantine .` then `chmod +x "Start Hotstreak Hub.command"` |

## More

| | |
|---|---|
| [`MOD-GUIDE.md`](MOD-GUIDE.md) | what the mod actually changes, the portal, netplay, real Wii, how to undo |
| [`TIERLIST.md`](TIERLIST.md) | all 182 figures ranked by the stats the mod gives them |
| [`START-HERE.md`](START-HERE.md) | the same, starting from **your own disc** instead of the release |
| [`RIP-GUIDE.md`](RIP-GUIDE.md) | how to make that game file out of a disc you own |
| [`TECHNICAL.md`](TECHNICAL.md) | the long read: every tool, every container, every finding |
| [`FINDINGS.md`](FINDINGS.md) | what the engine does, with the evidence |

The code is MIT ([`LICENSE`](LICENSE)); the game, and the disc image inside the
release build, is Nintendo's and Activision's. What this project adds is the
tools and a same-size patch.
