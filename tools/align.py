#!/usr/bin/env python3
"""
align.py - BIT-WEISE Sync-Suche + Known-Plaintext-Konsistenztest.

Bisher wurde der Sync 52 b1 5a db nur BYTE-aligned gesucht. Der
0xAAAAAA-Promiscuous-Lock legt Pakete aber auf beliebige Bit-Offsets ->
Frames mit Sync auf ungerader Bit-Position wurden verworfen, und die
Payload war pro Paket bit-verschoben.

Hier: in jedem Capture-Puffer den 32-Bit-Sync an JEDEM Bit-Offset suchen
(MSB-first und per-Byte bit-reversed), ab Treffer neu in Bytes zerlegen ->
alle Frames konsistent am Sync ausgerichtet. Dann der Known-Plaintext-Test:
in 'move' muss Report-ID/Buttons(=0)/Scroll(=0) jetzt KONSTANT sein.

Nutzung:
    python align.py
"""
import re
import os
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
PKT_RE = re.compile(r"PKT[^:]*:\s*((?:[0-9a-f]{2}\s*)+)", re.I)
FRAME_LEN = 14


def rev8(b):
    r = 0
    for i in range(8):
        r |= ((b >> i) & 1) << (7 - i)
    return r


def bits_of(data):
    return "".join("{:08b}".format(b) for b in data)


def bytes_from_bits(s):
    return bytes(int(s[i:i + 8], 2) for i in range(0, len(s) - 7, 8))


SYNC_MSB = bits_of(bytes.fromhex("52b15adb"))
SYNC_REV = bits_of(bytes(rev8(b) for b in bytes.fromhex("52b15adb")))  # 4a8d5abd


def extract_bitaligned(name):
    """Alle Frames: 32-Bit-Sync an jedem Bit-Offset suchen, Payload danach
    byte-weise rekonstruieren. Gibt (frames_msb, frames_rev)."""
    path = os.path.join(HERE, name)
    out = {"msb": [], "rev": []}
    for line in open(path, encoding="utf-8", errors="replace"):
        m = PKT_RE.search(line)
        if not m:
            continue
        data = bytes.fromhex(m.group(1).replace(" ", ""))
        bs = bits_of(data)
        for tag, sync in (("msb", SYNC_MSB), ("rev", SYNC_REV)):
            start = 0
            while True:
                j = bs.find(sync, start)
                if j < 0:
                    break
                payload_bits = bs[j + 32: j + 32 + FRAME_LEN * 8]
                if len(payload_bits) >= FRAME_LEN * 8:
                    out[tag].append(bytes_from_bits(payload_bits))
                start = j + 1
    return out


def most_common(frames, pos):
    c = Counter(f[pos] for f in frames)
    val, cnt = c.most_common(1)[0]
    return val, cnt / len(frames)


def popcount(x):
    return bin(x).count("1")


def analyze(tag, move, lhold, up, down):
    print("\n========== Variante: %s ==========" % tag)
    print("Frames: move=%d lhold=%d up=%d down=%d"
          % (len(move), len(lhold), len(up), len(down)))
    if not move or not lhold:
        print("zu wenige Frames.")
        return
    consts = [p for p in range(FRAME_LEN) if most_common(move, p)[1] >= 0.8]
    print("Konstante move-Bytes (>=80%%):",
          consts if consts else "KEINE")
    print("pos  move        lhold       xor bits   up          down")
    for pos in range(FRAME_LEN):
        mv, mc = most_common(move, pos)
        lv, lc = most_common(lhold, pos)
        uv, uc = most_common(up, pos) if up else (0, 0)
        dv, dc = most_common(down, pos) if down else (0, 0)
        x = mv ^ lv
        tag2 = ""
        if mc >= 0.8 and lc >= 0.8 and popcount(x) == 1:
            tag2 = " <- BUTTON?"
        if mc >= 0.8 and uc >= 0.8 and dc >= 0.8 and len({mv, uv, dv}) >= 2:
            tag2 += " <- SCROLL?" if "0x%02x" % mv else ""
        print("  %2d 0x%02x(%3.0f%%) 0x%02x(%3.0f%%) %02x %d   0x%02x(%3.0f%%) 0x%02x(%3.0f%%)%s"
              % (pos, mv, mc*100, lv, lc*100, x, popcount(x),
                 uv, uc*100, dv, dc*100, tag2))


def main():
    names = {"move": "c_move.log", "lhold": "c_lhold.log",
             "up": "c_scrollup.log", "down": "c_scrolldown.log"}
    data = {k: extract_bitaligned(v) for k, v in names.items()}
    for tag in ("msb", "rev"):
        analyze(tag,
                data["move"][tag], data["lhold"][tag],
                data["up"][tag], data["down"][tag])


if __name__ == "__main__":
    main()
