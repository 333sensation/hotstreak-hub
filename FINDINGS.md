# Skylanders: SuperChargers Racing (Wii, SKNE52) — modding findings

Everything below was derived from the extracted disc (`scr-wii/disc`) and the
unstripped ELF (`disc/files/goliath.engine.wii.final.elf`, 44,938 symbols).

## Engine / container

* Engine: "Goliath" / `roceGS` serializer (`roceGS version 9.0.175008`, built 2015-07-12).
* Game data lives in `files/Data/*.pkz` (786 files, ~2.8 GB).
* A `.pkz` is a chunk stream of typed objects:
  * chunk headers are big-endian `0x8000xxxx` tags + lengths,
  * objects carry a name (zero-padded) and a 4-byte type id,
  * object/type ids are **CRC32 of the UPPERCASE name**, e.g.
    `crc32("RACERAILIST") = 0xCAFB9B03`.
* Scripts (Lua-like, e.g. `if ... then ... end`) are stored **uncompressed** as
  plain text inside the same containers, so they are greppable and patchable
  (`scr-wii/tools/pkz_text_scan.py` dumps 1,307 blobs / 5.2 MB).

## Character stats

Front-screen scripts call:

```lua
local CharacterTopSpeedP1     = Stats_GetCharacterStat (0, 0)
local CharacterAccelerationP1 = Stats_GetCharacterStat (0, 1)
local CharacterArmorP1        = Stats_GetCharacterStat (0, 2)
local CharacterHandlingP1     = Stats_GetCharacterStat (0, 3)
local CharacterFirePowerP1    = Stats_GetCharacterStat (0, 4)
```

So stat index order is **TopSpeed, Acceleration, Armor, Handling, FirePower**
(the same indices are used for `Stats_GetVehicleStat` / `Stats_GetVehicleModStat`).

The values live in `Data/BaseSkylander.pkz` as `<figure>_Stats` objects that end
in five big-endian IEEE-754 floats in 0.0–1.0 (the UI draws 0–5 pips):

| object | TopSpeed | Accel | Armor | Handling | FirePower |
|---|---|---|---|---|---|
| `0000_Whirlwind_EonsElite_Stats` | 0.80 | 0.60 | 1.00 | 0.60 | 0.50 |
| `0016_Spyro_EonsElite_Stats` | 0.60 | 0.80 | 0.70 | 0.60 | 0.80 |
| `Kaos_Stats` | 0.90 | 0.50 | 0.60 | 0.70 | 0.80 |
| `CaptainFrightbeard_Stats` | 0.70 | 0.40 | 0.60 | 0.50 | 0.80 |

`scr-wii/tools/pkz_stats_scan.py` extracts them.

**Coverage (corrected).** The "only 34 stat objects" figure above was a naming
artefact, and so was the later "~150 Skylanders have no `_Stats` object". Counting
by object **type** instead of by name, `BaseSkylander.pkz` holds **304** stat
records (`0x4BBD2CFD`, every one a 36-byte body):

| | |
|---|---|
| character records | **203** — SA `00xx`, Giants `01xx`, Trap Team `04xx`/`30xx`, minis `05xx`, SWAP Force legs `10xx` / body `20xx`, SuperChargers `34xx`, the `_Dark`/`_LG`/`EonsElite` variants, 14 villains |
| vehicle records | **101** — `*_Stats_Mod_0/1/2/SC` for the 20 player vehicles, plus `*Plane/Car/Boat_Stats` and `RentAWreck_*` for the villain hulls |
| all-zero records | **161** (148 character + the 13 villain hulls) |

So every character the disc can name *does* have a record; what it does not have
— for 148 of them — is **numbers**. Nothing else on the disc supplies them
(`BaseGameplay.pkz` and `Common.pkz` contain none), so they have to be invented,
which `tools/pkz_stats_patch.py` now does in place (no new objects, no offset
fixups).

Two reasons a name-based scan undercounts, both worth knowing before writing
tooling against this file:

* 92 of the 304 records do not end in `Stats` — the 85 vehicle mod stages and 7
  character variants (`3412_NitroStats_Dark`, `3413_DriverJetVacStats_LG`, ...);
* on 27 records the `0x138E` key chunk holds the 4-byte key **in front of** the
  name, so a printable-run regex reads the key as the name (`Qy\\"`, `x{`, ...).
  The real name sits behind the `ff ff ff ff` end marker in the same chunk.

`tools/pkz_stats_patch.py` walks the wrappers by type and reads the name from
behind that marker, which is how it sees all 304.

## Bot / AI racers

`Data/Main.pkz` holds the identifier table (hash → name) with the AI data
classes:

* `RacerAIInfo`, `RacerAIList`, `RacerAIItem`, `RacerAISelector`, `RacerAISpawner`
* `RacerSelector`, `SelectSkylanderAction`
* `AIPersonalityItem`, `AIPersonalityList`, `AITemplate`

`Data/BaseGameplay.pkz` contains the actual data: **18 `RacerAIList` objects and
115 `RacerAIItem` records**, named per track, e.g.

* `Land_DangerZone_AIList_Mine`
* `Land_DangerZone_AIList_Mine+Bomb`
* `Land_DangerZone_AIList_Mine+Bomb+TNT`
* `Land_DangerZone_Personality_Mine`, …

`Data/3428_LifeBug.pkz` (and its Easter variant) ship one list each.

### Who the bots actually are

`BaseGameplay.pkz` holds 75 `RacerAIInfo` objects, and their **names are the
roster**. They are per driver *and* per terrain:

* `DriverAirLock_Air_AIInfo`, `DriverAirLock_Land_AIInfo`, `DriverAirLock_Sea_AIInfo`
* … and the same trio for exactly these 20 drivers:

  `AirLock, AstronautBlast, Bowser, DonkeyKong, Eruptor, GillGrunt, InkGirl,
  JetVac, Koala, LifeBug, LightBulb, NightFall, Nitro, Peacock, PopFizz,
  RollerBrawl, SoulJam, StealthElf, Terrafin, TriggerHappy`

  20 drivers × 3 terrains = 60 objects — i.e. **only the SuperChargers cast**.
* plus 15 villain infos (`ChefPepperJackInfo`, `ChompyMageInfo`, `CluckInfo`,
  `CountMoneyBoneInfo`, `DrKrankcaseInfo`, `GlumshanksInfo`, `GoldenQueenInfo`,
  `GreebleBoatInfo`, `GreebleCarInfo`, `GreeblePlaneInfo`, `GulperInfo`,
  `MesmeraldaInfo`, `PainYataInfo`, `WolfgangInfo`, `BossChompyMageAIList`).

That is exactly the limitation being reported: a character can only show up as
an AI racer if a `Driver<Name>_<Terrain>_AIInfo` object exists for it, and only
the 20 SuperChargers have one. Level files complete the picture with
`RacerSelector` objects (`Base_DangerZone.pkz` ×9, `L_ChompyMountain_DangerZone`
×4, `S_AncientSwamp_DangerZone` ×4, `L_SnowPaTroll_DangerZone` ×2,
`S_SpookyWaters_DangerZone` ×2) that pick from those infos, and `BaseGameplay`
adds 32 `RacerAISelector` objects.

## What is still missing for the requested mod

Both requested changes need **new objects inside the containers**, not just
edited values:

1. *Every character as a bot* — ~135 missing `Driver<X>_<Terrain>_AIInfo`
   objects (×3 terrains) and their references in the AI lists/selectors.
