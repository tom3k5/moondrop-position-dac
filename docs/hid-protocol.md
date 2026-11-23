# MOONDROP Position HID Protocol (`35d8:0123`)

This document describes the DSP/EQ control channel on the MOONDROP:Gravity Position USB-C DAC/AMP. Frame structures are derived from open-source implementations (see [`sources.md`](sources.md)) and verified against physical hardware (firmware `0.5`).

## 1. Transport Layer

| Item | Value |
|---|---|
| USB interface | interface 3 (`bInterfaceClass=3`, HID 1.11) |
| Device node | `/dev/hidrawN` (e.g. `input3`) or `input/by-id/usb-MOONDROP_MOONDROP_Position_<SERIAL>-if03-hidraw` |
| Report ID | **`0x4B`** (75) — 63 B payload + 1 B report ID = 64 B frame |
| Endpoints | OUT `0x05` (interrupt, 64 B), IN `0x86` (interrupt, 64 B) |
| Secondary report | `0x54` — 63 B input+output, unused by public web app (see §9) |
| Transfer mode | Interrupt report read/write (`hid_write`/`hid_read`, WebHID `sendReport`/`inputreport`); does **not** use `GET_REPORT` control transfers |

Interface 4 exposes a separate Consumer Control HID (`report 0x03`) for hardware media/volume buttons (see §8).

### Linux Discovery & Session Management

`scripts/dac_transport.py` scans sysfs without opening HID device nodes and parses report sizes directly from the HID descriptor. The device registry in `scripts/dac_devices.py` matches Position by VID/PID (`35d8:0123`) and 63-byte input/output `0x4B` reports. GUI, CLI, and `eq_fit.py --apply` share this registry. `scripts/moondrop_position.py` implements Position-specific frame encoding and DSP operations.

Sysfs presence alone does not guarantee permission; the transport verifies `/dev/hidraw*` access separately on the host or inside Flatpak. Kernel re-enumeration (even reusing `/dev/hidrawN`) invalidates any previously remembered session target. When multiple matching DACs are attached, CLI commands require `--device` (use `list` to inspect DSP nodes).

On November 23, 2026, hardware verification on Position firmware `0.5` confirmed identical slot, level, and raw 8-band coefficient readback compared to release `0.3.8`, non-flash live preview read/restore of a 1 dB band adjustment, flash write verification, skip of duplicate flash writes, and full backup restoration surviving physical replug.

## 2. Frame Layout

```
[0x4B] [OP] [CMD] [LEN] [payload ...]        (64 B total, zero-padded)
```

* `OP`: `0x01` write, `0x80` read
* `CMD`: command ID (§3)
* `LEN`: tolerated flexibly by firmware (`0x18` = 24 for EQ commands in Moondrop/devicePEQ, payload length in FreeDSP Studio; `moondrop_position.py` follows the Moondrop handler convention)
* Replies arrive as input reports on `0x4B` with `[0x80] [CMD] [...]` (after report ID).

Example — firmware version read:

```
→ 4b 80 0c 00 00 ...
← 4b 80 0c 01 30 2e 37 ...      # "0.7"
```

## 3. Commands

| CMD | Name | Dir | Payload / Response |
|---|---|---|---|
| `0x01` | `SAVE_EQ` (flash) | W | empty — commits EQ to flash |
| `0x02` | `MIC_GAIN` | R/W | int16 LE, scale `32767/15` per dB, range ±15 dB |
| `0x03` | `GLOBAL_GAIN` | R/W | 1 B signed (integer dB); read byte `p[4]` |
| `0x04` | `SAVE_OFFSET` | W | empty — commits pre-gain/offset to flash |
| `0x05` | `RESET` / memory refresh | W | `[0x05, 0x04, 0x00]` etc. (used before commit) |
| `0x09` | `EQ_UPDATE` | R/W | read/write band (§4, §5) |
| `0x0A` | `EQ_COEFF` (latch) | W | `[0x0A, idx, 0x00, 0xFF, 0xFF, 0xFF]` — latches band coefficients |
| `0x0C` | `VERSION` | R | ASCII `"x.y.z"` at `p[3..5]` |
| `0x0F` | `ACTIVE_SLOT` | R/W | read `p[3]`; write `[0x0F, slot]` (devicePEQ) or `[0x0F, 0x01, slot]` (FreeDSP) |
| `0x11` | `DAC_FILTER` | R/W | DAC filter (1..5: FAST-LL/FAST-PC/SLOW-LL/SLOW-PC/NON-OS) |
| `0x16` | `CHANNEL_BALANCE` | R/W | L/R balance (0–127) |
| `0x18` | `LED_SWITCH` | R/W | LED switch |
| `0x19` | `DAC_GAIN` | R/W | DAC gain |
| `0x1D` | `DAC_WORK_MODE` | R/W | 0 = normal, 1 = alternative |
| `0x23` | `PRE_GAIN` | R/W | int16 LE, `1/256 dB` step, range −128…0 dB |
| `0xFF` | `UPGRADE` | W | firmware upgrade mode (unused) |

