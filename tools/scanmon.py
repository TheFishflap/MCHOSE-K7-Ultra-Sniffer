#!/usr/bin/env python3
"""
scanmon.py - Live-Spektrum-Monitor fuer den mouse-sniffer Kanalscanner.

Liest die serielle Ausgabe von Board 1 (Seeed XIAO nRF52840) und stellt
pro 2.4-GHz-Kanal den RSSI-Pegel und die Aktivitaetsrate live dar. Damit
laesst sich sehen, welche Frequenzen die Maus nutzt und wann sie sendet.

Erwartetes Zeilenformat der Firmware (src/main.c):
    CH 5 (2405 MHz): -60 dBm  <-- Aktivitaet

WICHTIG: RSSI zeigt nur WELCHE Kanaele aktiv sind und das Timing/Hopping.
Ob ein Paket X-Y-Bewegung, Taste 1-5 oder Scroll ist, steckt im Paket-
INHALT - das sieht dieser Monitor (noch) nicht. Dafuer braucht es die
Promiscuous-Capture-Firmware als naechsten Schritt.

Bedienung:
    - Laeuft, bis Strg-C.
    - Zeichnet ein Balken-Spektrum (aktueller RSSI + Peak-Hold) pro Kanal.
    - Schreibt alle Roh-Zeilen zusaetzlich mit Zeitstempel in ein Logfile,
      damit du "jetzt bewege ich die Maus" spaeter mit den Kanaelen
      korrelieren kannst. Setze mit --mark-key einen manuellen Marker.

Aufruf (Python der nRF-Toolchain, hat pyserial dabei):
    C:/ncs/toolchains/4f5b6ad6dd/opt/bin/python.exe tools/scanmon.py --port COM5
"""

import argparse
import os
import re
import sys
import time
from collections import defaultdict

import serial
import serial.tools.list_ports

# "  CH 5 (2405 MHz): -60 dBm  <-- Aktivitaet"
LINE_RE = re.compile(r"CH\s*(\d+)\s*\(\s*(\d+)\s*MHz\)\s*:\s*(-?\d+)\s*dBm")

CH_FIRST = 0
CH_LAST = 79
N_CH = CH_LAST - CH_FIRST + 1

# RSSI-Bereich fuer die Balkenskalierung (dBm). -90 = Rauschen, -20 = sehr stark.
RSSI_FLOOR = -90
RSSI_CEIL = -20

# Pegel, ab dem der Balken hervorgehoben wird (Kanal gilt als "heiss").
HOT_DBM = -70

# Peak-Hold verblasst nach so vielen Sekunden ohne neuen Treffer.
PEAK_DECAY_S = 3.0
# Aktivitaetsrate wird ueber dieses Fenster gemittelt.
RATE_WINDOW_S = 2.0


def pick_port(preferred):
    ports = list(serial.tools.list_ports.comports())
    if preferred:
        return preferred
    if not ports:
        return None
    # XIAO/nRF bevorzugen, sonst erster Port.
    for p in ports:
        desc = (p.description or "").lower()
        if "usb" in desc or "serial" in desc or "cdc" in desc:
            return p.device
    return ports[0].device


class ChannelState:
    __slots__ = ("last_dbm", "last_t", "peak_dbm", "peak_t", "hits")

    def __init__(self):
        self.last_dbm = None
        self.last_t = 0.0
        self.peak_dbm = None
        self.peak_t = 0.0
        self.hits = []  # Zeitstempel der letzten Treffer (fuer Rate)


def bar(dbm, width=28):
    """RSSI -> Balken-String."""
    if dbm is None:
        return " " * width
    frac = (dbm - RSSI_FLOOR) / (RSSI_CEIL - RSSI_FLOOR)
    frac = max(0.0, min(1.0, frac))
    n = int(round(frac * width))
    return "#" * n + "-" * (width - n)


def clear_screen():
    # ANSI: Cursor nach oben links, Bildschirm loeschen.
    sys.stdout.write("\x1b[H\x1b[2J")


