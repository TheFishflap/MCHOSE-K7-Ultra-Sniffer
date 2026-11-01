#!/usr/bin/env python3
"""
decode.py - exakter goebish-XN297-Decoder + Mehrheitsentscheid.

Nach goebish xn297_decod.cpp:
  - Adresse (erste ADDR_LEN Bytes): byte ^ xn297_scramble[byte_count]
  - Payload (danach):   rev(byte) ^ rev(xn297_scramble[byte_count])
  - byte_count laeuft durch Adresse UND Payload (Payload-Byte0 -> scramble[ADDR_LEN]).

Unser Sync 52 b1 5a db sind die ersten 4 (gescrambelten) Adressbytes. Wir
schneiden ab dem Sync ADDR_LEN+PKT Bytes, decodieren, und bilden pro
decodierter Payload-Position den Mehrheitswert ueber viele Frames (mittelt
die nRF52-Demod-Bitfehler weg).

Nutzung:
    python decode.py move=tools/long_move.log lhold=tools/long_lhold.log
"""
import re
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
PKT_RE = re.compile(r"PKT[^:]*:\s*((?:[0-9a-f]{2}\s*)+)", re.I)

ADDR_LEN = 5
PKT = 19
TOTAL = ADDR_LEN + PKT

XN297_SCRAMBLE = bytes.fromhex(
    "e3b14bea85bce5660dae8c881269ee1f"
    "c76297d50b79cacc1b5d191024d3dc3f8ec52f")

SYNC = "".join("{:08b}".format(b) for b in bytes.fromhex("52b15adb"))


def rev8(b):
    r = 0
    for i in range(8):
        r = (r << 1) | (b & 1)
        b >>= 1
    return r


def bits_of(d):
    return "".join("{:08b}".format(b) for b in d)


def frames_from(path):
    """Bytes AB dem Sync (inkl. Sync), TOTAL Bytes, bit-weise gesucht."""
    out = []
    for line in open(os.path.join(HERE, path), encoding="utf-8", errors="replace"):
        m = PKT_RE.search(line)
        if not m:
            continue
        bs = bits_of(bytes.fromhex(m.group(1).replace(" ", "")))
        start = 0
        while True:
            j = bs.find(SYNC, start)
            if j < 0:
                break
            chunk = bs[j: j + TOTAL * 8]
            if len(chunk) >= TOTAL * 8:
                out.append(bytes(int(chunk[k:k+8], 2) for k in range(0, TOTAL*8, 8)))
            start = j + 1
    return out


def decode(frame):
    out = bytearray()
    for bc in range(len(frame)):
        b = frame[bc]
        s = XN297_SCRAMBLE[bc]
        if bc < ADDR_LEN:
            out.append(b ^ s)
        else:
            out.append(rev8(b) ^ rev8(s))
    return bytes(out)


def majority(frames, pos):
    c = Counter(f[pos] for f in frames)
    v, n = c.most_common(1)[0]
    return v, n / len(frames)


def main():
    paths = {}
    for a in sys.argv[1:]:
        n, _, p = a.partition("=")
        paths[n] = p
    sets = {n: [decode(f) for f in frames_from(p)] for n, p in paths.items()}
    for n in sets:
        print("%-8s %d Frames" % (n, len(sets[n])))
    print("\nDecodierte Payload (Mehrheitswert je Position, ab Payload-Byte 0):")
    print("Erwartet HID-aehnlich: id=01 | buttons | Xlo Xhi | Ylo Yhi | scroll\n")
    names = list(sets)
    hdr = "payload# " + "".join("%-13s" % n for n in names)
    print(hdr)
    for i in range(ADDR_LEN, TOTAL):
        cells = ""
        for n in names:
            if sets[n]:
                v, f = majority(sets[n], i)
                cells += "0x%02x(%3.0f%%)  " % (v, f * 100)
            else:
                cells += "   -        "
        print("  p%-2d    %s" % (i - ADDR_LEN, cells))


if __name__ == "__main__":
    main()
