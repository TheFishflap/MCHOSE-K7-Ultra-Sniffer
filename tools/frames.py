#!/usr/bin/env python3
"""
frames.py - richtet Promiscuous-Mitschnitte auf den Maus-Marker aus und
            zeigt die Payload-Bytes, optional als Vergleich mehrerer Logs.

Der Promiscuous-Empfaenger (src/main.c, Iter 8) rastet auf eine
alternierende Preamble ein; jedes starke Paket enthaelt danach den
Maus-Frame mit dem konstanten Marker:

    52 b1 5a db | payload ...

Dieses Tool sucht den Marker in jeder "PKT ..."-Zeile, schneidet die
folgenden Bytes als ausgerichteten Frame heraus und wertet aus.

Aufruf:
    # Einzelnes Log anschauen:
    python frames.py tools/move.log

    # Mehrere Aktionen vergleichen (zeigt, welche Byte-Position sich
    # zwischen den Aktionen unterscheidet -> X-Y vs. Taste vs. Scroll):
    python frames.py idle=tools/idle.log move=tools/move.log \
                     lclick=tools/lclick.log scroll=tools/scrollup.log
"""
import re
import sys
from collections import defaultdict

MARKER = bytes.fromhex("52b15adb")
FRAME_LEN = 14  # Bytes NACH dem Marker, die wir betrachten

PKT_RE = re.compile(r"PKT[^:]*:\s*((?:[0-9a-f]{2}\s*)+)", re.I)


def extract_frames(path):
    frames = []
    for line in open(path, encoding="utf-8", errors="replace"):
        m = PKT_RE.search(line)
        if not m:
            continue
        data = bytes.fromhex(m.group(1).replace(" ", ""))
        i = 0
        while True:
            j = data.find(MARKER, i)
            if j < 0:
                break
            payload = data[j + len(MARKER): j + len(MARKER) + FRAME_LEN]
            if len(payload) >= 4:
                frames.append(payload)
            i = j + 1
    return frames


def hexs(b):
    return " ".join("%02x" % x for x in b)


def show_single(path):
    frames = extract_frames(path)
    print("== %s ==  %d ausgerichtete Frames\n" % (path, len(frames)))
    for f in frames:
        print("  " + hexs(f))
    if not frames:
        return
    print("\nPro-Byte-Wertebereich:")
    maxlen = max(len(f) for f in frames)
    for pos in range(maxlen):
        vals = sorted({f[pos] for f in frames if len(f) > pos})
        tag = "  <- KONSTANT" if len(vals) == 1 else ""
        shown = " ".join("%02x" % v for v in vals[:16])
        if len(vals) > 16:
            shown += " ..."
        print("  byte[%2d] (%2d Werte): %s%s" % (pos, len(vals), shown, tag))


def show_compare(named_paths):
    data = {}
    for name, path in named_paths:
        data[name] = extract_frames(path)
        print("== %-10s %s : %d Frames" % (name, path, len(data[name])))
    print()
    maxlen = FRAME_LEN
    print("Pro Byte-Position: Wertemenge je Aktion "
          "(* = unterscheidet die Aktionen)")
    for pos in range(maxlen):
        sets = {}
        for name, frames in data.items():
            sets[name] = sorted({f[pos] for f in frames if len(f) > pos})
        # unterscheidet sich die Wertemenge zwischen den Aktionen deutlich?
        allvals = [tuple(sets[n]) for n in sets]
        differs = len(set(allvals)) > 1
        mark = " *" if differs else "  "
        print(" byte[%2d]%s" % (pos, mark))
        for name in sets:
            vals = sets[name]
            shown = " ".join("%02x" % v for v in vals[:12])
            if len(vals) > 12:
                shown += " ..."
            print("          %-10s (%2d): %s" % (name, len(vals), shown))


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    if "=" in args[0]:
        named = []
        for a in args:
            name, _, path = a.partition("=")
            named.append((name, path))
        show_compare(named)
    else:
        show_single(args[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