Additional Walkplay commands (`0x17`, `0x25`, `0x60`, `0xD3`, `0x0D`, `0x0E`) have not been tested on Position.

## 4. Reading a Band (`CMD 0x09`)

```
→ [0x80, 0x09, 0x18, 0x00, idx, 0x00]     idx = 0..7 (or 0..9)
← [0x80, 0x09, ..., ...]
```

Reply layout (offsets in payload **excluding** report ID byte):

| Offset | Field | Encoding |
|---|---|---|
| 4 | band index | 0-based, echoed |
| 7..26 | IIR coefficients | 5 × int32 LE, Q2.30 (`b0, b1, b2, −a1, −a2`) |
| 27..28 | frequency | uint16 LE, Hz |
| 29..30 | Q | int16 LE, 8.8 fixed (`÷ 256`) |
| 31..32 | gain | int16 LE, 8.8 fixed (`÷ 256`), dB |
| 33 | filter type | 1 = LSQ, 2 = PK, 3 = HSQ, 4 = LP, 5 = HP |
| 35 | active slot | e.g. 0 or 7 |

Out-of-range frequency (outside `10..24000 Hz`) indicates an unused band or a mismatched reply.

## 5. Writing a Band (`CMD 0x09`) & Commit

Write payload (63 B):

| Offset | Field |
|---|---|
| 0 | `0x01` (OP write) |
| 1 | `0x09` |
| 2 | `0x18` |
| 3 | `0x00` |
| 4 | band index |
| 5–6 | `0x00` |
| 7..26 | 20 B coefficients (`5 × int32 LE`, Q2.30) |
| 27..28 | frequency `uint16 LE` |
| 29..30 | Q 8.8 |
| 31..32 | gain 8.8 |
| 33 | filter type |
| 34 | `0x00` |
| 35 | target slot (`7` = Custom) |

After each band write, latch it (`0x0A`) so staging registers become active:

```
→ [0x01, 0x0A, idx, 0x00, 0xFF, 0xFF, 0xFF]
```

Full bank write sequence:

1. Switch to slot Custom (`7`) if inactive (`[0x01, 0x0F, slot]`, fallback `[0x01, 0x0F, 0x01, slot]`), then confirm slot 7 via readback.
2. For each band: write `0x09` → latch `0x0A`.
3. Optionally write pre-gain: `[0x01, 0x23, 0x00, lo, hi]` (devicePEQ), fallback `[0x01, 0x23, 0x02, lo, hi]` (FreeDSP Studio), and read back.
4. For persistent writes, verify slot, bands, and confirmed pre-gain, send `[0x01, 0x01]` (`SAVE_EQ`), and verify again after flash.

After flashing, the GUI rebuilds the DSP curve from the five Q2.30 coefficients returned by `0x09` at `96 kHz` and displays the confirmed pre-gain separately. The `coefficients` field in `scripts/dsp_control.py --diagnose` prints the 20-byte `0x09` readback per band as hex strings.

Inter-frame delays: ~25 ms between bands, ~50 ms between commands, ~150 ms after slot switch, ~200 ms after flash save. Faster writes drop frames.

### Live Preview & Pre-Gain Readback

