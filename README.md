# mouse-sniffer

Reverse-Engineering-Projekt: 2,4-GHz-Funkstrecke der MCHOSE K7 Ultra (Realtek
"TOPSPEED Wireless") verstehen, mit dem Ziel, später gezielt einzelne
Mausbewegungs-Pakete einzuspeisen (Mouse-Mover), ohne die normale
Mausfunktion zu stören. Privates Lernprojekt, vergleichbar mit der
MouseJack-Forschung von Bastille.

## Hardware

- 2x Seeed XIAO nRF52840 Plus
  - Board 1 ("Kabel weiss"): Sniffer
  - Board 2 ("Kabel schwarz"): zweiter Sniffer (verdoppelt die Fangrate),
    später ggf. Injektor
- Beide per USB-C am Rechner (UF2-Bootloader)

## Status

- [x] Projektgerüst angelegt
- [x] nRF Connect SDK Toolchain installiert (NCS v3.4.1)
- [x] Board geflasht, Kanalscanner läuft, RSSI-Ausgabe lesbar
- [x] Aktivitätskanal der Maus identifiziert: **2450 MHz (CH50)**
- [x] Modulation bestimmt: **2 MBit GFSK** (Nordic-kompatibel)
- [x] Sync-/Adresswort gefunden: **`52 b1 5a db`**
- [~] Paketformat: Rahmen erkannt, **Payload aber verwürfelt (Whitening)** —
      X-Y/Tasten/Scroll nicht als Werte decodierbar (siehe unten)
- [ ] Board 2: eigenes Paket senden (zurückgestellt)

## Zentrale Ergebnisse (Stand 2026-10-31)

| Eigenschaft        | Wert / Befund                                            |
|--------------------|----------------------------------------------------------|
| Kanal              | **2450 MHz** (CH50), Nebenbänder auf CH49/51             |
| Modulation         | **Nordic 2 MBit** GFSK (`NRF_RADIO_MODE_NRF_2MBIT`)      |
| Sync-/Adresswort   | **`52 b1 5a db`** (in allen starken Frames konstant)     |
| Frame-Struktur     | `52 b1 5a db | ?? | 5c/dc | ac | payload…`                |
| Payload            | **hochentropisch → Whitening/Scrambling** (nicht lesbar) |
| RSSI nahe Maus     | ca. −38…−60 dBm (Rauschen/Umgebung: −85…−98 dBm)         |

### Was blockiert — und warum

1. **Kein nRF-Hardware-Adress-Lock.** Über viele Varianten (3-/4-Byte-Adresse,
   mehrere Bit-Offsets, beide Prefix/Base-Konventionen) rastete die RADIO
   **nie** byte-genau auf die Pakete ein. Die Realtek-Funkstrecke ist nicht
   sauber Nordic-ESB-kompatibel (Preamble/Framing/Timing). Nur
   **Pseudo-Promiscuous** (Sync `0xAAAAAA`, CRC aus) liefert Frames — aber nur
   einen Bruchteil der Pakete (~0,5–1 Frame/s).

2. **Payload ist verwürfelt (Whitening).** Hinter dem konstanten `52 b1 5a db`
   wirkt jedes Byte nahezu zufällig. Getestet wurde die Hypothese, dass das
   Standard-**BLE-Whitening** (7-Bit-LFSR, Polynom x⁷+x⁴+1) verwendet wird:
   Brute-Force über **alle 128 Seeds** und beide Bit-Ordnungen, mit einem
   trennscharfen Scroll-hoch/runter-Test — **negativ** (bester Score 0,32).
   Also kein Standard-BLE-Whitening, oder mit der niedrigen Fangrate nicht
   knackbar.

3. **Fangrate zu niedrig**, um Tasten/Scroll statistisch zu trennen (selbst
   mit beiden Boards). Schwache Leads (nicht belastbar): linke Taste evtl. um
   Bit `0.0`, Scroll evtl. um byte[9/10] der Payload.

### Nächster Schritt (anderer Weg)

Vollständiges Decodieren ist mit nRF-Promiscuous nicht erreichbar (Fangrate +
unbekanntes Whitening). Der realistische nächste Schritt ist ein Plattform-
wechsel: **SDR (HackRF/bladeRF) + GNU Radio** für lückenlose, beliebig lange
Rohaufnahmen auf 2450 MHz. Dann Whitening offline an großen Paketmengen
reversen. Alternativ hilft der **Treiber/die Software der K7** (enthält oft
Kanal-/Paketlogik) oder ein USB-Mitschnitt des originalen Dongles.

## src/main.c — aktueller Stand: Promiscuous-Empfänger

`main.c` campt fest auf 2450 MHz (2 MBit), rastet per Pseudo-Promiscuous
(`0xAAAAAA`, CRC aus) auf die Preamble ein und schneidet pro Treffer ein
großes Rohfenster mit (RSSI-gefiltert, damit nur die nahe Maus durchkommt).
Ausgabe als Hex über USB-CDC (115200 Baud). Die Frame-Ausrichtung auf
`52 b1 5a db` und alle Auswertung passiert am Rechner (siehe `tools/`).

Die Git-Historie bzw. die Iterations-Kommentare dokumentieren den Weg
(Kanalscanner → RSSI → Promiscuous → Adress-Lock-Versuche → Raw-Fenster).

## tools/ — Host-Auswertung (Python)

Python der nRF-Toolchain nutzen (hat `pyserial`):
`C:/ncs/toolchains/<hash>/opt/bin/python.exe`

- **`capture.py`** — zeitgestempelter Mitschnitt eines COM-Ports für feste
  Dauer in ein Logfile. `--port auto|COMx --duration N --open-retry S`.
- **`frames.py`** — richtet Logs auf `52 b1 5a db` aus, zeigt Payload-Bytes;
  Vergleichsmodus `name=log.log …` über mehrere Aktionen.
- **`bits.py`** — bit-weiser Differenzvergleich der Aktionen (Whitening kürzt
  sich im Vergleich weg → Tasten-Bits suchen).
- **`dewhiten.py`** — Brute-Force über 128 BLE-Whitening-Seeds (Scroll-Test).
- **`scanmon.py` / `guided.py`** — Live-Spektrum bzw. geführter Monitor
  (Phasen Ruhe/Bewegen) für die RSSI-Phase.

## Setup (einmalig, lokal)

1. **nRF Connect for VS Code** (Nordic Semiconductor) installieren.
2. Toolchain Manager → nRF Connect SDK (NCS v3.4.1 hier verwendet).
3. Ordner in VS Code öffnen, als Application hinzufügen.
4. Board-Target: `xiao_ble/nrf52840`.
5. Build → Flash (Board im Bootloader-Modus: Reset doppelt drücken →
   USB-Laufwerk `XIAO-SENSE` → `build/mouse-sniffer/zephyr/zephyr.uf2`
   darauf kopieren).
6. Seriellen Monitor / `tools/capture.py` auf 115200 Baud.

### Build von der Kommandozeile

```sh
# Toolchain-Umgebung (Pfade ggf. an eigenen Hash anpassen):
export ZEPHYR_BASE=C:/ncs/v3.4.1/zephyr
cmake --build build       # inkrementell, nach Änderung in src/main.c
```

### Hinweis Flashen

Der UF2-Bootloader belegt kurz ein Wechsellaufwerk; danach meldet sich das
Board wieder als serieller Port. Läuft parallel ein serielles Terminal
(z. B. nRF Serial Terminal in VS Code), ist der COM-Port blockiert — vorher
trennen oder USB kurz neu stecken.