2. *Stats for every character* — 44 `_Stats` objects exist in total and they
   belong to Eon's Elite variants, villains and villain vehicles. The ~150
   regular Skylanders have none.

Editing in place is safe where records already exist (the five floats of an
`_Stats` object, numeric fields of an AI record — same-size writes, no offset
fixups). Adding records requires a container writer: the chunk stream uses
sequential chunk headers (`0x8000xxxx` + length), 32-bit CRC32 ids and a
zero-padded name per object, with a compressed/opaque blob region at the end of
each file.

## Applied mod: stats for every figure (done)

`tools/pkz_stats_patch.py` now covers **all 304** records it finds by type, and
every character ends up with real values: the 148 empty character records are
filled and the 55 that already shipped numbers are regenerated onto the same
scheme. Scheme:

* one of **nine spiked archetypes** (rocket, sprinter, cornerer, drifter,
  bruiser, juggernaut, gunner, brawler, all-rounder) picked from a CRC32 of the
  figure's own name, then each stat jittered multiplicatively (0.70–1.30), so two
  figures on the same archetype still differ;
* each archetype sums to exactly **3.0** on its own and maxes one stat while
  starving another — a rocket is 1.00 speed at 0.10 armour, a bruiser 1.00 armour
  and 1.00 firepower at 0.25 speed — so a figure's spread reads as an identity
  rather than as five numbers hovering around the middle;
* snapped to the **0.05 grid** the disc itself uses and normalised back to a total
  of **3.0** per figure — the same budget every figure always had, so nothing is
  stronger on paper, only shaped differently. The rounding remainder is given to
  the biggest stat with room and taken from the smallest one that has any, which
  keeps a spiked shape spiked instead of sanding it towards the middle, and a stat
  is never left at 0.0 (floor 0.05), because a figure with no top speed would not
  drive;
* a spread that still repeats is walked off the numbers somebody else holds, one
  0.05 step at a time, so "no two figures share a spread" survives the spiking:
  the spiked shapes clamp a stat at 1.00 often enough that 27 records collided
  before that pass and **none do after it**;
