#!/usr/bin/env python3
"""Parse goliath/roceGS .pkz objects and resolve their 32-bit id references.

Every serialised object starts with a data chunk header

    80 00 13 91 00 08 00 00 00 00 <payload size>
    <own id:4> <type:4> <fields...>
    80 00 13 8d ...                       closing chunks
    ff ff ff ff "<ObjectName>"            end marker + inline name

so the object graph can be indexed by walking data chunks. Ids are build-time
GUIDs (not name hashes), which means a reference can only be resolved by
looking up the object that owns the same id.
"""
import os
import re
import struct
import sys
import zlib

DATA_TAG = b"\x80\x00\x13\x91\x00\x08\x00\x00\x00\x00\x00\x00"
END_TAG = b"\xff\xff\xff\xff"
NAME_RE = re.compile(rb"[ -~]{2,80}\x00")


def type_hash(name):
    return zlib.crc32(name.upper().encode()) & 0xFFFFFFFF


KNOWN_TYPES = {}


def _known():
    if KNOWN_TYPES:
        return KNOWN_TYPES
    for n in (
        "RacerAIInfo", "RacerAIList", "RacerAIItem", "RacerAISelector",
        "RacerAISpawner", "RacerSelector", "AIPersonalityItem",
        "AIPersonalityList", "AITemplate", "Character", "CharacterData",
        "CharacterStatsModifiers", "VehicleIdentityModule",
    ):
        KNOWN_TYPES[type_hash(n)] = n
    return KNOWN_TYPES


class Obj:
    __slots__ = ("file", "offset", "size", "oid", "type", "fields", "name")

    def __repr__(self):
        tn = _known().get(self.type, "0x%08X" % self.type)
        return "<%s %s id=0x%08X @0x%X>" % (tn, self.name, self.oid, self.offset)


def parse_objects(path):
    """Yield every object found in one .pkz file."""
    d = open(path, "rb").read()
    for m in re.finditer(re.escape(DATA_TAG), d):
        base = m.start() + len(DATA_TAG)
        if base + 8 > len(d):
            continue
        size, oid, typ = struct.unpack_from(">III", d, base)
        payload_start = base + 12
        end = d.find(END_TAG, payload_start, payload_start + max(size, 0) + 0x200)
        if end < 0:
            continue
        nm = NAME_RE.match(d, end + 4)
        if not nm:
            continue
        o = Obj()
        o.file = os.path.basename(path)
        o.offset = m.start()
        o.size = size
        o.oid = oid
        o.type = typ
        o.fields = d[payload_start:payload_start + max(size, 0)]
        o.name = nm.group(0)[:-1].decode("latin1")
        yield o


def build_index(root):
    """Map own id -> Obj across every .pkz in root."""
    idx = {}
    for fn in sorted(os.listdir(root)):
        if not fn.lower().endswith(".pkz"):
            continue
        for o in parse_objects(os.path.join(root, fn)):
            idx.setdefault(o.oid, o)
    return idx


def dump_fields(o, width=4):
    vals = []
    f = o.fields
    for i in range(0, len(f) - width + 1, width):
        vals.append("%08X" % struct.unpack_from(">I", f, i)[0])
    return " ".join(vals)


def main():
    if len(sys.argv) < 2:
        print("usage: pkz_objects.py <dir> [--type TypeName] [--name substr] [--refs]")
        return
    root = sys.argv[1]
    ftype = None
    fname = None
    show_refs = "--refs" in sys.argv
    for i, a in enumerate(sys.argv):
        if a == "--type":
            ftype = zlib.crc32(sys.argv[i + 1].upper().encode()) & 0xFFFFFFFF
        if a == "--name":
            fname = sys.argv[i + 1]

    idx = build_index(root) if show_refs else {}
    for fn in sorted(os.listdir(root)):
        if not fn.lower().endswith(".pkz"):
            continue
        for o in parse_objects(os.path.join(root, fn)):
            if ftype is not None and o.type != ftype:
                continue
            if fname and fname.lower() not in o.name.lower():
                continue
            print("%-28s %-34s id=%08X size=%-4d %s"
                  % (o.file, o.name, o.oid, o.size, dump_fields(o)))
            if show_refs:
                refs = []
                for i in range(0, len(o.fields) - 3, 4):
                    v = struct.unpack_from(">I", o.fields, i)[0]
                    if v in idx and idx[v] is not o:
                        refs.append("    +0x%02X -> 0x%08X %s [%s]"
                                    % (i, v, idx[v].name,
                                       _known().get(idx[v].type, "?")))
                print("\n".join(refs))


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:      # piping into head/grep is the normal way to use this
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
