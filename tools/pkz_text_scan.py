#!/usr/bin/env python3
"""Scan goliath .pkz containers for embedded plaintext script blobs.

The engine stores script source (Lua-like) uncompressed inside the packages,
surrounded by binary records. This dumps every plausible text blob to
outdir/<pkz>__<offset>.txt and writes an index for grepping.
"""
import os
import re
import sys

TEXT = bytes(range(0x20, 0x7f)) + b"\r\n\t"
TEXT_SET = set(TEXT)


def blobs(data, min_len=48):
    n = len(data)
    i = 0
    find = data.find
    while i < n:
        # fast skip: look for a byte that could start text
        b = data[i]
        if b not in TEXT_SET:
            i += 1
            continue
        j = i
        last_bad = i
        while j < n:
            c = data[j]
            if c in TEXT_SET:
                j += 1
                continue
            break
        blob = data[i:j]
        if len(blob) >= min_len and blob.count(b"\n") >= 1:
            yield i, blob
        i = j if j > i else i + 1


def main():
    src = sys.argv[1]
    outdir = sys.argv[2]
    os.makedirs(outdir, exist_ok=True)
    index = open(os.path.join(outdir, "index.tsv"), "w")
    total = 0
    for name in sorted(os.listdir(src)):
        if not name.lower().endswith(".pkz"):
            continue
        path = os.path.join(src, name)
        with open(path, "rb") as f:
            data = f.read()
        count = 0
        for off, blob in blobs(data):
            out = os.path.join(outdir, "%s__%08x.txt" % (name, off))
            with open(out, "wb") as g:
                g.write(blob)
            index.write("%s\t%08x\t%d\n" % (name, off, len(blob)))
            count += 1
        total += count
        print("%-40s %6d blobs" % (name, count))
    index.close()
    print("total blobs:", total)


if __name__ == "__main__":
    main()
