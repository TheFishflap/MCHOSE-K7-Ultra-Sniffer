#!/usr/bin/env python3
"""
capture.py - zeitgestempelte Aufnahme der Scanner-Ausgabe fuer feste Dauer.

Oeffnet den COM-Port, schreibt jede empfangene Zeile mit relativem
Zeitstempel (Sekunden seit Start) in ein Logfile und beendet sich nach
--duration Sekunden von selbst. Gedacht fuers "Variante 2"-Vorgehen:
im Hintergrund laufen lassen, waehrend eine angesagte Maus-Sequenz
durchgefuehrt wird, danach Log auswerten (tools/analyze.py).

Aufruf:
    python capture.py --port COM5 --duration 60 --log tools/sessionX.log
"""
import argparse
import sys
import time

import serial
import serial.tools.list_ports


def find_port(preferred):
    """Bevorzugten Port nehmen, falls vorhanden; sonst einen plausiblen
    USB-Serial-Port (XIAO CDC) suchen."""
    ports = list(serial.tools.list_ports.comports())
    names = [p.device for p in ports]
    if preferred in names:
        return preferred
    for p in ports:
        d = ((p.description or "") + " " + (p.manufacturer or "")).lower()
        if any(k in d for k in ("usb", "seriell", "serial", "cdc", "xiao")):
            return p.device
    return ports[0].device if ports else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--duration", type=float, default=60.0)
    ap.add_argument("--log", required=True)
    ap.add_argument("--open-retry", type=float, default=0.0,
                    help="so viele Sekunden lang versuchen, den Port zu "
                         "oeffnen, falls er noch belegt ist")
    args = ap.parse_args()

    deadline = time.time() + args.open_retry
    ser = None
    used_port = args.port
    while True:
        cand = find_port(args.port) if args.port == "auto" else args.port
        try:
            if cand is None:
                raise serial.SerialException("kein Port gefunden")
            ser = serial.Serial(cand, args.baud, timeout=0.2)
            used_port = cand
            break
        except serial.SerialException as e:
            if time.time() >= deadline:
                print("BELEGT/Fehler: %s" % e, file=sys.stderr)
                return 2
            time.sleep(0.4)
    print("Port offen: %s" % used_port)

    start = time.time()
    n = 0
    with open(args.log, "w", encoding="utf-8") as log:
        log.write("# capture start %s port %s dauer %.0fs\n"
                  % (time.strftime("%Y-%m-%d %H:%M:%S"), used_port, args.duration))
        log.flush()
        buf = b""
        while time.time() - start < args.duration:
            chunk = ser.read(256)
            if not chunk:
                continue
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                line = raw.decode("utf-8", "replace").rstrip("\r")
                if not line:
                    continue
                t = time.time() - start
                log.write("%10.4f  %s\n" % (t, line))
                n += 1
            log.flush()
    ser.close()
    print("FERTIG: %d Zeilen in %.1fs -> %s" % (n, time.time() - start, args.log))
    return 0


if __name__ == "__main__":
    sys.exit(main())