Live auditioning uses the same `0x09` / `0x0A` writes and readback checks while omitting `SAVE_EQ`. Before starting preview, the app captures the active slot, its pre-gain, and all 8 Custom bands with raw Q2.30 bytes. On exit/cancel, it restores those exact bytes, Custom pre-gain, and the prior slot/pre-gain, verifying restoration via readback.

Although transport 8.8 encodes `1/256 dB` steps, firmware `0.5` returned `−2.50 dB` when asked for `−2.6484375 dB` (`−2.65 dB` profile). During profile writes/preview, the app tries the exact 8.8 value first and accepts a confirmed nearest `0.5 dB` step if the DAC rounds it, displaying both values without altering the profile JSON.

## 6. Biquad Coefficients

DSP filters evaluate at **fixed `96 kHz`** and store **Q2.30** (`× 2³⁰`, `int32 LE`) coefficients using normalized RBJ formulas (`a0 = 1`):

```
w0 = 2π·f / 96000
PK:  A = 10^(gain/40); α = sin(w0)/(2Q)
     b = [1+αA, -2cos w0, 1-αA]
     a = [1+α/A, -2cos w0, 1-α/A]
LSQ/HSQ: A = 10^(gain/40); D = (A+1/A)(1/Q-1)+2
     for Q > 1: D = max(D, 1/Q²)
     α = sin(w0)/2 · √D; β = 2√A·α
LP/HP: α = sin(w0)/(2Q)
     b = [(1∓cos w0)/2, 1∓cos w0, (1∓cos w0)/2] / (1+α)
     a = [1, -2cos w0/(1+α), (1-α)/(1+α)]
```

Packed order: `[b0, b1, b2, −a1, −a2] / a0`, each `× 2³⁰`, `int32 LE`.

For shelves with high `Q` and large `|gain|`, clamping `D >= 1/Q²` when `Q > 1` keeps damping positive while preserving standard `Q = 0.7` coefficients. Any steep shelf whose corrected coefficients overflow Q2.30 (e.g. HSQ `1 kHz`, `+12 dB`, `Q = 10`) is rejected before touching device state.

## 7. EQ Limits (`hub.mondroplab.tech`)

Source: `hub.mondroplab.com` Custom EQ web app `1.8.0` build `26B1107` (`POSITION` config in `eqcaps`):

| Parameter | Value |
|---|---|
| Bands | 8 |
| Filter types | `PK, LPQ, HPQ` (shelves disabled in web UI, but **confirmed** on firmware `0.5`: slot 0 uses `HSQ`, slot 7 accepts/returns `LSQ` and `HSQ` with exact Q2.30 coefficients) |
| Frequency | 20–20,000 Hz, 1 Hz step |
| Gain | −18…+12 dB (`1/256 dB` wire step; web UI uses `0.1 dB`) |
| Q | `0.1015625…10` (`1/256` step; web UI uses `0.01`) |
| Pre-gain | −128…0 dB |
| Global gain | −18…0 dB, integer dB |
| Slots | 0 = Default (read-only), 7 = Custom (writable) |

## 8. Consumer Keys (Interface 4)

HID descriptor: report ID `0x03` (`0xE9` Vol+, `0xEA` Vol−, `0xCD` Play/Pause, `0xCF` Mute). Handled natively by the kernel input layer and PipeWire.

## 9. Unknown Report `0x54`

Interface 3 declares two vendor reports: `0x4B` (EQ/DSP) and `0x54` (63 B I/O). All known open-source implementations and the official web app use `0x4B` exclusively; `0x54` likely serves mobile-app-only features and is left untouched.

## 10. Implementation Pitfalls

1. **Shared `CMD 0x09`** — band read and active slot read share `0x09` with no correlation ID; flush stale input reports before sending and verify band index echo.
2. **Asynchronous replies** — filter by `payload[1] == CMD`.
3. **Timing** — respect delays in §5 or frames will drop.
4. **Flash wear** — use `--dry-run` when testing and skip redundant flash writes when state already matches.
5. **Host access** — without `udev/70-dsp-control.rules`, `/dev/hidraw*` is root-only.
