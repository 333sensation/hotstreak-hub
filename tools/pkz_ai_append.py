#!/usr/bin/env python3
"""Append Driver<Name>_<Terrain>_AIInfo records so every Skylander can be a bot.

Bot racers only exist for the 20 SuperChargers because BaseGameplay.pkz ships 60
`RacerAIInfo` objects (20 drivers x Land/Air/Sea). Nothing else in the data
references those objects by id, so a new record with the right type hash is all
the engine needs to discover one more AI driver.

Record layout (byte offsets relative to the data chunk tag, cloned verbatim from
`Driver<X>_<Terrain>_AIInfo`):

    +0x00  80 00 13 91 00 08            data chunk tag
    +0x06  00 00 00 00 00 00            header filler
    +0x0C  <payload size = 0x1C>
    +0x10  <object id>                  unique per object
    +0x14  45 BA 52 4C                  type = crc32("RACERAIINFO")
    +0x18  00 00 00 00
    +0x1C  <character resource id>
    +0x20  <AI template id>
    +0x24  <vehicle resource id>        per terrain
    +0x28  <terrain: 1=Land 2=Air 3=Sea>
    ...    closing chunks, 0x5C chunk with a second unique id
    ...    ff ff ff ff + name in a 64-byte zero padded field

The records are appended at the end of the file and the header size field
(0x0C = file size - 16) is updated, so no existing byte or offset moves.
"""
import argparse
import os
import re
import shutil
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pkz_objects import parse_objects, type_hash  # noqa: E402

DATA_DIR = "disc/files/Data"
GAMEPLAY = os.path.join(DATA_DIR, "BaseGameplay.pkz")
SKYLANDER = os.path.join(DATA_DIR, "BaseSkylander.pkz")
NAME_FIELD = 0x40
TERRAINS = [(1, "Land"), (2, "Air"), (3, "Sea")]

# a character pkz is a plain figure pack: NNNN_Name.pkz
CHAR_RE = re.compile(r"^(\d{4})_([A-Za-z0-9]+)\.pkz$")
# vehicles, expansions and other non-character packs
SKIP_NAMES = {
    "AirJet", "UndeadBuggy", "WaterFishSub", "FireBike", "FireCar", "EarthTank",
    "EarthTruck", "UndeadCoffin", "LifeCopter", "WaterTorpedoSub", "AirPlane",
    "ClownPlane", "TechBike", "TechTruck", "LightPlane", "DarkSub", "MagicSub",
    "MagicBoat", "DKCart", "LifePlane", "SkyRacingExpansion",
    "LandRacingExpansion", "SeaRacingExpansion", "KaosTrophy", "KnightMare",
}


def resource_ids(path):
    """Map 0x5C-chunk id -> resource name for one pkz."""
    d = open(path, "rb").read()
    out = {}
    for m in re.finditer(rb"\x5c(.{4})\x00\x00\x00[\x15\x0f]", d, re.S):
        oid = struct.unpack(">I", m.group(1))[0]
        end = d.find(b"\xff\xff\xff\xff", m.end())
        nm = re.match(rb"\xff\xff\xff\xff([ -~]{3,60})\x00", d[end:end + 80])
        if nm:
            out.setdefault(nm.group(1).decode("latin1"), oid)
    return out


def record_bytes(d, obj):
    """Raw bytes of one object record, from its data chunk to its name field."""
    name_pos = d.find(obj.name.encode(), obj.offset)
    if name_pos < 0:
        raise RuntimeError("can't locate name for " + obj.name)
    return bytearray(d[obj.offset:name_pos + NAME_FIELD])


