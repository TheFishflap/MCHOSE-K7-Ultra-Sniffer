#!/usr/bin/env python3
"""
guided.py - gefuehrter Live-Monitor fuer den mouse-sniffer Kanalscanner.

Oeffnet ein eigenes Konsolenfenster, fuehrt dich durch abwechselnde Phasen
    Phase 1: RUHE    -> Maus NICHT anfassen (misst das Umgebungsrauschen)
    Phase 2: BEWEGEN -> Maus staendig bewegen (zeigt die Maus-Kanaele)
und zeigt dabei live pro 2.4-GHz-Kanal den RSSI. Am Ende (Strg-C) wird
klassifiziert, welche Kanaele NUR beim Bewegen aktiv waren = Maus, und
welche dauernd da sind = Umgebung (WLAN/BLE).

WICHTIG: RSSI zeigt nur WELCHE Frequenz aktiv ist und WANN - nicht den
Paket-Inhalt. X-Y vs. Taste vs. Scroll ist daraus NICHT trennbar; dafuer
kommt spaeter der Promiscuous-Mitschnitt.

Zeilenformat der Firmware (src/main.c):
    CH 5 (2405 MHz): -60 dBm  <-- Aktivitaet

Aufruf:
    python guided.py --port auto --ruhe 8 --move 8
"""
import argparse
import re
import sys
import time
from collections import defaultdict

import serial
import serial.tools.list_ports

try:
    import winsound  # nur Windows; fuer Piep beim Phasenwechsel
except Exception:
    winsound = None

LINE_RE = re.compile(r"CH\s*(\d+)\s*\(\s*(\d+)\s*MHz\)\s*:\s*(-?\d+)\s*dBm")

RSSI_FLOOR = -90
RSSI_CEIL = -20
HOT_DBM = -70
# ein Kanal zaehlt in einer Phase als "aktiv", wenn er mind. so oft getroffen wird
MIN_HITS_FOR_ACTIVE = 2


def find_port(preferred):
    ports = list(serial.tools.list_ports.comports())
    names = [p.device for p in ports]
    if preferred != "auto" and preferred in names:
        return preferred
    for p in ports:
        d = ((p.description or "") + " " + (p.manufacturer or "")).lower()
        if any(k in d for k in ("usb", "seriell", "serial", "cdc", "xiao")):
            return p.device
    return ports[0].device if ports else None


def beep(freq, ms):
    if winsound:
        try:
            winsound.Beep(freq, ms)
        except Exception:
            pass


def clear():
    sys.stdout.write("\x1b[H\x1b[2J")


def bar(dbm, width=30):
    if dbm is None:
        return " " * width
    frac = (dbm - RSSI_FLOOR) / (RSSI_CEIL - RSSI_FLOOR)
    frac = max(0.0, min(1.0, frac))
    n = int(round(frac * width))
    return "#" * n + "-" * (width - n)


def open_port(preferred, baud, retry_s):
    deadline = time.time() + retry_s
    while True:
        cand = find_port(preferred)
        try:
            if cand is None:
                raise serial.SerialException("kein Port")
            s = serial.Serial(cand, baud, timeout=0.1)
            return s, cand
        except serial.SerialException:
            clear()
            rem = max(0, int(deadline - time.time()))
            print("=" * 60)
            print("  WARTE AUF SERIELLEN PORT ...")
            print("=" * 60)
            print()
            print("  COM-Port ist noch belegt (z.B. nRF-Serial-Terminal).")
            print("  --> COM5 in VS Code trennen ODER USB-Kabel des XIAO")
            print("      kurz abziehen und wieder einstecken.")
            print()
            print("  Greife den Port automatisch, sobald er frei ist.")
            print("  Abbruch in ~%ds, falls nichts passiert." % rem)
            sys.stdout.flush()
            if time.time() >= deadline:
                return None, cand
            time.sleep(0.4)


