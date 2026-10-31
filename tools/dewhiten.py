#!/usr/bin/env python3
"""
dewhiten.py - BLE-Whitening-Seed per Brute-Force finden (128 Seeds).

Das nRF/BLE-Whitening ist ein 7-Bit-LFSR, Polynom x^7 + x^4 + 1, mit nur
128 moeglichen Startzustaenden. Billige 2.4-GHz-Chips (auch Realtek)
uebernehmen das oft. Wir probieren alle 128 Seeds (und beide Bit-Ordnungen)
offline durch und suchen den, der die Captures PLAUSIBEL macht.

Trennschaerfster Test: Scroll hoch vs. runter. Beim richtigen Seed muss an
EINER Byte-Position das Scroll-Byte bei "up" klein-positiv (0x01..0x0f) und
bei "down" klein-negativ (0xf1..0xff) sein - oder umgekehrt. Ein falscher
Seed trifft das praktisch nie fuer alle Frames.

Nutzung:
    python dewhiten.py up=tools/c_scrollup.log down=tools/c_scrolldown.log
"""
import re
import sys

MARKER = bytes.fromhex("52b15adb")
FRAME_LEN = 12
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


def whiten_stream(init7, n):
    """BLE-LFSR x^7+x^4+1. init7 = 7-Bit-Startzustand (0..127).
    Liefert n Whitening-Bytes (Daten werden LSB-first verarbeitet)."""
    pos = [(init7 >> k) & 1 for k in range(7)]
    out = bytearray()
    for _ in range(n):
        byte = 0
        for i in range(8):
            o = pos[6]
            byte |= o << i
            newpos = [o, pos[0], pos[1], pos[2], pos[3] ^ o, pos[4], pos[5]]
            pos = newpos
        out.append(byte)
    return out


def rev8(b):
    r = 0
    for i in range(8):
        r |= ((b >> i) & 1) << (7 - i)
    return r


def dewhiten(frame, stream, bitrev):
    if bitrev:
        return bytes(rev8(rev8(frame[i]) ^ stream[i]) for i in range(len(frame)))
    return bytes(frame[i] ^ stream[i] for i in range(len(frame)))


def small_pos(v):
    return 1 <= v <= 0x0f


def small_neg(v):
    return 0xf1 <= v <= 0xff


def main():
    args = sys.argv[1:]
    paths = {}
    for a in args:
        n, _, p = a.partition("=")
        paths[n] = p
    up = extract(paths["up"])
    down = extract(paths["down"])
    print("Frames: up=%d down=%d\n" % (len(up), len(down)))
    if not up or not down:
        print("Zu wenige Frames.")
        return 1

    best = []
    for bitrev in (False, True):
        stream = None
        for seed in range(128):
            stream = whiten_stream(seed, FRAME_LEN)
            du = [dewhiten(f, stream, bitrev) for f in up]
            dd = [dewhiten(f, stream, bitrev) for f in down]
            for pos in range(FRAME_LEN):
                uv = [f[pos] for f in du]
                dv = [f[pos] for f in dd]
                # Hypothese A: up positiv, down negativ
                a = (sum(small_pos(v) for v in uv) / len(uv)
                     + sum(small_neg(v) for v in dv) / len(dv)) / 2
                # Hypothese B: umgekehrt
                b = (sum(small_neg(v) for v in uv) / len(uv)
                     + sum(small_pos(v) for v in dv) / len(dv)) / 2
                score = max(a, b)
                best.append((score, seed, bitrev, pos,
                             "up+/down-" if a >= b else "up-/down+"))
    best.sort(reverse=True)
    print("Top-Kandidaten (score 1.0 = alle Frames passen):\n")
    print("score  seed  bitrev  byte  richtung")
    for score, seed, bitrev, pos, dirn in best[:8]:
        print("  %.2f   %3d    %-5s   %2d    %s" % (score, seed, bitrev, pos, dirn))

    s, seed, bitrev, pos, dirn = best[0]
    print("\nBester Seed=%d bitrev=%s, Scroll-Byte an Position %d (%s):"
          % (seed, bitrev, pos, dirn))
    stream = whiten_stream(seed, FRAME_LEN)
    print("  up  :", " ".join("%02x" % dewhiten(f, stream, bitrev)[pos] for f in up))
    print("  down:", " ".join("%02x" % dewhiten(f, stream, bitrev)[pos] for f in down))
    print("\nKomplette dewhitente up-Frames (Seed %d):" % seed)
    for f in up[:8]:
        print("  " + " ".join("%02x" % x for x in dewhiten(f, stream, bitrev)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