def render(channels, started, total_lines, logpath, marks):
    now = time.time()
    clear_screen()
    uptime = now - started
    print("mouse-sniffer  Live-Spektrum  (Strg-C zum Beenden)")
    print("Laufzeit: %6.1fs   Zeilen: %-7d   Log: %s" % (uptime, total_lines, logpath))
    print("RSSI-Skala: %d..%d dBm   heiss ab %d dBm   Marker gesetzt: %d"
          % (RSSI_FLOOR, RSSI_CEIL, HOT_DBM, marks))
    print("-" * 78)
    print("  CH   MHz   RSSI   Rate/s  Spektrum (akt=# peak=|)")

    any_active = False
    for ch in range(CH_FIRST, CH_LAST + 1):
        st = channels[ch]
        # Peak-Hold verblassen lassen.
        peak = st.peak_dbm
        if peak is not None and (now - st.peak_t) > PEAK_DECAY_S:
            peak = None
        # Rate ueber Fenster.
        st.hits = [t for t in st.hits if now - t <= RATE_WINDOW_S]
        rate = len(st.hits) / RATE_WINDOW_S

        cur = st.last_dbm
        if cur is not None and (now - st.last_t) > 1.0:
            cur = None  # aelter als 1s: Kanal gerade still

        if cur is None and peak is None and rate == 0:
            continue  # nie/laengst nicht gesehen -> Zeile sparen
        any_active = True

        b = list(bar(cur))
        # Peak-Markierung einzeichnen.
        if peak is not None:
            frac = (peak - RSSI_FLOOR) / (RSSI_CEIL - RSSI_FLOOR)
            frac = max(0.0, min(1.0, frac))
            idx = min(len(b) - 1, int(round(frac * len(b))))
            if b[idx] == "-":
                b[idx] = "|"
        bstr = "".join(b)

        hot = " *" if (cur is not None and cur >= HOT_DBM) else "  "
        cur_s = "%4d" % cur if cur is not None else "   ."
        print("  %2d  %4d  %s%s  %5.1f   %s"
              % (ch, 2400 + ch, cur_s, hot, rate, bstr))

    if not any_active:
        print("  (noch keine Aktivitaet ueber dem Firmware-Schwellwert empfangen)")
    sys.stdout.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", help="z.B. COM5 (Default: automatisch suchen)")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--log", default=None,
                    help="Logfile (Default: tools/scan_<zeit>.log)")
    ap.add_argument("--raw", action="store_true",
                    help="nur Roh-Zeilen durchreichen, kein Spektrum")
    args = ap.parse_args()

    port = pick_port(args.port)
    if not port:
        print("Kein serieller Port gefunden. Board angeschlossen? "
              "Mit --port COMx angeben.", file=sys.stderr)
        return 2

    logpath = args.log or os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "scan_%s.log" % time.strftime("%Y%m%d_%H%M%S"))

    print("Oeffne %s @ %d ... (Log: %s)" % (port, args.baud, logpath))
    try:
        ser = serial.Serial(port, args.baud, timeout=0.2)
    except serial.SerialException as e:
        print("Konnte Port nicht oeffnen: %s" % e, file=sys.stderr)
        print("Tipp: Ist der nRF-Serial-Terminal / ein anderer Monitor noch "
              "offen? Immer nur ein Programm pro COM-Port.", file=sys.stderr)
        return 2

    channels = defaultdict(ChannelState)
    started = time.time()
    last_render = 0.0
    total_lines = 0
    marks = 0

    with open(logpath, "w", encoding="utf-8") as log:
        log.write("# mouse-sniffer scan log, Start %s, Port %s\n"
                  % (time.strftime("%Y-%m-%d %H:%M:%S"), port))
        log.flush()
        try:
            buf = b""
            while True:
                chunk = ser.read(256)
                now = time.time()
                if chunk:
                    buf += chunk
                    while b"\n" in buf:
                        raw, buf = buf.split(b"\n", 1)
                        line = raw.decode("utf-8", "replace").rstrip("\r")
                        if not line:
                            continue
                        total_lines += 1
                        ts = now - started
                        log.write("%10.3f  %s\n" % (ts, line))
                        if args.raw:
                            print("%10.3f  %s" % (ts, line))
                            continue
                        m = LINE_RE.search(line)
                        if m:
                            ch = int(m.group(1))
                            dbm = int(m.group(3))
                            st = channels[ch]
                            st.last_dbm = dbm
                            st.last_t = now
                            st.hits.append(now)
                            if st.peak_dbm is None or dbm >= st.peak_dbm:
                                st.peak_dbm = dbm
                                st.peak_t = now
                    log.flush()

                if not args.raw and (now - last_render) >= 0.25:
                    render(channels, started, total_lines, logpath, marks)
                    last_render = now
        except KeyboardInterrupt:
            print("\nBeende. Log gespeichert: %s" % logpath)
        finally:
            ser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
