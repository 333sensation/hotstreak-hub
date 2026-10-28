# The mod guide

What Hotstreak Hub changes, what the window does, and how to put it back the way
it was. Five minutes to read; the first section is the whole point.

## What it changes

Four things, all of them inside the disc:

| | |
|---|---|
| **The field** | the opponents you race are rolled from the disc's own toy catalogue — **224 figures** — instead of the twelve the disc shipped |
| **Their stats** | every figure in the game has racing stats of its own. 148 of the disc's 203 stat records were empty; all of them are filled now, and each figure spends the same 3.0 points in a very different way, so no two drive alike |
| **The bots** | every bot runs at one speed per difficulty instead of the 0.80–1.20 spread the disc shipped — the whole field runs *together*, and the field is 31–47 % quicker |
| **The cups** | each cup is re-pointed at a fresh line-up of the disc's own circuits (7 circuits + 7 mirrored versions per terrain to draw from) |

Nothing is added to the game, no tracks are invented, no code is rewritten. It
is the game you already have, with different opponents on a track and the
figures you own fighting back.

## What it does not change

- **No new tracks, characters or vehicles.** Every figure, hull and circuit is
  already on the disc; the mod just decides who gets in.
- **The multiplayer is still the shipped 2-player split-screen**, and there is
  still no online mode to connect to (the Wii's own service closed before this
  game shipped). "Play with a friend" below is Dolphin netplay over that
  split-screen.
- **Difficulty still does what it did.** It is *how fast* the bots drive that
  changed. Easy still fields the passive personalities, Hard the aggressive ones.
- **Your figure is not in the disc.** Who *you* race as is read off the Portal of
  Power, which Dolphin emulates — that is a live choice, not something the mod
  bakes in.

## Before you start

1. Your game file passes the check: `python3 setup.py --verify-rip`.
2. Dolphin is installed (<https://dolphin-emu.org/download/>).
3. `hotstreak-hub.wbfs` exists in this folder — **Start Hotstreak Hub** builds it
   on its first run.

## The window

| button | what happens |
|---|---|
| **▶ PLAY** | rolls a cast, writes it into the disc, rebuilds the image (~10 s) and boots Dolphin |
| **ROLL NEW CAST** | rolls without booting, so you can look at the field first — the portraits on the left are who you will race |
| **PIN FIGURES** | click a portrait to make that figure appear in every cast. A useful way to keep a rival around |
| **PLAY WITH A FRIEND** | netplay: a six-letter session code that gives two machines the *same* roster — see below |
| **YOUR SKYLANDER** | pick the figure you race as, and its vehicle, and put it on Dolphin's emulated portal — no rebuild needed |
| **EXPORT TO SD CARD** | writes the patched image into the layout a USB loader expects, for a real Wii |
| *new cast every launch* | on by default. Off = the same field every time, until you press ROLL NEW CAST |
| *new cup tracks every launch* | on by default. Off = the shipped cup order, restored in the disc |

## What you will see in the race

- The grid holds figures from the whole catalogue, on the hulls the disc already
  assigns. Each slot points at the figure's own character record, so it is drawn,
  named and voiced as that figure — the results screen reads `Chompy Mage`,
  `Fling Kong`, `Bone Bash Roller Brawl` instead of the shipped line-up.
- Villains keep the vehicle they shipped with. When a figure and a hull do not
  belong together the engine quietly drops it onto the free/scrap vehicle, which
  is why the mod never re-points a vehicle — a villain on a borrowed hull is how
  you used to get a riderless scrap car in the field.
- Easy / Medium / Hard still pick the personalities; what changed is the pace.
  The field no longer has one slow straggler and one runaway: it arrives
  together, about a third faster than before.
- Cups are the same cups, on different circuits. A cup still has five races, and
  each one is drawn from that cup's own terrain.

## Your Skylander (the portal)

Who you race as comes from a toy tag, exactly like on the real console.

1. **YOUR SKYLANDER** → pick a figure (and optionally a vehicle).
2. In Dolphin: **Emulation → Show Skylanders Portal**, then move the toy from the
   collection onto the portal. You can do this while the game is running, at any
   menu.
3. The choice is remembered and re-installed on every PLAY.

This needs the tag library (`../skylanders-nfc-sim/data` — 448 figures and minis,
35 vehicles, real 1024-byte dumps). Without it everything else still works; only
this picker is empty. The launcher turns on `EmulateSkylanderPortal` in Dolphin's
ini and backs that file up once as `Dolphin.ini.launcher-backup`.

## Play with a friend

Both machines run the same race over Dolphin netplay, one player per controller,
using the game's own split-screen.

1. **HOST** on one machine: it builds the disc, shows a six-letter code, an
   address, a port and an `md5`.
2. The friend's launcher lists it under **ACTIVE SESSIONS ON YOUR NETWORK** (a UDP
   broadcast on port 9797 — no server, no account) or types the code and presses
   **JOIN**.