* a `_Dark` / `_LG` / `EonsElite` variant keeps its base figure's spread with
  0.10 moved from its weakest stat to its strongest one that still has room
  (Whirlwind's armor is already 1.00) and a weakest stat already on the floor is
  skipped rather than pushed to zero, so a variant never comes out identical to
  its base: same budget, sharper feel — what the disc's own variant numbers do
  (base 2.5, variant 3.0);
* SWAP Force halves keep their own record (a Legs record and a Body record for
  the same toy differ), so a swapped figure is not a clone of its parts.

Vehicle records are **not** characters, so by default only the 13 empty villain
hulls are filled; the 88 tuned vehicle records (the 20 player vehicles incl. their
`Mod_1`/`Mod_2`/`Mod_SC` stages, and the `RentAWreck_*` hulls) keep the disc's
numbers — rewriting those changes how your own ride handles. `--vehicles`
regenerates all 101 anyway.

Verification performed on the patched file:

* 216 records written (203 characters + 13 villain hulls), 3,499 bytes changed of
  318,772 — every changed byte inside a 20-byte float field, file size identical;
* `all-zero records left: 0`; every character record sums to exactly 3.00 and
  every value is inside 0.05–1.00;
* **203 distinct spreads across the 203 character records**, none shared;
* the budget is unchanged and the spend is not: the mean stat is 0.60 before and
  after, but the mean spread of a figure grows from 0.58 to **0.76**, stats at
  0.05–0.15 go from 1 to **69**, stats pinned at 1.00 from 102 to 190, and the
  range under the tier list's lap weights widens from 1.67–2.53 to 1.61–2.63 — the
  same three points, spent far more unevenly;
* re-running the tool on its own output reproduces the file byte for byte;
* the chunk tree still tiles and the object-type histogram is unchanged
  (`pkz_pool_grow.tree_ok`), i.e. nothing moved but the floats;
* `wit copy disc skylanders-scr-mod.wbfs` → `wit verify` reports
  `+OK ... DATA SKNE52` (11 s), and extracting `files/Data/BaseSkylander.pkz`
  from the image gives md5 `b74d29363041ca175717ed30f37091ea`, the same as
  the patched file in `disc/`.

Two things nobody has verified: **reading the pips in game** (the check above is
container-level, not a screen capture), and how the engine treats a **SWAP Force**
figure, whose Legs and Body records each got 3.0 — if it sums the halves instead
of picking one, those swaps read double. Every other record belongs to exactly
one racer.

Revert with `cp disc/files/Data/BaseSkylander.pkz.orig disc/files/Data/BaseSkylander.pkz`.

## Where bot faces come from (settled)

`sc-wii/tools/pkz_objects.py` parses the chunk stream (data chunk header is
`80 00 13 91 00 08` + 6 zero bytes, then `size`, `id`, `type`, fields). Running it
over `BaseGameplay.pkz` gives 75 `RacerAIInfo`, 18 `RacerAIList`, 13
`AIPersonalityList` objects, and the per-terrain AIInfo payload is:

```
00 00 00 00            
<char id>              same for Land/Air/Sea of one driver (20 drivers -> 21 ids)
<AI template id>       shared, 8 distinct values across the 75
<vehicle id>           different per terrain (e.g. JetVac Land 54EE030D =
                       3221_UndeadBuggy, Air 7D3EC498 = 3236_LightPlane)
<variant>             0..3, per driver *and* per terrain (NOT the terrain
                       number - see "The pools, byte for byte" below)
```

Level selector records (`Base_DangerZone.pkz` ×9, `L_ChompyMountain_DangerZone`
×4, `S_AncientSwamp_DangerZone` ×4, `L_SnowPaTroll_DangerZone` ×2,
`S_SpookyWaters_DangerZone` ×2) are 24-byte entries of the shape

```
<owner id> 93E56119 <0> <shared ref> <per-entry ref>
```

and none of those refs is a `RacerAIInfo`; scanning every level file for the 75
AIInfo ids returns **zero** references. `AIPersonalityList` objects
(`StarterPackPersonalityList`, `BossGoldenQueenAIList`, …) likewise hold
`AIPersonalityItem` arrays, not character refs.

Conclusion: **the character a bot uses is stored in its `RacerAIInfo` record**
(`<char id>` + that character's vehicle per terrain). The per-level selectors
only pick which AI personality/difficulty group a race uses; they never name a
character. So opening the roster means adding `Driver<X>_<Terrain>_AIInfo`
objects — and because nothing references AIInfos by id, no reference fixups are
needed if the engine enumerates them by type.

## Why the appended AI records never showed up (corrected)

`tools/pkz_ai_append.py` produced 336 extra `RacerAIInfo` records, but the game
ignored all of them, and this is now fully explained by the container layout:

* A container (`.pkz`) is a chunk tree: `80 00 <type> <a> <b> <u64 len>` per
  chunk. Objects are `0x138D` chunks inside a per-class group chunk (the
  `RacerAIInfo` group is `type 0x0032` at 0x1309BC in `BaseGameplay.pkz`, holding
  417 objects).
* Every object chunk wraps `0x0C80` (a `0x0C80 len 4 = 1` marker + the `0x1391`
  data chunk), then a `0x138D` summary chunk, then `0x138E` (the object's **key**,
  `0x15`, `0x0F`, padding) and `ff ff ff ff` + a 64-byte zero-padded name.
* Each group ends with `0x139A` (object **count**, 0x1A1 = 417) and `0x139B`
  (the group's **key registry**: 415 unique 4-byte keys).
* All ancestor chunk lengths (group, root) have to be updated together.

The appended records were written after the blob region, as bare `0x1391` data
chunks without the `0x138D` container, without group count/registry entries and
with no pool referencing them — so the loader skipped them entirely. Bumping the
root length alone (which is what the script did) is not enough.

## How bots are actually chosen (settled for real)

AI infos are referenced **by their key**, not by their instance id, and only from
`RacerAIList` objects in `BaseGameplay.pkz`:

| object | entries | contents |
|---|---|---|
| `EnemyAIList_Land_ActionPack` | 20 | `Driver*_Air_AIInfo` |
| `EnemyAIList_Land_StarterPack_SheepHerder` | 20 | `Driver*_Land_AIInfo` |
| `EnemyAIList_Sea_ActionPack` | 20 | `Driver*_Land_AIInfo` |
| `ActionPackPersonalityList` | 20 | `Driver*_Sea_AIInfo` |
| `EnemyAIList_Land/Air/Sea_StarterPack`, `*_SheepHerder` | 4–7 | villains |
| `Boss*PersonalityList`, `*_DangerZone_*` | 1 | bosses / personalities |

A list payload is a 32-byte header followed by N × 16-byte entries
(`word, key, owner key, shared key 91284605`); the payload length, the `0x1391`
length, the object's `0x138D` length and all parent lengths are explicit, so a
list *can* be grown — but nothing in the pools references any key that is not
on the disc, and a racer also needs a `Driver<Name>` package (only 8 characters
ship one: Eruptor, GillGrunt, JetVac, PopFizz, RollerBrawl, StealthElf,
Terrafin, TriggerHappy, plus variants).

Consequence: the roster is the 20 SuperChargers + 15 villains, and every one of
them already has a valid AI info. The ~100 other figures have **no** AI info, no
vehicle pairing and no driver package, and the 4-byte character identity their
AI info would need (`AirLock = 571FA718`, `JetVac = 79E645F7`, …) is an opaque
figure id that only exists in the shipped tables for the characters that already
have AI data. It is not derivable from the figure names: crc32, FNV-1, FNV-1a and djb2 over
name/number permutations (`3425_AirLock`, `AirLock`, `0100_JetVac`, …) miss,
and so does crc32 (and crc32 of the uppercase form) over all 6,258 names in the
`Main.pkz` identifier table. They are build-time GUIDs.

So "every figure as a bot" is not reachable by data patching: it needs new AI
infos *and* new figure-id/vehicle/personality content that the disc does not
contain.

## The pools, byte for byte (final)

A `RacerAIList` object is a single `0x1391` chunk at a fixed size, so the body is
fully explicit (any byte-level tool can read it):

```
+00  own id
+04  type = CAFB9B03 (crc32 "RACERAILIST")
+08  00000000
+0C  u16 0014 (maxRacers = 20), u16 <count>
+10  00000000
+14  u16/u16 (pool-specific, e.g. 000C 0014)
+18  record[0]   <- always the pool's personality list, `word` = 0x10 for driver pools
+28  record[1] ... record[19]
        record = u32 word | u32 key | u32 owner | u32 shared (0x91284605)
        the very last record is stored truncated (word + key only)
```

Four pools hold drivers, **20 slots each as shipped** (one personality record + 19
driver records + the truncated last one):

| object | slots | what was in them |
|---|---|---|
| `EnemyAIList_Air_StarterPack` | 20 | `Driver*_Air_AIInfo` |
| `EnemyAIList_Land_StarterPack` | 20 | `Driver*_Land_AIInfo` |
| `EnemyAIList_Land_StarterPack_SheepHerder` | 20 | `Driver*_Land_AIInfo` |
| `EnemyAIList_Sea_StarterPack` | 20 | `Driver*_Sea_AIInfo` |

The four `*_ActionPack` lists are the **villain** pools (8 records each), not
driver pools; the earlier table above got that wrong because the object names
had been read from the wrong wrapper (see "Binding names to objects" below).

Two facts that settle what a pool edit can and cannot do:

* Terrain variants are the **same character**: `DriverJetVac_{Air,Land,Sea}_AIInfo`
  all carry char id `79E645F7`; only the vehicle id differs. So swapping a pool
  to another terrain changes the bots' vehicle, never their face
  (`tools/pkz_pool_terrain.py`, written but deliberately **not** applied).
* The villain infos (`GoldenQueenInfo`, `WolfgangInfo`, …) are **the same class**
  as the driver infos (`0x45BA524C` = `RacerAIInfo`), and the villain pools
  (`EnemyAIList_*_StarterPack`) already reference them. 14 of them exist
  (`CaptainFrightbeardInfo` is an `AIPersonalityList`, not a racer info).
* The 4th payload word is **not** the terrain (AirLock is 0/0/3 for Air/Land/Sea,
  Bowser 3/1/0); treat it as a variant/class byte and leave it alone.

## The per-object reference table (0x139C) matters

Every object **is** a `0x138D` wrapper: it *contains* `0x138E` (key + padded
name), a `0x0C80` marker, the `0x139C` table of `00000015 <key>` entries, and a
`0x0C81` chunk that nests the `0x1391` data. For all 18 `RacerAIList` objects
that table holds exactly the set of keys found in the object's data
(personality + every entry); the shipped order lists the personality record
last, i.e. the table is the record list rotated by one.

**Binding names to objects:** wrapping is not "data, then the next wrapper". A
tool that reads the name from the *next* `0x138D` gets every name shifted by
one object, which is what happened to `tools/pkz_pool_grow.py` and to the pool
table above. The reliable walk is: descend through payloads that start with a
`0x8000xxxx` chunk header, and for each `0x138D` take its own `0x138E` name plus
the `0x1391` nested in its own `0x0C81` (`tools/pkz_pool_swap.py` does exactly
that and finds 2461 named wrappers in `BaseGameplay.pkz`).

That is why every pool edit has to touch two places: the record in the data and
the matching entry in the table. An in-place key swap that only edits the data
leaves a ref that is not in the table (same failure mode as the deleted
`pkz_ai_append.py`).

## Applied mod: villains swapped into the driver pools (current)

`tools/pkz_pool_swap.py` writes **no new bytes**: in each of the four driver
pools it rewrites the 4-byte key of existing driver records to a villain
`RacerAIInfo` key, and updates the one `0x139C` entry that carries that key
(the table is the record list rotated by one, so entries are matched by value).
File size, chunk lengths and record counts are untouched.

Villains are **terrain-matched**: the three shipped villain pools are the
authoritative split, so the tool reads them instead of guessing —

| terrain | villain infos (from `EnemyAIList_<Terrain>_ActionPack`) | pool it goes into |
|---|---|---|
| air | ChefPepperJack, PainYata, Cluck, Wolfgang, GreeblePlane | `EnemyAIList_Air_StarterPack` |
| land | DrKrankcase, CountMoneyBone, ChompyMage, Glumshanks, GreebleCar | `EnemyAIList_Land_StarterPack`, `…_SheepHerder` |
| sea | GoldenQueen, CaptainFrightbeard, Mesmeralda, Gulper, GreebleBoat | `EnemyAIList_Sea_StarterPack` |

Result per pool: 1 personality record + 15 driver infos + 5 villains of that
terrain, so no sea villain ever lines up on a land track (or vice versa).

Verification: 158 bytes change out of the 160 written (20 slots x 2 locations x
4 bytes; two bytes happened to keep their value), all inside record/ref key
fields;
every `RacerAIList` still mirrors its ref table (set equality); `wit verify` →
`+OK … SKNE52`; the file extracted from the image compares equal to the tree.

Revert: `cp disc/files/Data/BaseGameplay.pkz.orig disc/files/Data/BaseGameplay.pkz`.

## Failed attempt: all four pools grown to hold every racer (reverted)

`tools/pkz_pool_grow.py` starts from the pristine file and grows **every** driver
pool to hold all 20 driver characters plus all 14 villain infos, adding the
missing characters with the terrain variant the pool already uses:

| pool | entries before | after | added |
|---|---|---|---|
| `EnemyAIList_Land_ActionPack` | 21 | **37** | 2 missing drivers + 14 villains |
| `EnemyAIList_Land_StarterPack_SheepHerder` | 21 | **35** | 14 villains |
| `EnemyAIList_Sea_ActionPack` | 21 | **35** | 14 villains |
| `ActionPackPersonalityList` | 21 | **38** | 3 missing drivers + 14 villains |

(each count includes the pool's personality record; the two pools that say
"missing drivers" shipped the same character twice instead of a 20th one)

Each growth is `+N records x 16 B` in the data and `+N refs x 8 B` in the table,
so the enclosing lengths move by different amounts:

| chunk | delta |
|---|---|
| data `0x1391` | +16N |
| ref table `0x139C` | +8N |
| `0x0C81` wrapper | +16N |
| `0x138D` wrapper | +24N |
| group `0x80000032` | +24N |
| root `0x80000001` | +24N |

The new records go in **before the trailing truncated record**, so the shape the
loader already accepts (N full records + an 8-byte last record) is preserved.
The header fields are left untouched: `maxRacers = 0x14` appears in *every* pool,
including the one-entry ones, so it is a config constant and not the entry count.
The entry count follows the payload length.

Verification performed (independent of the patch script):

* file grows by exactly **+1464 bytes** (10,164,932 -> 10,166,396), root length ==
  `filesize-16`, and the top-level chunks tile the file exactly;
* **1497** data chunks parse before and after, with identical names *and* types
  in the same order, and the only data chunks whose lengths changed are the four
  pools (352 -> 608 / 576 / 576 / 624);
* all four pools have as many ref-table entries as data keys, refs ⊇ data, and
  all 18 `RacerAIList` objects satisfy the same invariant;
* `wit COPY disc skylanders-scr-mod.wbfs` -> `wit verify` reports `+OK … SKNE52`,
  and both edited files extracted back out compare equal to the working tree;
* Dolphin boots the image with no error output (OpenGL backend).

**This does not work in game.** With the grown pools the disc verifies and boots,
but the game never leaves the loading screen (the loading animation keeps running
and the race never starts). Every check above still passes on that image, so
structural validity of the chunk tree is *not* sufficient evidence that the
loader accepts a grown pool: the pool write path here is unproven.

Reverting `BaseGameplay.pkz` to `.orig` makes the same image load again, and the
stats-only image (clean `BaseGameplay.pkz` + patched `BaseSkylander.pkz`) is
confirmed working. Revert the bot part with
`cp disc/files/Data/BaseGameplay.pkz.orig disc/files/Data/BaseGameplay.pkz`.

Confirmed cause of the mess: `tools/pkz_pool_grow.py` took each object's name
from the *next* `0x138D` wrapper, so every target was off by one object — it
reported `EnemyAIList_Land_ActionPack` as 352 bytes / 21 entries (that is really
`EnemyAIList_Air_StarterPack`) and grew whichever pool happened to sit before
each named one, twice in some cases. A correct retry must start from the wrapper
walk in `tools/pkz_pool_swap.py` (each `0x138D` owns its `0x138E` name and the
`0x1391` inside its own `0x0C81`) and grow one pool at a time with a boot test
after each.

## Racer identities for every figure (corrected - they do exist)

The 4-byte value an AI info carries (`AirLock = 571FA718`, `JetVac = 79E645F7`,
…) **is the key of that figure's catalogue object** in `BaseSkylander.pkz`
(type `0x5DA30426`). The proof is `VehicleDriverPairList` (the only object of
that type, 55 `(char, vehicle)` pairs): every entry's char id is exactly the
`0x138E` key of a catalogue object —

```
3406_Peacock            key 9A56169E  ->  DriverPeacock_*_AIInfo char 9A56169E
3413_DriverJetVac       key 559EFB79  ->  DriverJetVac_*_AIInfo  char 559EFB79
3425_AirLock            key 2CB6A40C  ->  DriverAirLock_*_AIInfo char 2CB6A40C
0000_Whirlwind          key A6C7C735  (no AI info, but the id is right there)
```

So the earlier claim that racer ids are underivable GUIDs was wrong: the ids
are object keys, and every figure has one (`437` catalogue objects, `152` of
them backed by a `*_Stats` object = the playable characters).

Also already on the disc: `RentAWreck_Plane / _Car / _Boat`
(`77878CD4 / 0C4E3BF4 / 47422C66`) — the per-terrain rental vehicles, used by the
`Greeble*Info` villain bots (`tmpl A76001FE`, `variant 0`). That trio is a
proven "(character, AI template, rental vehicle)" bot on every terrain.

## Why added objects hung: the key registry is a hash index

`0x139B` is not a plain key list. Its entries are ordered by

```
bucket(key) = djb2(key as 4 big-endian bytes) >> 24      (256 buckets)
```

— ascending bucket, ascending key inside a bucket. Verified over all 415 entries
of the `RacerAIInfo` group. Appending keys at the end breaks that order, so the
loader can no longer find keys it asks for and the game hangs on the loading
screen. Every earlier insertion did exactly that.

**But even with the registry in bucket order the game still hangs on load**
(`BaseGameplay.pkz.all-415-infos`, 10,264,412 bytes: pools field 130 characters,
every structural check passes, `wit verify` is clean, and the loader still never
leaves the loading screen). So bucket order is not the only invariant — whatever
else the loader wants, it is not visible in the file. Conclusion: **the container
must not change size on this disc.** The tools below are kept for the record.

The working ceiling is what `pkz_random_bots.py` does: rewrite the 71 existing AI
records in place, 71 characters per disc, all 128 reachable across rerolls.

What the bucket-order rebuild would do if the container tolerated growth:

* `tools/pkz_pool_all.py` adds a `Driver<Figure>_<Terrain>_AIInfo` for every
  playable figure (128 figures -> **340 new objects**, group 417 -> 757, registry
  415 -> 755 keys, `BaseGameplay.pkz` 10,164,932 -> 10,254,692);
* `tools/pkz_pool_fill.py` grows the four driver pools to list **every info of
  their terrain** (21 -> 120/123/123/123 records), rebuilding each wrapper's
  data + `0x139C` ref table and every enclosing length.

Result: the pools can field **130 distinct characters**, i.e. every figure on the
disc, and the engine picks each race's opponents out of that pool
(`maxRacers = 0x14`, so a race still shows ~20 racers, but they are drawn from
the whole roster).

Verification: root length == filesize-16, every chunk group tiles, 757 objects /
755 keys in bucket order, all 415 AI infos have `refs = {char, template,
vehicle}`, all pool records mirror their ref table and resolve to real infos,
`wit verify` → `+OK … SKNE52`. Backup: `backups/BaseGameplay.pkz.all-415-infos`.

## Superseded: random bot cast per image (71-record ceiling)

Adding objects does not work: the 412-info build below verifies structurally and
starts, but the game hangs on the loading screen. Every edit that ever worked on
this disc (`pkz_stats_patch.py`, `pkz_pool_swap.py`) leaves the file **the same
size**; the two failures (pool growth, AI-info insertion) both grew it. So treat
`BaseGameplay.pkz` as fixed-size and only rewrite bytes in place.

`tools/pkz_random_bots.py` does that. It re-points the **71 AI records a race
can field** at random playable figures: `charId` = that figure's catalogue key,
and the matching `0x139C` ref entry. Nothing moves: ~650 bytes change, the file
stays 10,164,932 bytes.

* The 56 `Driver<X>_<Terrain>_AIInfo` records are the important ones: they carry
the racer AI template `33D91E1A` and keep their own vehicle. Recasting only the
15 villain records first produced **no visible change in game** - the race does
not field infos whose template is a villain personality, even though the pools
list them.
* The 15 villain infos are recast as well. **The recast writes `charId` only.**
  The first version also pointed every villain info at one per-terrain
  `RentAWreck_Plane/Car/Boat`, which is why a sea field came out as a row of
  identical scrap boats: the shipped data gives each villain its own hull
  (`GoldenQueen_Boat`, `CaptainFrightbeard_Boat`, `Mesmeralda_Boat`,
  `Gulper_Boat`, `DrKrankcase_Car`, `Wolfgang_Plane`, ...) and those are already
  terrain-correct.
* The `Greeble{Plane,Car,Boat}Info` infos are **not** recast. Each action-pack
  pool lists its Greeble record **three times** (one object, eight records in
  the pool), so recasting the object puts three clones of a single figure on the
  grid. They stay as shipped - three Greeble bots - and the roster also never
  hands out the same *toy* twice (224 catalogue entries are 122 characters), so
  no two racers in one field are the same figure in a different paint job.

An action-pack pool can hold at most **five distinct characters**: the `0x139C`
ref table is deduplicated (8 records -> 6 refs) and is fixed size, so extra
records can only repeat keys that already have a ref entry.

That makes a race draw from 128 figures: Spyro, Whirlwind, Bash, Sonic Boom,
Prism Break, Cynder, Drobot, Fryno, Snapshot, Rocky Roll, ... plus the villain
entries.

Run it before each repack for a different cast:

```
python3 tools/pkz_random_bots.py            # random cast
python3 tools/pkz_random_bots.py --seed 7   # reproducible cast
python3 tools/pkz_random_bots.py --dry-run  # just print the cast
```

It picks 68 distinct characters out of the **122** toys the catalogue knows (56
driver infos + 12 villain infos; the three Greeble objects are left alone).

`./reroll.sh [--seed N] [--must Spyro,Whirlwind,Bash]` does the whole cycle:
roll a cast, repack `skylanders-scr-mod.wbfs`, `wit verify`. Rerolling a few
times covers all 128 characters across discs; one disc covers 71 because that is
how many AI records exist and the container cannot grow (see below).

Revert with `cp backups/BaseGameplay.pkz.pristine disc/files/Data/BaseGameplay.pkz`.

### Backups (`scr-wii/backups/`)

| file | what it is |
|---|---|
| `BaseGameplay.pkz.pristine` | untouched original |
| `BaseGameplay.pkz.working-randomcast` | the image confirmed working in game (villain swap + random cast) |
| `BaseGameplay.pkz.probe-spyro` | +1 inserted object (`DriverSpyro_Land_AIInfo`), untested |
| `BaseGameplay.pkz.412-infos-hangs` | the all-figures insertion that hangs on load |
| `BaseSkylander.pkz.pristine` | untouched original |
| `BaseSkylander.pkz.stats` | the superseded first stats patch (five even profiles) |

## Failed attempt: an AI info for every figure, every terrain (reverted)

`tools/pkz_ai_add.py` clones `GreeblePlaneInfo` / `GreebleCarInfo` /
`GreebleBoatInfo` per terrain and replaces only the key, the name, the instance
id and the character id, producing `Driver<Figure>_<Terrain>_AIInfo` for every
figure that lacks one: **412 new `RacerAIInfo` objects** covering **152
figures** (456 figure-terrain slots minus those the disc already had).

Insertion is done properly, which the old append attempt never did:

* the new `0x138D` wrapper goes in front of the group's `0x139B` key registry;
* the group's `0x139A` object count grows by the number of objects
  (417 → 829) and the registry gets the new keys (415 → 827);
* the group length and every enclosing length, up to the root chunk, grow by
  `objects + 4 x keys` (`BaseGameplay.pkz`: 10,164,932 → 10,273,700, +108,768).

Verification: root length == `filesize-16`, every chunk group tiles its payload,
all 2,461 pre-existing wrappers keep their name/key/type, the 412 new ones parse
with `refs = {char, template, vehicle}` and appear in the registry, and
`wit verify` → `+OK … SKNE52` with the file extracted from the image equal to the
tree.

Still unproven: whether the engine picks bots from *all* `RacerAIInfo` objects or
only from the keys a pool names. The new infos are not referenced by any pool
yet, so a race either fields them (enumeration by type) or ignores them; the
pool side is the next step if it does.

## Why the other ~115 figures could not be bots (superseded)

The reasoning below was built on the belief that the racer id was an opaque
build-time GUID. It is not — see "Racer identities for every figure" above.

The 4-byte value an AI info carries (`AirLock = 571FA718`, `JetVac = 79E645F7`,
…) is the **racer identity**. Every attempt to obtain one for a non-racer figure
failed, and the failures are conclusive rather than accidental:

* **Not a name hash.** crc32, FNV-1, FNV-1a and djb2 over 782 package stems and
their permutations (`3425_AirLock`, `0100_JetVac`, `DriverJetVac`, upper/lower,
with/without `.pkz`, `Data/` prefix, …) match none of the 21 known ids. crc32 and
crc32-of-uppercase over all **6,258** names in the `Main.pkz` identifier table
also miss.
* **Not an object id or key.** Scanning every `.pkz` for the known ids finds them
only as *references*: in the AI infos, in `3220_AirJet`
(`VehicleDriverPairList`), in `KaosVillain` and in some UI ref tables. No object
anywhere owns one as its instance id or its key, so there is no table to read a
name → id mapping from.
* **Not in the compact character catalog.** `BaseSkylander.pkz` has 753 catalog
objects (`0000_Whirlwind_Polar`, `0100_JetVac_Series3_FullBlast`, …) of type
`0x5DA30426`, each referencing a base figure GUID at payload `+0x24`
(`Whirlwind = 46144FA8`). Those are a *different* id space: none of the 21 racer
ids appears in that catalog's data or ref tables.
* **Not in the per-figure packages.** Every figure ships `<num>_<Name>.pkz` with
a `*_HI`/`*_Loader` object set; only 8 characters ship a
`<num>_Driver<Name>.pkz`. The package GUIDs (own ids, keys, catalog refs) never
equal a racer id.

So the disc defines racer identities for exactly **20 drivers + 14 villains**,
and those are now all reachable from every pool. The remaining figures have no
racer id, no vehicle pairing and no AI template — there is nothing on the disc to
copy into a new `RacerAIInfo`.

## State of the mod

As shipped now: `BaseGameplay.pkz` = pristine + the villain key swap in the four
driver pools + those 15 villain records re-pointed at a random cast of playable
figures (all in place, size unchanged); `BaseSkylander.pkz` = spiked stats for
every figure (216 records rewritten in place, 3,499 bytes changed, file size
unchanged, md5 `b74d29363041ca175717ed30f37091ea`).
`skylanders-scr-mod.wbfs` was repacked from that tree and verified
(`wit verify` → `+OK … SKNE52`, both files inside the image compare equal to the
working tree), and the game starts and loads with it.

`skylanders-vanilla.wbfs` is a known-good pristine repack of the same tree
(`disc` with both `.orig` files restored); keep it as the fallback when testing
data edits.

## Useful facts

* `wit` (Wiimms ISO Tool 3.05a) is installed at `DolRecomp/extern/wit/bin/wit`
  and can extract (`wit EXTRACT`) and repack (`wit COPY`) this disc.
* Dolphin 2606a is installed, so a patched image can be smoke-tested.
* The extracted tree can be repacked to `.wbfs`/`.iso` for testing.

## Multiplayer on this disc: local split-screen, online never shipped

Checked because "is it splitscreen or real multiplayer" came up. Answer: local
split-screen, and the online half of the engine is present but never wired.

Wired and reachable (per level, 23 `*_Common.pkz`):

    0x80000009 managers   MNG_SplitscreenOverrider_2P / _4P / _Multiplayer
    race scripts          Multiplayer_IsSpectator(), eventArgs.PlayerIndex < 2
    BaseGameplay.pkz      PAGE_Multi_Local_ResultScreen_Race, Player2Reference,
                          CurrentPlayerIndex, ButtonSubHUD_SecondPlayerSelection
    FrontScreen.pkz       PAGE_MultiLocal_GameSelect, MENU_ButtonMultiLocal_L/C/R,
                          TEXT_MultiLocal, "Multi Player" / "Local"
    UI strings            "P2 Press any button to join", "Player 2 connect Wii\n                          Remote", "P2 hold \MENUBACK\ to quit"

Present but dead code / dead assets:

    ELF                   Demonware bdLobby/bdMatchMaking/bdSession/bdSocketRouter,
                          NWNetworkMgr, NWMatchMakingStateMachine, NWSession,
                          GLAPINetwork (+ SetDemonwareAuthAddress /
                          SetDemonwareLSGAddress / SetDemonwareTitleID),
                          nw4hbm layouts, STUN hosts stun.{us,eu,jp,au}.demonware.net
    FrontScreen.pkz       MENU_ButtonMultiOnline_L/C/R, TEXT_MultiOnline,
                          MENU_MultiOnline_Image, MENU_CreateGame_Image,
                          SubPage_MultiWaitingHUD, BUTTON_Multi_isOnline
    string table          "Create a Room", "Looking for Portal Masters...",
                          "Connecting to the Skylands Network...", and Sony PSN
                          and 3DS text that cannot come from a Wii build

Why it is dead, in order of the gate:

1. `GLAPINetwork`'s vtable (`0x805422D0`) is referenced only from `.debug_loc`
   and `.symtab`; its constructor is never called. `NWNetworkMgr` is built by
   `GEEngineMgr` and everything below it (lobby, matchmaking, session) is
   internally well connected — but nothing above it ever starts a session.
2. FrontScreen has `PAGE_MultiLocal_GameSelect` but no `PAGE_MultiOnline_*`
   page object: the online page set is not in this build's data, only its
   elements are. Page composition lives in the compiled GoliathScript
   (`GS version 9.0.175008`), not in the object graph — the UI objects carry no
   `0x139C` cross references at all.
3. The Demonware client address is a runtime value (`SetDemonware*Address`);
   nothing ever sets it on Wii, so there is no host to point at a private
   server even if the flow were unlocked.
4. Wii online auth goes through Nintendo WFC (`naswii.nintendowifi.net/ac`,
   `/pr`) with Nintendo-signed TLS, i.e. the same wall Wiimmfi had to patch IOS
   for, and the Demonware LSG protocol itself is proprietary.

Consequence: an "alternative server" has no client to serve yet. Reviving the
mode means writing a GoliathScript decompiler/patcher (or hand-patching PPC
bytecode) to restore the online page and the `GLAPINetwork` init path, then
implementing the auth/LSG protocol and the Wii TLS bypass. Everything else in
the mod (roster, launcher, split-screen) is independent of that work.

## Multiplayer: 4-player local is code, not data (checked against the 3DS)

Asked for: "make multiplayer as it is on the 3DS, with 4-player local play".
The Wii disc's local multiplayer (2P split-screen) is **already wired and
complete**; what is 4-player on the 3DS is not data this build is missing. Both
halves of that were checked, with the 3DS dump read through the new
`tools/pkz_3ds.py` (see "Reading the 3DS build" below).

**The data is there on both builds, object for object.**

| | Wii | 3DS |
|---|---|---|
| player references in `BaseGameplay.pkz` | `Player1Reference`, `Player2Reference` | `Player1Reference`, `Player2Reference`, `PlayerObjectReference` |
| per-level splitscreen overriders | `MNG_SplitscreenOverrider_2P` / `_4P` / `_Multiplayer`, in all 23 `*_Common.pkz` | the same three, **same keys** (`_2P` 36E03B5C, `_4P` DE2768C0, `_Multiplayer` 5EAAA9BB) |
| 4-player UI art | `MENU_Glow_Player03/04`, `BUTTON_SkylanderSelection_Player03/04`, `BUTTON_MultiToySkylander01..08`, `CurrentRoomPlayerText01..04` | same set |

So the Wii build ships the 4P viewport object, the 4P HUD art and 8 toy slots -
left over from the shared asset pipeline - and no amount of key flipping reaches a
mode whose *player joining* is 2P.

**The joining logic is native code, not data.** The Wii's local multiplayer
menu scripts are plain text inside `FrontScreen.pkz` and every one of them stops
at two players:

```
return Menu_IsSplitScreenToysSelectionDoneByPlayerIndex(1) and
       Menu_IsSplitScreenToysSelectionDoneByPlayerIndex(0)
local playerIndex = Menu_GetCurrentPlayerActing()
```

The part that actually decides how many local players a session accepts is
registered by `gamelogic.rso` (`MultiplayerMenuManager`, `IsLocalMultiplayer`,
`Player_GetHasMultiplePlayers`, `SpawnLocalPlayer`), i.e. compiled PowerPC, and
the online half that would have supplied the rest was never shipped ("Multiplayer
on this disc" above: no `PAGE_MultiOnline_*`, `GLAPINetwork` never constructed).

**Consequence.** Enabling 4-player local play is not a `.pkz` edit. It means
patching the executable - the symbols to chase are the splitscreen manager's
`InitSplit`, `uiNbPlayers`, `uiSplitWidth` / `uiSplitHeight`, `muiSplitAxis`,
and the spawn path `SpawnLocalPlayer` - and the only verification available here
is a boot test, because leaving the load screen needs input (see "The base that
ships"). Everything else about the mode already works: the four multiplayer race
playlists, the cups, the split-screen HUDs and the 2P flow.

## Applied mod: the stats patch, ported to the 3DS build

`tools/pkz_3ds_stats.py` is `pkz_stats_patch.py` for the 3DS romfs. It imports
the Wii tool's scheme (archetypes, 3.0 budget, 0.05 grid, the roster-wide
"no two spreads alike" pass) rather than reimplementing it, so the seed is the
figure's name and the names are the same on both builds:

    3DS  0101_SwarmStats            shipped 0.00 0.00 0.00 0.00 0.00
                                   patched 0.50 1.00 0.10 1.00 0.40

What had to be rewritten is only the container: the file is a little-endian
roceGS stream inside one zlib stream (`pkz_3ds.py`), the stat body is the same 36
bytes, and on this build the five floats are little-endian where the Wii's are
big-endian. The type word is big-endian on both.

Written back at the **same size**: re-deflate the patched stream, update the
header's compressed size (+0x10), pad the tail with the `0xDA` the original used,
and refuse rather than guess when the new stream does not fit. Verified on
`BaseSkylander.pkz` (98304 bytes in, 98304 out):

* 203 stat records found, **148 of them all-zero - the same 148 stubs the Wii
disc ships**, so this build's roster has exactly the same hole in it;
* 3,245 bytes changed, and **0 of them outside a stat record's 20 float bytes**;
* the object count is unchanged (343), the uncompressed size is unchanged
  (174,028), only the compressed size moves (63,505 -> 26,159) and the freed room
  becomes `0xDA` padding;
* every record totals 3.00, **203 distinct spreads**, none left all-zero, all
  values on the 0.05 grid, and re-running the tool reproduces the file;
* **198 of the 203 figures get the identical spread the Wii build's patch gives
them** (`--compare` checks this figure by figure). The five that differ: two
records on the 3DS ship **no name of their own** (the printable run after the body
belongs to the next object, so they are seeded from their object id instead of a
borrowed name), two are named `..._EonsElite_Stat` where the Wii says `_Stats`,
and one is collateral - the uniqueness pass walks a repeated spread off whatever
the figure before it took, and this roster is a shade different.

Install: Luma's layeredfs, no romfs repack -

    python3 tools/pkz_3ds_stats.py <romfs>/Data/BaseSkylander.pkz \
        --out 3ds/titles/0004000000165E00/romfs/Data/BaseSkylander.pkz

Not verified: the pips on screen. The check above is container-level, and there
is no 3DS emulator in this repo to boot it on.

## The bot patch on the 3DS: not portable yet

`pkz_random_bots.py` recasts the Wii's 71 `RacerAIInfo` records. This build's
`BaseGameplay.pkz` has none: reading it with `pkz_3ds.py` gives 1,236 objects and
the only AI-shaped name among them is `RacerAISpawner`, which is a class in the
identifier table, not racer data. Two possibilities, and they need different work:

* the 3DS definition of who an opponent is lives somewhere this reader does not
  reach yet - `Main.pkz` still resolves to 0 objects and a level file to ~185 of
  its thousands, because where one package's zlib stream ends and the next begins
  is approximated rather than parsed (the header's block table is not fully
  understood; `pkz_3ds.py` says so);
* or this build drives its opponents from its own classes, in which case the
  patch has to be redesigned against them rather than ported.

So the honest order is: finish the package framing, then look for the racer
records, then port. Writing a 3DS bot patcher now would be guessing.

## An alternative server for the 3DS online mode

The 3DS build's competition mode is **local play or online with up to four
players**, and the online half needed a Nintendo Network account (Activision's own
support page: "your console must be signed into an active ... Nintendo Network
account"); 3DS online was shut down in 2024.

There is nothing to point at a private server from this dump:

* the endpoints are not in the romfs. Searching the whole 3DS `Data/` tree for
  hostnames finds none - the only `.net/.com` strings in there are animation
  names (`rumble.ca`, `strongloop.ca`, ...). On the Wii build the same strings
  live in the ELF (`stun.{us,eu,jp,au}.demonware.net`, the Demonware LSG calls),
  i.e. in code, and a 3DS romfs dump does not contain code;
* the client itself is the dead half even if the address were patched: the Wii
  build shows what the client is (Demonware `bdLobby` / `GLAPINetwork`, a
  proprietary protocol with no public documentation), and no community server for
  this game exists - Pretendo reimplements Nintendo Network, not a third-party
game backend.

To make progress on that half, the piece this dump does not have is the 3DS
**executable** (`code.bin`/exefs). With it the endpoint table and the TLS/auth
path can be found and described, which is the step before any server could be
written. The rest of the mod - stats above, and local 4-player play, whether on
this build or the Wii one - needs no server at all.

## Reading the 3DS build (`tools/pkz_3ds.py`)

The 3DS romfs is the same game data in a different wrapper, and both differences
are now documented and handled:

* the container is **little-endian** (Wii is big-endian) - a plain one starts
  `01 00 00 80` = tag `0x80000001`, and in the 16-byte chunk header the two u32s
  swap: Wii `tag u16 u16 0 len`, 3DS `tag u16 u16 len 0`;
* a file starting `b0 b1 be ba` is **zlib-compressed**: 0x8000 bytes of header
  (+0x04 payload offset, +0x0C uncompressed size, rest 0xAA fill) followed by one
  or more zlib streams, each inflating to a little-endian roceGS stream.

On that dump 90 of the 782 files are plain and 691 are the zlib wrapper,
including every file the multiplayer wiring lives in. Measured with the tool:

| file | on disk | inflates to | objects |
|---|---|---|---|
| `BaseSkylander.pkz` | 98,304 | 174,028 (== its header's size) | 343 |
| `BaseGameplay.pkz` | 3,014,656 | 6,154,009 | 1,234 |
| `MultiplayerHuds.pkz` | 294,912 | 617,117 | 149 |
| `L_ChompyMountain_Common.pkz` | 3,342,336 | 7,377,190 | 185 |

That is how the `Player*Reference` and `MNG_SplitscreenOverrider_*` comparison
above was made. The tool's object reader falls back to a tag sweep when a 3DS
object frames differently from the Wii one, so `payload=0` in a listing means
"the walk did not resolve that body", not "the object is empty".

## How many figures the disc can actually field

`BaseSkylander.pkz` holds the toy catalogue (`0x5DA30426`, 437 entries) and the
per-figure stats (`0x4BBD2CFD`, 304 entries). Only part of the catalogue is
figures; by toy number the figure ranges are

    00xx Spyro's Adventure   01xx Giants      04xx Trap Team
    05xx minis               30xx Trap Team   34xx SuperChargers

and the rest of the catalogue is something else: `02xx` magic items, `03xx`
adventure packs, `10xx`/`20xx` SWAP Force halves, `32xx` vehicles and vehicle
items (`3222`-`3241`), `33xx` level packs, `35xx` expansion packs and the Kaos
trophy, plus the `Driver*` duplicates of the SuperCharger figures.

That leaves **224 catalogue figures over 122 distinct toy numbers** (the
difference is the variant line: Series 2/3/4, LightCore, Eon's Elite, Dark,
Legendary, Legendary LightCore, seasonal), 221 of which have a portrait on the
disc. 126 of the 224 ship their own stat record (counted by object type; the
name-suffix scan the launcher used sees only 111); the other 98 inherit their
base figure's numbers at runtime.

Two things worth knowing:

* the earlier 121-figure pool was the *intersection* of catalogue and stats, so
  it silently dropped every variant that has a catalogue entry but no stats of
  its own - that is what "are you sure you have all figures" was about. The
  launcher now rolls over all 224.
* a further ~90 names have a stats object and a character package
  (`0472_Chopper.pkz`, `0473_TreadHead.pkz`, `0481_FunnyBone.pkz`, ...) but no
  catalogue entry, so there is no charId to give a `RacerAIInfo`. Their
  per-package character object has a different key from the catalogue one, so
  naming them as racers is not possible with what is on the disc today.

The 340+ figure claim is the physical-toy compatibility of the whole franchise;
the disc's own catalogue is the 224 above.

## How the player's own figure works (the portal, not the pkz)

Everything the mod patches so far is *opponents*: the 71 `RacerAIInfo` records a
race fields. The figure the player races as is not one of them - the game reads
it from the Portal of Power over USB, so on Dolphin it comes from Dolphin's
emulated portal instead of from the disc.

Checked in Dolphin's source (`IOS/USB/Emulated/Skylanders/`):

| | |
|---|---|
| figure size | `FIGURE_SIZE = BLOCK_COUNT (0x40) * BLOCK_SIZE (0x10)` = **1024 bytes** |
| file types | `.sky .bin .dmp .dump` - all the same 1024-byte tag image |
| decryption | per block: `key = MD5(block0‖block1‖0x00‖i‖HASH_CONST)` with `HASH_CONST = " Copyright (C) 2010 Activision. All Rights Reserved. "`, AES-CBC IV 0; sector trailers and blocks 0-7 are plaintext |
| settings | `[General] SkylandersCollectionPath`, `[EmulatedUSBDevices] EmulateSkylanderPortal` (`MainSettings.cpp:346`, `:628`) |

The tag library at `skylanders-nfc-sim/data` is 782 real dumps of exactly that
size (`dumps.bin.gz` = 782 x 1024, listed by `roster.json`: 429 figures, 19
minis, 35 vehicles, 67 traps, 80 crystals, 42 magic items, 110 chests). Verified
by decrypting dumps with the algorithm above: the blocks come out structured
(toy code present, figure id non-zero, `Barrel Blaster (Dark)` variant 580),
i.e. they are genuine encrypted tag images, not something this repo invented.

So "which Skylander and which vehicle do I use" needs no disc edit at all:
`launcher/toys.py` writes the chosen dumps into `launcher/portal/`, points
Dolphin's collection path there and enables the emulated portal, and the swap
happens inside Dolphin while the game runs.

## Character racing stats: what the disc has, and how it got flattened

`BaseSkylander.pkz` holds one `*Stats` object per character with five big-endian
floats (TopSpeed, Acceleration, Armor, Handling, FirePower, 0..1 at data+0x20).
Current state of the shipped data (`backups/BaseSkylander.pkz.pristine`, md5
`003d9404765c`):

| | |
|---|---|
| stats objects, counted by object type | **304**: 203 character/driver entries + 101 vehicle (`*_Stats_Mod_0/1/2/SC`, `*Plane/Car/Boat_Stats`, `RentAWreck_*`) |
| distinct value sets | **114** (one of them is all-zero) |
| records that are all-zero | **161** (148 character records + 13 villain hulls) |
| non-empty character records | **55**, holding 54 distinct spreads |
| toy numbers with any real values | **34 of 168** |

The name-suffix scan this section first used found only 194 of those 304, and the
old tool inherited that: 92 records do not end in `Stats` (the vehicle mod
stages) and 27 keep the key in front of the name in the key chunk, so a
printable-run regex read the key as the name. Counting by type is the fix.

So the disc ships real racing numbers for only 55 of its 203 character records
(34 of the 168 toys); the other 148 are zero-stubs - there is no per-figure stats
object for them anywhere else (`BaseGameplay.pkz` and `Common.pkz` have none).
Two same-toy cases differ too: `0005_TerrafinStats` has values while
`0005_Terrafin_EonsElite_Stats` is all zeros.

The first version of `tools/pkz_stats_patch.py` collapsed every character onto
**5 profiles**, which is why a tree patched with it played identically figure to
figure, and it also only reached the 196 records whose name ends in `Stats`. Both
are fixed: the tool enumerates by object type (all 203 character records) and
gives each figure its own spread, so the flattening is gone. What cannot be fixed
is the source data - the 148 empty records have to be invented, nothing on the
disc provides them. See "Applied mod: stats for every figure" above for the
scheme and the verification.

## A racer's two refs: which one broke the disc

`RacerAIInfo` carries its refs back to back in one body:

```
doff+28   character  (the figure the racer looks like)
doff+32   AI template (0x33D91E1A on every driver; *not* the vehicle)
doff+36   vehicle    (what the racer drives)
```

`roster.py` only ever writes the character (and the matching ids in the
wrapper's `0x15,id` table). The vehicle is written **once, at bake time**, by
`tools/pkz_random_bots.py`.

| | pristine | shipped base |
|---|---|---|
| distinct vehicle refs | 35 | 23 |
| driver infos on their own hull | 56 | 56 |
| villain infos on their own hull | 12 | 0 - all twelve on the terrain rental |

The twelve villain infos (`ChefPepperJackInfo`, `CluckInfo`, `PainYataInfo`,
`WolfgangInfo`, `ChompyMageInfo`, `CountMoneyBoneInfo`, `DrKrankcaseInfo`,
`GlumshanksInfo`, `CaptainFrightbeardInfo`, `GoldenQueenInfo`, `GulperInfo`,
`MesmeraldaInfo`) are moved onto the rental the shipped Greeble bots drive -
`RentAWreck_Plane` / `_Car` / `_Boat` (`77878CD4` / `0C4E3BF4` / `47422C66`).
A villain info left on its own hull (`GoldenQueen_Boat`, `DrKrankcase_Car`, ...)
with a different figure under it is what came up as a corrupt racer and killed
the disc; that state was live for one build and is now reverted.

So "every sea bot drives the same boat" is not a bad patch: on the sea grid the
rental (`RentAWreck_Boat`) is used by the four sea villain infos plus
`GreebleBoatInfo` - five of the 22 spots - and the plot drivers keep the hulls
the disc ships them with. Fifteen of the 71 spots sit on a rental in total
(twelve villains + the three Greeble dummies).
Giving the villains their own boats back is exactly the change that corrupts the
race - it needs the villain's vehicle *object* and its driver pairing to survive a
character swap, which the rental does not depend on.

### The base that ships

```
BaseGameplay.pkz vs pristine: 824 bytes, size identical
  279 in the 71 character refs
  327 in the wrapper 0x15,id tables (the same ids mirrored next to the object)
  218 in the EnemyAIList_* / ActionPackPersonalityList pools and villain bodies
  12 vehicle refs  -> terrain rental (villain infos only)
racer slots 71 (25 land / 24 air / 22 sea); any roll gives 22-25 distinct
characters per terrain with no character twice in one terrain
Common.pkz  pristine cup order (the launcher rolls the cups per play)
image       wit verify: +OK; boots through the language select and loads
            Chompy Mountain Race (hint carousel / "Browse hints")
```

Beyond the language screen the game needs input to continue, so the check above
is a boot log read off a screen capture, not a driven race - hitting that load
screen is the furthest this repo can verify on its own.

Roll back state, should another build misbehave: `backups/BaseGameplay.pkz.working-randomcast`
(this base) plus `backups/Common.pkz.pristine`.
