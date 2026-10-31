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
- [x] Funkchip identifiziert (sehr wahrscheinlich): **XN297/XN297L-Clone**
- [~] Paketformat: Rahmen erkannt, **Payload mit XN297-Scramble verwürfelt** —
      Scramble-Tabelle bekannt/verifiziert, Felder aber noch nicht decodiert
      (zu wenige/grob demodulierte Frames; siehe unten)
- [ ] Board 2: eigenes Paket senden (zurückgestellt)

## Zentrale Ergebnisse (Stand 2026-10-31)

| Eigenschaft        | Wert / Befund                                            |
|--------------------|----------------------------------------------------------|
| Kanal              | **2450 MHz** (CH50), Nebenbänder auf CH49/51             |
| Modulation         | **Nordic 2 MBit** GFSK (`NRF_RADIO_MODE_NRF_2MBIT`)      |
| Sync-/Adresswort   | **`52 b1 5a db`** (in allen starken Frames konstant)     |
| Frame-Struktur     | `52 b1 5a db | ?? | 5c/dc | ac | payload…`                |
| Funkchip           | wahrscheinlich **XN297/XN297L**-Clone (kein echter Nordic)|
| Payload            | **XN297-Scramble** (LFSR x⁷+x³+1, Seed 0x71) — Tab. bekannt|
| RSSI nahe Maus     | ca. −38…−60 dBm (Rauschen/Umgebung: −85…−98 dBm)         |

### Was blockiert — und warum

1. **Kein nRF-Hardware-Adress-Lock.** Über viele Varianten (3-/4-Byte-Adresse,
   mehrere Bit-Offsets, beide Prefix/Base-Konventionen) rastete die RADIO
   **nie** byte-genau auf die Pakete ein. Die Realtek-Funkstrecke ist nicht
   sauber Nordic-ESB-kompatibel (Preamble/Framing/Timing). Nur
   **Pseudo-Promiscuous** (Sync `0xAAAAAA`, CRC aus) liefert Frames — aber nur
   einen Bruchteil der Pakete (~0,5–1 Frame/s).

2. **Payload ist mit XN297-Scramble verwürfelt.** Research deutet stark auf
   einen **XN297/XN297L-Clone** hin (statt echtem Nordic). Der legt ein festes
   Scrambling über Adresse + Payload: 7-Bit-LFSR, **Polynom x⁷+x³+1, Seed
   0x71**, Ausgabe MSB-first gepackt, Funk sendet LSB-first. Die bekannte
   Scramble-Tabelle (`e3 b1 4b ea …`) wurde aus genau diesem LFSR
   reproduziert/verifiziert (`tools/xn297.py`). Das Standard-**BLE-Whitening**
   (x⁷+x⁴+1) war folglich der falsche Polynom → der 128-Seed-Test schlug fehl.

3. **Fangrate zu niedrig / Demod grob.** Das Pseudo-Promiscuous fängt den
   XN297 nur grob (~0,5–1 Frame/s, teils bit-verschoben), daher ist das
   Descramblen auf den vorhandenen Frames noch nicht sauber (Scroll-Vorzeichen
   nicht eindeutig). Schwache Leads: linke Taste evtl. um Bit `0.0`, Scroll
   evtl. um byte[9/10].

### Nächster Schritt: echter XN297-Empfang (Adress-Trick)

Host-seitiges Descramblen der Promiscuous-Captures scheitert, weil jedes
Paket mit leicht anderer Bit-Phase gefangen wird (der `0xAAAAAA`-Lock ist
nicht byte-genau). Lösung ist die **Hardware-Reception** (gelöst in
DeviationTX / Multiprotocol / goebish `XN297_emu.ino`, iNav `nrf24_cx10.c`):

- **Adresse:** echte XN297-Adresse byte-für-byte mit `xn297_scramble` XOR-en
  und **bit-reversen**, das Ergebnis als nRF-RX-Adresse setzen. Der
  HW-Korrelator rastet dann auf den rohen gescrambelten Bitstream ein →
  **jedes** Paket, byte-genau.
- **Preamble:** 0x55 bzw. 0xAA je nach erstem Adressbit; Auto-Ack aus.
- **Payload descramblen:** `rev(byte) ^ rev(xn297_scramble[i])`
  (= `tools/xn297.py` Mode 4), Tabelle aus LFSR x⁷+x³+1 / Seed 0x71.
- **Achtung PCF:** „enhanced" XN297 hat ein ~9–10-Bit-PCF zwischen Adresse
  und Payload → Payload ist **nicht byte-aligned**, vor dem Descramble um die
  PCF-Bits shiften.
- **CRC:** CRC-16/CCITT über entscrambelte Adresse+PCF+Payload, Init/XorOut
  0xFFFF, CRC selbst gescrambelt gesendet.

**Versucht (Iteration 11, negativ):** der XN297-Adress-Trick auf dem
nRF52840 — vorgescrambelte/bit-gespiegelte Adresse als RX-Adresse, 8
Varianten (gespiegelt/ungespiegelt × Offset × Registerkonvention). **0
Treffer.** Zusammen mit Iter 5/6/7/9 steht fest: die **nRF52840-RADIO rastet
den XN297-Bitstream hardwareseitig nicht ein** — der goebish-Trick ist für
einen echten **nRF24L01+** erprobt, und der nRF52840-"2MBit"-Modus ist dafuer
offenbar nicht ausreichend bit-/preamble-kompatibel (via Zephyr-HAL).

**Empfohlener nächster Weg (Plattform):**
1. **Echtes nRF24L01+-Modul** (~2 €) an einem MCU — hier läuft goebishs
   XN297-Empfangscode direkt und erprobt. Wahrscheinlich der schnellste Weg
   zu sauberen, byte-genauen Paketen.
2. **SDR** (HackRF/bladeRF) + GNU Radio für lückenlose Rohaufnahmen.
3. **K7-Treiber/Dongle-USB-Mitschnitt** (Kanalliste, Adresse, Report-Layout,
   evtl. CRC/PCF direkt aus der Software).

Die Analyse-Tools (`tools/`) und die verifizierte Scramble-/Descramble-Logik
(`xn297.py`) sind plattformunabhängig und direkt weiterverwendbar, sobald
saubere Pakete vorliegen.

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
- **`dewhiten.py`** — Brute-Force über 128 BLE-Whitening-Seeds (Scroll-Test;
  negativ — es ist XN297, nicht BLE).
- **`xn297.py`** — erzeugt die XN297-Scramble-Tabelle aus dem LFSR
  (x⁷+x³+1, Seed 0x71) und testet Descramble-Varianten an den Captures.
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
