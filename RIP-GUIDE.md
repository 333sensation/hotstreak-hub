# How to get your own game file

The one thing this project does not give you and cannot give you is the game
itself. You need a file of *Skylanders: SuperChargers Racing* for the Wii — the
same file Dolphin or a USB loader would play. This page is how you make it out
of a disc you own.

It takes about twenty minutes, one SD card or USB stick, and a Wii that can run
homebrew (a Wii U in **vWii** mode works exactly the same way). **Dolphin plays
the file; it cannot make one from a Wii disc**, so the console is needed once.

> Ripping a disc you own for your own use is legal in some countries and not in
> others. Check yours. Keep the file to yourself — a copy of the game given to
> someone else is piracy, and that is not what this project is.

## Which disc

The American release: game id **`SKNE52`**. The fourth letter is the region —
the European disc has `P` there instead of `E` (`SKNP52`), the Japanese one `J`.
This mod was built from the American disc: the same three containers exist in
every region, but they do not hold the same bytes, so a patched European disc
will not boot. `python3 setup.py --verify-rip` tells you which disc you have
before you do any work.

## Route A — CleanRip (the reliable one)

[CleanRip](https://github.com/emukidid/cleanrip) reads the disc on the Wii and
writes a byte-accurate copy of it. Its checksum is compared against the
redump.org database while it runs, so you find out immediately if the disc was
read cleanly.

1. Format an SD card or USB stick. **FAT32 or exFAT** — either is fine, but FAT32
   splits big files (the next section handles that). 4.7 GB free is enough.
2. Download CleanRip, unzip it, and put the folder in `apps/` on that card:
   `(card)/apps/CleanRip/boot.dol` (+ `icon.png`, `meta.xml`).
3. Put the card in the Wii, start the **Homebrew Channel**, launch **CleanRip**.
4. Answer **Yes** to *calculate checksums* and **Yes** to *download the redump.org
   DAT files* (that needs the Wii online; if it errors, restart the Wii and try
   again, or skip it and check the checksum in Dolphin later).
5. Pick the device you are dumping to, then its filesystem (**FAT32** in most
   cases).
6. Insert the game disc and press A. CleanRip detects by itself whether the disc
   is dual-layer — this game is single-layer, so leave that alone. If you are
   asked whether it is an unlicensed Datel disc, say **No**.
7. Let it run. It takes ten minutes or so, and the progress is on screen. At the
   end you get the MD5 of the dump next to the redump one — **they have to
   match**. If they do not, the disc or the drive had a read error (wipe the
   disc and try again).

You now have a folder on the card named after the game, holding `…part0.iso`
(and usually `…part1.iso`, because a 4.7 GB file does not fit in FAT32's 4 GB)
plus a `-dumpinfo.txt` with the checksums in it.

### Joining the parts

A `.part0.iso` on its own is not a disc image. Put the parts together first,
then delete the parts.

**Windows** — open the folder in Explorer, click the address bar, type `cmd` and
press Enter, then:

```bat
copy /b *.part?.iso game.iso
```

**macOS / Linux** — in a terminal, in that folder:

```sh
cat `ls *.part?.iso | sort` > game.iso
```

Check what came out. Its MD5 must equal the one in `-dumpinfo.txt`:

| | |
|---|---|
| macOS | `md5 game.iso` |
| Linux | `md5sum game.iso` |
| Windows | `certutil -hashfile game.iso MD5` |

The joined file is about 4.7 GB. That is the file the setup wants — or shrink it
first with `wit copy game.iso game.wbfs` (about 1.6 GB) if you are short on
space. Both work. (`wit` is `tools/wit/bin/wit` after the first setup run, or
`python3 setup.py --fetch-wit` fetches it now.)

## Route B — USB Loader GX (if your Wii already plays backups)

If homebrew and a USB loader are already set up:

1. Plug the drive you keep your games on into the Wii and start **USB Loader
   GX** (or WiiFlow / CFG).
2. Put the disc in and pick **Install** for it (the `+` / disc-install option).
3. It writes `wbfs/Skylanders SuperChargers Racing [SKNE52]/SKNE52.wbfs` on the
   drive. Copy that file to your computer.

Fewer steps, no joining, no checksums — the trade is that you do not get a
checksum telling you the rip is clean. `--verify-rip` will at least confirm it
reads back from start to end.

## Route C — you already have a file

An old backup on a hard disk, the game already in Dolphin's library (a `.iso`,
`.wbfs`, `.wia` or `.rvz`). This setup takes `.iso`, `.wbfs` and `.wia`, so an
`.rvz` has to be converted back first: **Dolphin → right-click the game → Convert
File → ISO** (or WBFS). Then check it.

## Checking it

```sh
python3 setup.py --verify-rip                       # finds the file itself
python3 setup.py --verify-rip "/path/to/game.iso"    # or name it
```

It reads without changing anything, and answers in one of these ways:

| you see | what it means |
|---|---|
| `GOOD - your game file is exactly what this mod needs` | nothing to do: double-click **Start Hotstreak Hub** |
| `That file is not a Wii game` | wrong file, or a download that never finished — a good one is `.iso`/`.wbfs`/`.wia` and 1.6 GB or more |
| `That is a different game` | another game's disc; this mod only works with SuperChargers Racing |
| `Right game, wrong region` | you have the European or Japanese disc — see *Which disc* above |
| `The file is incomplete or damaged: it stops partway through` | the copy was interrupted: dump or download it again |
| `files are missing from inside it` | the rip left parts out; copy the whole disc again |

The guided setup runs this same check on whichever file it finds, **before** it
unpacks anything — so a broken file is one friendly line instead of a minute of
work followed by a strange error.

## Where to leave the file

Anywhere. The setup looks in this folder, the folder above it, your `Downloads`,
`Desktop`, `Documents`, your home folder, and every mounted disk and SD card, and
it takes the file whose name says the most about this game. `Downloads` is fine —
you do not have to move or rename anything.

## If you have no Wii

Then there is no legal way to make the file, and this project will not help you
find one. What you can do is borrow a Wii, or buy the disc and use a friend's
softmodded console for one evening; after that the file is yours and the disc can
go back on the shelf. Everything after the rip happens on your computer and needs
no console at all.
