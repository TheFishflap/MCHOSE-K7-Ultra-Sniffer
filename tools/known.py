#!/usr/bin/env python3
"""
known.py - Known-Plaintext-Test auf die RF-Captures.

Der USB-HID-Mitschnitt liefert den Klartext (Report-Format der Maus:
report-id, buttons, X int16 LE, Y int16 LE, scroll). Der Scramble/Keystream
ist fest pro Byte-Position, also  keystream[i] = rf[i] XOR plaintext[i].

Bekannte Klartext-Fakten pro Capture-Bedingung:
  c_move       : buttons = 0x00, scroll = 0x0000  (X/Y variabel)
  c_lhold      : buttons = links gesetzt, scroll = 0x0000
  c_scrollup   : scroll != 0 (positiv)
  c_scrolldown : scroll != 0 (negativ)

Test: Wenn unsere RF-Frames byte-konsistent am Marker ausgerichtet sind,
muss an der Button-Byte-Position gelten:
  - c_move dort KONSTANT (= keystream, da plaintext 0)
  - c_lhold dort KONSTANT und = move-Wert XOR (einzelnes Button-Bit)
Analog unterscheiden sich scrollup/down an der Scroll-Position von move.

Ist nichts konsistent -> die Frames sind pro Paket bit-verschoben (Jitter),
dann braucht der KPA saubere, byte-genaue Frames (nRF24L01+ / zeitsync).

Nutzung:
    python known.py
"""
import re
import os
from collections import Counter

MARKER = bytes.fromhex("52b15adb")
FRAME_LEN = 14
PKT_RE = re.compile(r"PKT[^:]*:\s*((?:[0-9a-f]{2}\s*)+)", re.I)
HERE = os.path.dirname(os.path.abspath(__file__))


def extract(name):
    path = os.path.join(HERE, name)
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


def most_common(frames, pos):
    c = Counter(f[pos] for f in frames)
    val, cnt = c.most_common(1)[0]
    return val, cnt / len(frames)


def popcount(x):
    return bin(x).count("1")


def main():
    move = extract("c_move.log")
    lhold = extract("c_lhold.log")
    up = extract("c_scrollup.log")
    down = extract("c_scrolldown.log")
    print("Frames: move=%d lhold=%d up=%d down=%d\n"
          % (len(move), len(lhold), len(up), len(down)))

    print("Pro Byte-Position: wie KONSTANT ist move (= keystream, falls")
    print("Plaintext dort 0) und passt lhold als move XOR 1-Bit?\n")
    print("pos  move_val move_const  lhold_val lhold_const  xor  bits")
    for pos in range(FRAME_LEN):
        mv, mc = most_common(move, pos)
        lv, lc = most_common(lhold, pos)
        x = mv ^ lv
        tag = ""
        if mc >= 0.8 and lc >= 0.8:
            tag = "  <- beide konstant"
            if popcount(x) == 1:
                tag += " + 1-Bit-Diff = BUTTON?"
        print("  %2d    0x%02x   %4.0f%%      0x%02x   %4.0f%%     %02x   %d%s"
              % (pos, mv, mc * 100, lv, lc * 100, x, popcount(x), tag))

    print("\nScroll-Check: unterscheidet sich eine Position move<->up<->down")
    print("konstant? (scroll-Byte)\n")
    print("pos  move      up        down")
    for pos in range(FRAME_LEN):
        mv, mc = most_common(move, pos)
        uv, uc = most_common(up, pos)
        dv, dc = most_common(down, pos)
        flag = ""
        if mc >= 0.7 and uc >= 0.7 and dc >= 0.7 and len({mv, uv, dv}) == 3:
            flag = "  <- 3 versch. konstante Werte = SCROLL?"
        print("  %2d  0x%02x(%3.0f%%) 0x%02x(%3.0f%%) 0x%02x(%3.0f%%)%s"
              % (pos, mv, mc*100, uv, uc*100, dv, dc*100, flag))

    # Fazit: gibt es ueberhaupt konstante Bytes in move?
    consts = [p for p in range(FRAME_LEN) if most_common(move, p)[1] >= 0.8]
    print("\nKonstante Byte-Positionen in move (>=80%%):",
          consts if consts else "KEINE -> Frames sind pro Paket bit-verschoben")


if __name__ == "__main__":
    main()