def render(phase_name, color, secs_left, channels, cyc, seen_ruhe, seen_move):
    now = time.time()
    clear()
    banner = {
        "RUHE": "  PHASE 1:  R U H E   -   Maus NICHT anfassen",
        "BEWEGEN": "  PHASE 2:  B E W E G E N   -   Maus staendig bewegen!",
        "BEREIT": "  GLEICH GEHT'S LOS ...",
    }[phase_name]
    line = "#" * 60
    print(line)
    print(banner)
    print("  noch %4.1f s   |   Zyklus %d   |   Strg-C = Ende + Auswertung"
          % (secs_left, cyc))
    print(line)
    print("  CH   MHz   RSSI  Spektrum")
    any_act = False
    for ch in range(0, 80):
        st = channels[ch]
        cur = st["last"]
        if cur is not None and (now - st["t"]) > 0.8:
            cur = None
        if cur is None:
            continue
        any_act = True
        hot = " *" if cur >= HOT_DBM else "  "
        print("  %2d  %4d  %4d%s %s" % (ch, 2400 + ch, cur, hot, bar(cur)))
    if not any_act:
        print("  (gerade kein Kanal ueber dem Firmware-Schwellwert)")
    print()
    # Zwischenstand Klassifikation
    mouse = sorted(c for c in seen_move if seen_move[c] >= MIN_HITS_FOR_ACTIVE
                   and seen_ruhe.get(c, 0) < MIN_HITS_FOR_ACTIVE)
    amb = sorted(c for c in seen_ruhe if seen_ruhe[c] >= MIN_HITS_FOR_ACTIVE)
    print("  Zwischenstand:")
    print("   Umgebung (auch in Ruhe aktiv): %s"
          % (", ".join("CH%d" % c for c in amb) or "-"))
    print("   NUR beim Bewegen (= Maus?):    %s"
          % (", ".join("CH%d(%dMHz)" % (c, 2400 + c) for c in mouse) or "-"))
    sys.stdout.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="auto")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--ruhe", type=float, default=8.0, help="Sekunden Phase 1")
    ap.add_argument("--move", type=float, default=8.0, help="Sekunden Phase 2")
    ap.add_argument("--open-retry", type=float, default=45.0)
    ap.add_argument("--log", default=None)
    args = ap.parse_args()

    ser, port = open_port(args.port, args.baud, args.open_retry)
    if ser is None:
        print("\nPort blieb belegt - abgebrochen.", file=sys.stderr)
        return 2

    logpath = args.log or ("tools/guided_%s.log" % time.strftime("%Y%m%d_%H%M%S"))
    logf = open(logpath, "w", encoding="utf-8")
    logf.write("# guided %s port %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), port))

    channels = defaultdict(lambda: {"last": None, "t": 0.0})
    seen_ruhe = defaultdict(int)
    seen_move = defaultdict(int)

    # Ablauf: kurz BEREIT, dann endlos RUHE/BEWEGEN abwechselnd.
    schedule = [("BEREIT", 3.0)]
    buf = b""
    cyc = 0

    def pump():
        """liest seriell, aktualisiert channels, gibt Liste frischer CH-Treffer."""
        nonlocal buf
        hits = []
        chunk = ser.read(256)
        if chunk:
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                s = raw.decode("utf-8", "replace").rstrip("\r")
                if not s:
                    continue
                logf.write("%10.3f  %s\n" % (time.time(), s))
                m = LINE_RE.search(s)
                if m:
                    ch = int(m.group(1)); dbm = int(m.group(3))
                    channels[ch]["last"] = dbm
                    channels[ch]["t"] = time.time()
                    hits.append(ch)
            logf.flush()
        return hits

    try:
        phase_idx = 0
        while True:
            if phase_idx < len(schedule):
                phase, dur = schedule[phase_idx]
                phase_idx += 1
            else:
                # endlose Abwechslung
                if (phase_idx - len(schedule)) % 2 == 0:
                    phase, dur = "RUHE", args.ruhe
                else:
                    phase, dur = "BEWEGEN", args.move
                    cyc += 1
                phase_idx += 1

            if phase == "RUHE":
                beep(500, 150)
            elif phase == "BEWEGEN":
                beep(1200, 150); beep(1200, 150)

            end = time.time() + dur
            last_r = 0.0
            while time.time() < end:
                hits = pump()
                for ch in hits:
                    if phase == "RUHE":
                        seen_ruhe[ch] += 1
                    elif phase == "BEWEGEN":
                        seen_move[ch] += 1
                now = time.time()
                if now - last_r >= 0.2:
                    render(phase, None, end - now, channels, max(cyc, 1),
                           seen_ruhe, seen_move)
                    last_r = now
    except KeyboardInterrupt:
        pass
    finally:
        try:
            ser.close()
        except Exception:
            pass
        logf.close()

    clear()
    mouse = sorted(c for c in seen_move if seen_move[c] >= MIN_HITS_FOR_ACTIVE
                   and seen_ruhe.get(c, 0) < MIN_HITS_FOR_ACTIVE)
    amb = sorted(c for c in seen_ruhe if seen_ruhe[c] >= MIN_HITS_FOR_ACTIVE)
    print("=" * 60)
    print("  AUSWERTUNG")
    print("=" * 60)
    print("  Umgebung (auch in Ruhe aktiv):")
    for c in amb:
        print("    CH%-2d %4d MHz   (Ruhe-Treffer: %d)"
              % (c, 2400 + c, seen_ruhe[c]))
    if not amb:
        print("    - keine -")
    print()
    print("  NUR beim Bewegen aktiv  = Kandidat MAUS:")
    for c in mouse:
        print("    CH%-2d %4d MHz   (Move-Treffer: %d)"
              % (c, 2400 + c, seen_move[c]))
    if not mouse:
        print("    - keine eindeutigen -")
    print()
    print("  Log: %s" % logpath)
    print("  (Fenster bleibt offen - mit Enter schliessen)")
    try:
        input()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
