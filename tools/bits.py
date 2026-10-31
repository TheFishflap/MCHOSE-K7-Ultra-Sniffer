#!/usr/bin/env python3
"""
bits.py - bit-weiser Differenzvergleich der Aktions-Captures.

Idee: Das BLE-artige Whitening XORt jedes Paket mit DERSELBEN festen
Sequenz (fester Kanal -> fester Seed). Vergleicht man dieselbe Bit-Position
zwischen zwei Aktionen, kuerzt sich das Whitening weg. Ein Bit, das bei
"move" konstant 0 und bei "move+linke Taste" konstant 1 ist, verraet die
linke Taste - ganz ohne Dewhitening.

Nutzung:
    python bits.py move=tools/c_move.log lhold=tools/c_lhold.log \
                    rhold=tools/c_rhold.log scrollup=tools/c_scrollup.log \
                    scrolldown=tools/c_scrolldown.log
"""
import re
import sys

MARKER = bytes.fromhex("52b15adb")
FRAME_LEN = 12  # Bytes nach dem Marker -> 96 Bitpositionen
PKT_RE = re.compile(r"PKT[^:]*:\s*((?:[0-9a-f]{2}\s*)+)", re.I)


def extract(path):
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
            pl = data[j + 4: j + 4 + FRAME_LEN]
            if len(pl) == FRAME_LEN:
                frames.append(pl)
            i = j + 1
    return frames


def bit_at(frame, pos):
    return (frame[pos // 8] >> (pos % 8)) & 1


def frac_ones(frames, pos):
    if not frames:
        return None
    return sum(bit_at(f, pos) for f in frames) / len(frames)


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    data = {}
    for a in args:
        name, _, path = a.partition("=")
        data[name] = extract(path)
    base = "move" if "move" in data else list(data)[0]

    print("Frames je Aktion:")
    for n in data:
        print("  %-11s %d" % (n, len(data[n])))
    print("\nBit-Positionen, an denen sich eine Aktion klar von '%s' abhebt." % base)
    print("(Anteil Einsen; * = Aktion fast konstant UND deutlich anders als Basis)\n")

    names = list(data)
    nbits = FRAME_LEN * 8
    header = "byte.bit  " + "".join("%-12s" % n for n in names)
    print(header)
    print("-" * len(header))
    for pos in range(nbits):
        fr = {n: frac_ones(data[n], pos) for n in names}
        b = fr[base]
        if b is None:
            continue
        # interessant, wenn eine Aktion nahe 0/1 UND >=0.6 von der Basis entfernt
        interesting = False
        for n in names:
            if n == base or fr[n] is None:
                continue
            if (fr[n] <= 0.15 or fr[n] >= 0.85) and abs(fr[n] - b) >= 0.6:
                interesting = True
        mark = " *" if interesting else "  "
        cells = ""
        for n in names:
            v = fr[n]
            cells += "%-12s" % ("%.2f" % v if v is not None else "-")
        print("  %2d.%d  %s%s" % (pos // 8, pos % 8, cells, mark))


if __name__ == "__main__":
    sys.exit(main())
