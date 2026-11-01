# mouse-sniffer

Reverse-engineering project: understanding the 2.4 GHz radio link of the
MCHOSE K7 Ultra (Realtek "TOPSPEED Wireless"), with the goal of later
injecting individual mouse-movement packets (a mouse mover) without
disturbing normal mouse operation. Private learning project, in the spirit
of Bastille's MouseJack research.

## Hardware

- 2x Seeed XIAO nRF52840 Plus
  - Board 1 ("white cable"): sniffer
  - Board 2 ("black cable"): second sniffer (doubles the capture rate),
    possibly an injector later
- Both connected over USB-C (UF2 bootloader)

## Status

- [x] Project scaffold
- [x] nRF Connect SDK toolchain installed (NCS v3.4.1)
- [x] Board flashed, channel scanner runs, RSSI output readable
- [x] Mouse activity channel identified: **2450 MHz (CH50)**
- [x] Modulation determined: **2 MBit GFSK** (Nordic-compatible)
- [x] Sync / address word found: **`52 b1 5a db`**
- [x] Radio chip identified (very likely): **XN297 / XN297L clone**
- [~] Packet format: frame recognized, **payload is XN297-scrambled**;
      scramble table known and verified, fields not yet decoded (too few /
      coarsely demodulated frames; see below)
- [ ] Board 2: transmit a packet (on hold)

## Key results (as of 2026-11-01)

| Property          | Value / finding                                          |
|-------------------|----------------------------------------------------------|
| Channel           | **2450 MHz** (CH50), sidebands on CH49/51                |
| Modulation        | **Nordic 2 MBit** GFSK (`NRF_RADIO_MODE_NRF_2MBIT`)      |
| Sync / address    | **`52 b1 5a db`** (constant across all strong frames)   |
| Frame layout      | `52 b1 5a db | ?? | 5c/dc | ac | payload...`              |
| Radio chip        | likely **XN297 / XN297L** clone (not a real Nordic part) |
| Payload           | **XN297 scramble** (LFSR x^7+x^3+1, seed 0x71); table known|
| RSSI near mouse   | about -38 to -60 dBm (noise / ambient: -85 to -98 dBm)   |

### What blocks it, and why

1. **No nRF hardware address lock.** Across many variants (3- and 4-byte
   address, several bit offsets, both prefix/base register conventions) the
   RADIO never locked byte-exact onto the packets. The Realtek link is not
   cleanly Nordic-ESB compatible (preamble / framing / timing). Only
   pseudo-promiscuous (sync `0xAAAAAA`, CRC off) yields frames, and only a
   fraction of the packets (roughly 0.5 to 1 frame/s).

2. **Payload is XN297-scrambled.** Research points strongly to an
   XN297 / XN297L clone (instead of a real Nordic chip). It applies a fixed
   scramble over address plus payload: 7-bit LFSR, polynomial **x^7+x^3+1,
   seed 0x71**, output packed MSB-first, radio transmits LSB-first. The known
   scramble table (`e3 b1 4b ea ...`) was reproduced and verified from this
   exact LFSR (`tools/xn297.py`). Standard BLE whitening (x^7+x^4+1) was the
   wrong polynomial, which is why the 128-seed BLE test failed.

3. **Known-plaintext attack prepared, demod is the bottleneck.** A USB HID
   capture of the dongle (VID 0x3837, PID 0x1001) gives the cleartext; the
   8-byte report is `id=01 | buttons | X int16 LE | Y int16 LE | scroll`.
   So `keystream[i] = rf[i] XOR plaintext[i]` (the scramble is fixed).
   `tools/align.py` recovers all frames via a bit-wise sync search (the sync
   is MSB-first), and `tools/known.py` / `tools/decode.py` run the XOR. With
   46 move and 37 left-hold frames plus a majority vote, no byte or bit
   cleanly separates move from left-hold. Only byte[2] (`ac`, right after the
   sync) is about 74% stable; bytes further out decay to about 10%. That means
   the nRF52 demodulator does not match the XN297L PHY exactly (symbol timing
   drifts across the packet). The attack is correct, but it needs a clean
   XN297L demodulator. **The nRF52 line is therefore exhausted.**

### Recommended next path (platform)

The decode scheme itself is validated: `tools/decode.py` (exact goebish
scheme) produces stable descrambled constants on the clean leading bytes, so
it will work as soon as clean, byte-exact frames exist. What is missing is
receive hardware that demodulates XN297L natively.

1. **A real nRF24L01+ module** (about 2 EUR) on an MCU. goebish's XN297
   receive code runs there directly and proven; likely the fastest route to
   clean, byte-exact packets. Our `tools/` plus the verified scramble logic
   plug in immediately.
