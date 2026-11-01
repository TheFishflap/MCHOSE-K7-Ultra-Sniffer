#!/usr/bin/env python3
"""
xn297.py - XN297-Descrambling auf die Captures anwenden.

Quelle/Credit: goebish (xn297_decod.cpp, nrf24_multipro) und die
DeviationTX / DIY-Multiprotocol-TX-Community fuer Scramble-Tabelle,
LFSR (x^7+x^3+1, Seed 0x71) und Descramble-Schema.
  https://github.com/goebish/nrf24_multipro
  https://github.com/pascallanger/DIY-Multiprotocol-TX-Module

Laut Research ist die K7 Ultra kein echter Nordic-Chip, sondern ein
XN297(L)-Clone. Der legt ein FESTES Scrambling (bekannte Tabelle aus der
DeviationTX/Multiprotocol-Szene) ueber Adresse + Payload, und sendet
LSB-first (nRF liest MSB-first -> Byte evtl. bit-gespiegelt).

Da die Scramble-Sequenz fest ist, ist unser Marker "52 b1 5a db" die
GESCRAMBELTE Adresse; der Payload wird ab der passenden Tabellenposition
mit XOR descrambelt. Wir brute-forcen die wenigen Freiheitsgrade
(Bit-Order x Tabellen-Offset) und testen mit Scroll hoch/runter:
richtige Kombi -> Scroll-Byte up klein-positiv, down klein-negativ.

Nutzung:
    python xn297.py up=tools/c_scrollup.log down=tools/c_scrolldown.log \
                    move=tools/c_move.log
"""
import re
import sys

MARKER = bytes.fromhex("52b15adb")
FRAME_LEN = 14
PKT_RE = re.compile(r"PKT[^:]*:\s*((?:[0-9a-f]{2}\s*)+)", re.I)

def gen_xn297_scramble(n=39):
    """XN297-Scramble aus dem 7-Bit-LFSR: Polynom x^7+x^3+1, Seed 0x71,
    Feedback = MSB(Bit6) XOR Bit2, Ausgabe und Packing MSB-first.
    Reproduziert die bekannte Tabelle e3 b1 4b ea 85 ... (verifiziert)."""
    lfsr = 0x71
    out = bytearray()
    for _ in range(n):
        byte = 0
        for _ in range(8):
            msb = (lfsr >> 6) & 1
            byte = (byte << 1) | msb
            fb = msb ^ ((lfsr >> 2) & 1)
            lfsr = ((lfsr << 1) & 0x7f) | fb
        out.append(byte)
    return bytes(out)


XN297_SCRAMBLE = gen_xn297_scramble()


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


def rev8(b):
    r = 0
    for i in range(8):
        r |= ((b >> i) & 1) << (7 - i)
    return r


def descramble(frame, scram_off, mode):
    """mode: 0 raw^s, 1 rev(b)^s, 2 rev(b^s), 3 b^s dann rev,
    4 rev(b)^rev(s) (exakter goebish-Descrambler), 5 b^rev(s)."""
    out = bytearray()
    for i, b in enumerate(frame):
        s = XN297_SCRAMBLE[scram_off + i]
        if mode == 0:
            out.append(b ^ s)
        elif mode == 1:
            out.append(rev8(b) ^ s)
        elif mode == 2:
            out.append(rev8(b ^ s))
        elif mode == 3:
            out.append(rev8(rev8(b) ^ s))
        elif mode == 4:
            out.append(rev8(b) ^ rev8(s))   # goebish: bit_reverse(byte) ^ bit_reverse(scramble)
        elif mode == 5:
            out.append(b ^ rev8(s))
    return bytes(out)


def small_pos(v):
    return 1 <= v <= 0x10


def small_neg(v):
    return 0xf0 <= v <= 0xff


def main():
    paths = {}
    for a in sys.argv[1:]:
        n, _, p = a.partition("=")
        paths[n] = p
    up = extract(paths["up"])
    dn = extract(paths["down"])
    mv = extract(paths.get("move", paths["up"]))
    print("Frames: up=%d down=%d move=%d\n" % (len(up), len(dn), len(mv)))

    results = []
    for mode in range(6):
        for off in range(0, 8):  # Tabellenposition fuer frame-byte[0]
            if off + FRAME_LEN > len(XN297_SCRAMBLE):
                continue
            du = [descramble(f, off, mode) for f in up]
            dd = [descramble(f, off, mode) for f in dn]
            for pos in range(FRAME_LEN):
                uv = [f[pos] for f in du]
                dv = [f[pos] for f in dd]
                a = (sum(small_pos(v) for v in uv) / len(uv)
                     + sum(small_neg(v) for v in dv) / len(dv)) / 2
                b = (sum(small_neg(v) for v in uv) / len(uv)
                     + sum(small_pos(v) for v in dv) / len(dv)) / 2
                results.append((max(a, b), mode, off, pos,
                                "up+/down-" if a >= b else "up-/down+"))
    results.sort(reverse=True)
    print("Top-Kandidaten (1.0 = perfekt):")
    print("score  mode  off  byte  richtung")
    for sc, mode, off, pos, d in results[:10]:
        print("  %.2f    %d    %d   %2d   %s" % (sc, mode, off, pos, d))

    sc, mode, off, pos, d = results[0]
    print("\nBeste Kombi: mode=%d scramble-offset=%d scroll-byte=%d (%s)"
          % (mode, off, pos, d))
    print("  up  :", " ".join("%02x" % descramble(f, off, mode)[pos] for f in up))
    print("  down:", " ".join("%02x" % descramble(f, off, mode)[pos] for f in dn))
    print("\nDescrambelte move-Frames (mode=%d off=%d):" % (mode, off))
    for f in mv[:10]:
        print("  " + " ".join("%02x" % x for x in descramble(f, off, mode)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