def patch_record(rec, own_id, c5_id, char_id, template_id, vehicle_id, terrain, name):
    old5 = struct.unpack_from(">I", rec, 0x10)[0]
    struct.pack_into(">I", rec, 0x10, own_id)          # object id
    struct.pack_into(">I", rec, 0x1C, char_id)
    struct.pack_into(">I", rec, 0x20, template_id)
    struct.pack_into(">I", rec, 0x24, vehicle_id)
    struct.pack_into(">I", rec, 0x28, terrain)
    # the 0x5C chunk carries a second id; locate it by its marker
    m = re.search(rb"\x5c(.{4})\x00\x00\x00\x15", bytes(rec), re.S)
    if not m:
        raise RuntimeError("0x5C chunk not found")
    struct.pack_into(">I", rec, m.start() + 1, c5_id)
    # name field: 64 bytes, zero padded
    name_pos = len(rec) - NAME_FIELD
    if len(name) > NAME_FIELD - 1:
        raise RuntimeError("name too long: " + name)
    rec[name_pos:] = name.encode("latin1").ljust(NAME_FIELD, b"\0")
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", default="DriverJetVac")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="", help="comma separated character names")
    args = ap.parse_args()

    d = open(GAMEPLAY, "rb").read()
    objs = list(parse_objects(GAMEPLAY))
    ai_th = type_hash("RacerAIInfo")

    templates = {}
    template_id = None
    for o in objs:
        if o.type == ai_th and o.name.startswith(args.template + "_"):
            terrain = o.name.split("_")[1]
            templates[terrain] = o
            template_id = struct.unpack_from(">I", o.fields, 8)[0]
    if len(templates) != 3:
        print("error: need Land/Air/Sea templates, found", sorted(templates))
        return 1

    # vehicle ids per terrain, taken from the template driver
    vehicles = {}
    for terrain, o in templates.items():
        vehicles[terrain] = struct.unpack_from(">I", o.fields, 12)[0]

    # character -> resource id
    res = resource_ids(SKYLANDER)
    chars = {}
    for fn in os.listdir(DATA_DIR):
        m = CHAR_RE.match(fn)
        if not m:
            continue
        num, name = m.group(1), m.group(2)
        if name in SKIP_NAMES:
            continue
        key = "%s_%s" % (num, name)
        if key in res:
            chars[key] = res[key]
    if args.only:
        want = {s.strip() for s in args.only.split(",") if s.strip()}
        chars = {k: v for k, v in chars.items() if any(k.endswith("_" + w) or k == w for w in want)}

    print("template       : %s (template id %08X)" % (args.template, template_id))
    print("vehicles       : " + ", ".join("%s=%08X" % (t, vehicles[t]) for t in vehicles))
    print("characters     : %d with a resource id in BaseSkylander" % len(chars))

    existing_names = {o.name for o in objs}
    existing_ids = set()
    for o in objs:
        existing_ids.add(o.oid)
    existing_ids |= set(struct.unpack(">I", d[i:i + 4])[0] for i in range(0, len(d), 4))

    recs_out = bytearray()
    added = 0
    for key, char_id in sorted(chars.items()):
        pretty = key.split("_", 1)[1]
        for terrain_no, terrain_name in TERRAINS:
            name = "Driver%s_%s_AIInfo" % (pretty, terrain_name)
            if name in existing_names:
                continue
            rec = record_bytes(d, templates[terrain_name])
            # deterministic unique ids that cannot collide with existing values
            salt = 0
            while True:
                own_id = zlib_crc("AI:%s:%d" % (name, salt))
                c5_id = zlib_crc("AI5:%s:%d" % (name, salt))
                if own_id not in existing_ids and c5_id not in existing_ids and own_id != c5_id:
                    break
                salt += 1
            rec = patch_record(rec, own_id, c5_id, char_id, template_id,
                               vehicles[terrain_name], terrain_no, name)
            recs_out += rec
            existing_ids.add(own_id)
            existing_ids.add(c5_id)
            added += 1

    # the container ends with a 16-byte trailer (header size field = size - 16),
    # so the new object records go just before it, keeping every offset stable
    trailer = 16
    out = bytearray(d[:len(d) - trailer]) + recs_out + bytearray(d[len(d) - trailer:])
    print("new records    : %d (%d characters x 3 terrains)" % (added, added // 3))
    print("insert at      : end of object stream (0x%X), before the 16-byte trailer"
          % (len(d) - trailer))
    print("new file size  : %d -> %d (+%d)" % (len(d), len(out), len(out) - len(d)))
    if args.dry_run:
        print("(dry run, nothing written)")
        return 0

    # header field at 0x0C is (file size - 16) in both containers
    struct.pack_into(">I", out, 0x0C, len(out) - 16)
    backup = GAMEPLAY + ".orig"
    if not os.path.exists(backup):
        shutil.copy2(GAMEPLAY, backup)
        print("backup         :", backup)
    open(GAMEPLAY, "wb").write(out)

    check = list(parse_objects(GAMEPLAY))
    new_ai = [o for o in check if o.type == ai_th]
    print("verify         : %d RacerAIInfo records now parse (was %d)"
          % (len(new_ai), len([o for o in objs if o.type == ai_th])))
    return 0


def zlib_crc(text):
    import zlib
    return zlib.crc32(text.encode()) & 0xFFFFFFFF


if __name__ == "__main__":
    sys.exit(main())