2. **SDR** (HackRF / bladeRF) plus GNU Radio for gap-free raw capture.
3. **K7 driver / dongle USB capture** (channel list, address, report layout,
   possibly CRC/PCF straight from the software).

Note on enhanced XN297: an optional PCF field of about 9 to 10 bits can sit
between address and payload, so the payload is not byte-aligned; shift by the
PCF bits before descrambling. CRC is CRC-16/CCITT over the unscrambled
address, PCF and payload (init/xorout 0xFFFF), the CRC itself sent scrambled.

## src/main.c (current state: promiscuous receiver)

`main.c` camps on 2450 MHz (2 MBit), uses pseudo-promiscuous sync
(`0xAAAAAA`, CRC off) to lock onto the preamble, and captures a large raw
window per hit (RSSI-gated so only the nearby mouse gets through). Output is
hex over USB-CDC (115200 baud). Frame alignment on `52 b1 5a db` and all
analysis happen on the host (see `tools/`). The git history documents the
path (channel scanner, then RSSI, then promiscuous, then address-lock
attempts, then raw window).

## tools/ (host analysis, Python)

Use the Python that ships with the nRF toolchain (it has `pyserial`):
`C:/ncs/toolchains/<hash>/opt/bin/python.exe`

- **`capture.py`**: timestamped capture of a COM port for a fixed duration
  into a log file. `--port auto|COMx --duration N --open-retry S`.
- **`frames.py`**: aligns logs on `52 b1 5a db`, shows payload bytes; compare
  mode `name=log.log ...` across several actions.
- **`align.py`**: bit-wise sync search (all bit offsets) that recovers every
  frame, plus the known-plaintext consistency test.
- **`known.py`**: known-plaintext test from the USB HID report format.
- **`decode.py`**: exact goebish XN297 decode (address `byte ^ scramble[i]`,
  payload `rev(byte) ^ rev(scramble[i])`) plus majority vote.
- **`xn297.py`**: builds the XN297 scramble table from the LFSR
  (x^7+x^3+1, seed 0x71) and tests descramble variants.
- **`dewhiten.py`**: 128-seed BLE whitening brute force (negative result; the
  chip is XN297, not BLE).
- **`scanmon.py` / `guided.py`**: live spectrum and guided monitor
  (idle/move phases) for the RSSI stage.

## Setup (once, locally)

1. Install **nRF Connect for VS Code** (Nordic Semiconductor).
2. Toolchain Manager, install the nRF Connect SDK (NCS v3.4.1 used here).
3. Open this folder in VS Code and add it as an application.
4. Board target: `xiao_ble/nrf52840`.
5. Build, then flash (board in bootloader mode: double-tap reset, it appears
   as the `XIAO-SENSE` USB drive, copy
   `build/mouse-sniffer/zephyr/zephyr.uf2` onto it).
6. Serial monitor / `tools/capture.py` at 115200 baud.

### Command-line build

```sh
# Toolchain environment (adjust the path to your own hash):
export ZEPHYR_BASE=C:/ncs/v3.4.1/zephyr
cmake --build build       # incremental, after editing src/main.c
```

### Flashing note

The UF2 bootloader briefly mounts a removable drive; afterwards the board
re-enumerates as a serial port. If a serial terminal is open in parallel
(for example the nRF Serial Terminal in VS Code), the COM port is locked;
disconnect it first, or briefly replug USB.

## Credits / sources

The XN297 decoding in this project builds directly on prior work from the
RC / multiprotocol community:

- **goebish**: `xn297_decod.cpp` (XN297 descrambler: address
  `byte ^ scramble[i]`, payload `bit_reverse(byte) ^ bit_reverse(scramble[i])`)
  and `XN297_emu.ino` in
  [goebish/nrf24_multipro](https://github.com/goebish/nrf24_multipro).
  Gist: https://gist.github.com/goebish/f8982353c34f2b71ffe8
  Our `tools/xn297.py` and `tools/decode.py` implement exactly this scheme.
- **XN297 scramble LFSR** (polynomial x^7+x^3+1, seed 0x71) from the
  DeviationTX / DIY-Multiprotocol-TX community
  ([pascallanger/DIY-Multiprotocol-TX-Module](https://github.com/pascallanger/DIY-Multiprotocol-TX-Module)).
- **iNav**: `nrf24_cx10.c` (`XN297_UnscramblePayload`, CRC flow) as a further
  XN297 receive reference.

Thanks to goebish and the DeviationTX / multiprotocol developers; without
their published XN297 work the decoding here would not have been possible.