3. Both machines build from the same code, so the rosters are identical and the
   `md5` matches. If the two `md5`s differ, something is stale: rebuild.
4. In Dolphin: **Tools → Start Netplay → Host / Connect**, pick
   `hotstreak-hub.wbfs`, port **2626**. Across the internet, forward 2626 on the
   host.
5. In game, player 2 presses a button on the second controller.

Pins are ignored for netplay casts — a pin would make the two discs differ.

## Taking it to a real Wii

**EXPORT TO SD CARD**, pick the root of the SD card or USB drive, and it writes:

```
(card)/wbfs/Skylanders SuperChargers Racing [SKNE52]/SKNE52.wbfs
```

That is the layout USB Loader GX, WiiFlow and CFG expect, so the card can go
straight into a softmodded Wii. The roster and the cups are baked in at that
moment — a Wii does not roll a new cast per boot, only the launcher does.

The image is a normal trimmed `.wbfs` of about 1.6 GB.

## Why it keeps booting

Every edit is **the same size** as what it replaces. The disc's container format
keeps a hash index of its objects, so adding so much as one byte shifts every
offset after it and the game hangs on load. The tools therefore only rewrite
values in place, the launcher refuses to write a file whose length changed, and
`wit verify` checks the rebuilt image reads back as a well-formed `SKNE52` disc.
`FINDINGS.md` has the details, including the attempts that broke the disc.

## Undo

The shipped file of each container is kept in `backups/`. To go back to the
original game:

```sh
WIT=tools/wit/bin/wit            # the copy setup.py fetched for you
cp backups/BaseGameplay.pkz.pristine disc/files/Data/BaseGameplay.pkz
cp backups/Common.pkz.pristine       disc/files/Data/Common.pkz
$WIT copy disc hotstreak-hub.wbfs --overwrite
```

The two checkboxes are not an undo: *new cast every launch* off keeps the field
you already have (it does not put the shipped opponents back), and *new cup
tracks* off restores the disc's own cup order on the next PLAY. Deleting the
folder deletes the mod; the disc is untouched, because the mod only ever existed
as a rebuilt image and files inside this folder.

## When something is wrong

| what you see | what to do |
|---|---|
| PLAY does nothing | `python3 setup.py --check` names the missing piece in one line |
| the game hangs on the loading screen | a container changed size. Copy both `.pristine` files back (see *Undo*) and press PLAY again |
| black screen, or a broken-looking picture, in Dolphin | on macOS the Metal backend cannot draw this disc — `play-mod.sh` and the launcher force OpenGL (`-v ogl`) for exactly this reason |
| the roster looks the same every boot | *new cast every launch* is off, or figures are pinned |
| the portal picker is empty | the tag library (`../skylanders-nfc-sim/data`) is not next to this folder |
| netplay says the `md5`s differ | both machines use the same session code, and neither has a stale image — rebuild on both |
| "wit (Wiimms ISO Tool) is required" | `python3 setup.py --fetch-wit`, or set `WIT=/path/to/wit` |

## Under the hood

`reroll.sh` and `cups.sh` do the same rolls from a shell without the window.
`tools/` holds the patchers, one file each, with the format they read or write
explained at the top of the file; the README lists all of them. The engine side —
how a racer record points at a figure, an AI template and a hull, and what the
game validates — is in [`FINDINGS.md`](FINDINGS.md). For the ranking all 182
figures' stats produce, see [`TIERLIST.md`](TIERLIST.md).
