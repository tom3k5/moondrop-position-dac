# AutoEq & EQ Database Integration with Hardware DSP

This document describes how **autoeq.app functionality** (measurement database, target curves, parametric EQ optimizer) integrates with the **hardware DSP** of supported USB-C DACs such as MOONDROP:Gravity Position (`35d8:0123`, HID report `0x4B`). Control protocol specification: [`hid-protocol.md`](hid-protocol.md).

## 1. What AutoEq Provides and What It Does Not

[autoeq.app](https://autoeq.app) and the [AutoEq](https://github.com/jaakkopasanen/AutoEq) library (MIT) are **not** device-control software. They provide:

| Component | Purpose |
|---|---|
| measurement database (`measurements/`) | Frequency response curves from oratory1990, crinacle, Rtings, Innerfidelity, etc. |
| target database (`targets/`) | Harman in-ear 2016/2017/2019, AutoEq in-ear, JM-1, diffuse field, etc. |
| `autoeq` library (PyPI 4.1.2) | CSV loading, interpolation, centering, target compensation, smoothing, gain limiting, **parametric EQ optimizer** (`PEQ_CONFIGS`, `optimize_parametric_eq`) |
| autoeq.app (web) | Model/target picker UI, custom measurement upload, Equalizer APO / Wavelet export; FastAPI backend (`webapp/main.py`, `POST /equalize`) |
| pre-computed results (`results/`) | Ready-made `ParametricEQ.txt` / `GraphicEQ.txt` files |

**What is missing:** AutoEq does not speak the HID `0x4B` protocol and cannot write to the DAC. That layer is implemented in this project.

Note on MOONDROP Position: **Moondrop Position does not yet have a third-party measurement in the AutoEq repository**. Instead, this project bundles `data/measurements/Moondrop Position (B&K 5128).csv`, derived from the manufacturer's public technical specification (`POSITION (Original)`, B&K 5128). For other headphones, users can select from the AutoEq catalog or drop local REW / `squig.link` (L/R `.txt`) curves.

## 2. Verified Components

| Component | File | Status |
|---|---|---|
| HID protocol + EQ/pre-gain/slot R/W | `scripts/moondrop_position.py` | Confirmed on Position firmware 0.5; hardware results summarized in README. |
| AutoEq pipeline: measurement + target → 8 bands → JSON profile | `scripts/eq_fit.py` | Tested against Position reference measurement |
| Equalizer APO EQ import | `moondrop_position.py import-eq` | Tested on sample exports |
| AutoEq venv (Python 3.11, numpy/scipy) | `.venvs/autoeq/` | Auto-reexec handled by `eq_fit.py` |
| `udev` rule | `udev/70-dsp-control.rules` | Ready for host `/etc/udev/rules.d/` |
| Data: factory curve + MIT targets + bundled index | `data/measurements/`, `data/targets/`, `data/autoeq-catalog.json` | Factory curve + 9 MIT AutoEq targets + full model/source index |
| Sample profile | `data/profiles/moondrop-position-harman.json` | Generated for Harman In-Ear 2019 |

Test results (`Moondrop Position (B&K 5128).csv` vs `Harman in-ear 2019.csv`, `fs = 96 kHz`):

* **Default (`1× LSQ + 1× HSQ + 6× PK`)** — shelf filters confirmed on firmware 0.5:
  ```
  RMS error: 3.05 dB (before EQ) → 0.47 dB (after EQ), max 3.12 dB
  preamp: −4.26 dB
  ```
* **Peaking filters only (`--no-shelves`, `8× PK`)** — restriction in the official `hub.moondroplab.tech` app (`docs/ref/moondrop-position.json` disables shelves and allows only `PK / LPQ / HPQ`):
  ```
  RMS error: 3.05 dB (before EQ) → 2.20 dB (after EQ), max 12.48 dB
  preamp: −4.66 dB
  ```

Using `1× LSQ + 1× HSQ + 6× PK` reduces RMS error nearly 5× (`0.47 dB` instead of `2.20 dB`) and cuts peak deviation 4× (`3.12 dB` instead of `12.48 dB`).

### Fit Preview in the Tuning Tab

Both **My profiles** and **AutoEq catalog** share a preview pane that separates selection from the active DAC profile. The AutoEq preview displays the target curve and the selected fit range. When the fit range changes, the previous plot remains visible alongside the range it was computed for (`meta.fit_range` stores `[max_hz, band_count]` in saved JSON profiles), while saving or applying requires a result matching the current range.

The top plot compares the factory B&K 5128 curve, target, and predicted acoustic response. For Custom profiles, the app adds the selected filter response and subtracts the factory slot 0 filter response (from live device readback or the firmware 0.5 reference). The bottom plot displays the combined electrical response at 96 kHz; pre-gain is shown separately and does not affect shape evaluation. The DSP curve uses Q2.30 coefficients read back from the device.

In compact windows, a switcher toggles between **Frequency response** and **EQ correction**. **Details…** next to RMS opens a dialog with the mean target offset and largest deviation in `20 Hz–10 kHz`. Plot geometry stays constant across profile switches while Y scales adapt dynamically.

The GUI interpolates on a logarithmic grid (`>= 96` steps/octave) and computes RMS over the overlapping range from `20 Hz` to `10 kHz`, subtracting the mean offset so level differences do not skew shape error. Frequencies above `10 kHz` are shaded to mark lower acoustic confidence.

For the bundled `8× PK` Harman profile, direct filter overlay on B&K 5128 yields ~`0.72 dB RMS`, while the GUI model replacing slot 0 filters yields ~`1.06 dB RMS` (peak deviation near `9.3 kHz`). The optimizer's own metric uses a smoothed error curve across the wider band (`2.20 dB RMS`, max `+12.48 dB` at `19.96 kHz`).

## 3. Architecture

```
                 ┌─────────────────────── Local & Bundled EQ Base ───────────────────────┐
                 │  measurements: Position factory curve, local REW / squig.link (.txt)  │
                 │  targets: bundled MIT AutoEq targets, custom CSV/TXT                  │
                 │  catalog: bundled model/source index + on-demand HTTPS curve cache    │
                 └───────────────────────────────────┬───────────────────────────────────┘
                                                     │
                                        ┌────────────▼────────────┐
                                        │  optimizer (AutoEq)     │
                                        │  compensate → smoothen  │
                                        │  → equalize → optimize  │
                                        │  within device limits   │
                                        └────────────┬────────────┘
                                                     │ JSON profile
                                        ┌────────────▼────────────┐
                                        │  HID transport (0x4B)   │
                                        │  hidraw (native)        │
                                        └────────────┬────────────┘
                                                     │
                                        ┌────────────▼────────────┐
                                        │  Hardware DAC DSP       │
                                        │  slot 7 "Custom", flash │
                                        └─────────────────────────┘
```

**DSP Control uses PySide6 + hidraw on Linux, packaged as Flatpak (`pl.innovibe.DspControl`).** Python shares profile handling and DAC writes between GUI and CLI. AutoEq remains decoupled from hardware access, and browsing/applying local profiles works offline.

References: [Qt for Python Deployment](https://doc.qt.io/qtforpython-6/deployment/index.html), [HIDAPI backends & udev](https://github.com/libusb/hidapi#about), [MDN WebHID availability](https://developer.mozilla.org/en-US/docs/Web/API/WebHID_API).

## 4. Integration Variants

| Variant | Mechanism | Pros | Cons | Best For |
|---|---|---|---|---|
| **A. CLI** | `eq_fit.py` → JSON → `write-eq`/`--apply`; hidraw + udev | offline, scriptable, no Chromium | no interactive plot | automation, scripting |
| **B. autoeq.app + import** | CSV → autoeq.app → Equalizer APO → `import-eq` → `write-eq` | web UI | manual file transfer, online fit | one-off tuning without venv |
| **C. modernGraphTool / devicePEQ (WebHID)** | browser → connect → auto-fit → write | browser UI | requires Chromium/WebHID, online | quick web edits |
| **D. FreeDSP Studio** | native Rust app | desktop UI | Position scheme 13 unverified | general FreeDSP cables |
| **E. EasyEffects / JamesDSP (software)** | PipeWire software PEQ | unlimited bands | host-only, not stored on DAC | software-only EQ |
| **F. DSP Control (PySide6 + hidraw)** | Linux desktop / Flatpak | offline profiles, shared CLI/GUI logic, live preview, 96 kHz shelves | requires host udev rule | daily hardware DSP control |

## 5. EQ Database Structure & Sources

```
data/
├── autoeq-catalog.json # bundled AutoEq model & target index
├── measurements/       # Position factory B&K 5128 curve + docs
├── targets/            # bundled MIT targets from AutoEq
└── profiles/           # ready-made JSON profiles
```

Sources and refresh behavior (also documented in `data/measurements/README.md` and `data/targets/README.md`):

* **MOONDROP Position (manufacturer spec)** — `data/measurements/Moondrop Position (B&K 5128).csv`, derived from public `POSITION (Original)` documentation.
* **User measurements (REW / squig.link)** — `scripts/measurements.py` parses local CSV and `.txt` (REW 1/48 oct, single or L/R) exports supplied by the user.
* **AutoEq** — `data/autoeq-catalog.json` provides model names and measurement sources from first launch, while MIT targets in `data/targets/` work offline. Third-party measurement curves (`measurements/<source>/data/.../*.csv`) are not redistributed in the repo due to missing uniform redistribution licenses; instead, the app downloads requested curves over HTTPS from `raw.githubusercontent.com` and refreshes the index via Git Smart HTTP (`filter=blob:none`, `deepen=1`), avoiding GitHub REST API anonymous rate limits. Failed refreshes leave existing cached indexes and curves intact.
* **Official Moondrop** — factory slot 0 ("Default") read directly via HID, plus `hub.mondroplab.com` device limits captured in `eqcaps` (`docs/ref/moondrop-position.json`).
* **eqcaps** — public CC0 device limit database (8 bands, PK/LP/HP ranges). Testing on firmware 0.5 confirmed additional support for `LSQ` (1) and `HSQ` (3).

`dump-slots` reads the active slot; `--switch` reads slots 0 and 7, restores the initial slot, and verifies its gain.

## 6. Linux Integration Guidelines

1. Install `udev/70-dsp-control.rules` on the host so regular users can access `/dev/hidraw*` for DSP control (consumer media keys on the separate HID interface are handled directly by the kernel/desktop).
2. Keep native Wayland (`QT_QPA_PLATFORM=wayland`) and Flatpak sandboxing clean.
3. Never auto-flash on connect by default; verify current state first and skip flash writes when already matching.

## 7. Hardware Constraints & Workarounds

* **8 bands (`1× LSQ + 1× HSQ + 6× PK`)**: enabled by default in `eq_fit.py` (`--no-shelves` reverts to `8× PK`).
* **Fixed `96 kHz` DSP rate**: optimizer runs at `fs=96000` to match hardware biquad evaluation.
* **Pre-gain**: computed as `−max_gain − 0.1 dB`, stored in register `0x23` (`−128…0 dB`, `1/256 dB` step).
* **Flash endurance**: write only on explicit user confirmation.

## 8. Risks & Pitfalls

1. **Factory DSP subtraction.** `POSITION (Original)` includes slot 0 ("Default") EQ. Subtract slot 0 response from the factory curve before optimizing 8 Custom bands.
2. **Write sequencing.** Band `0x09` → latch `0x0A` → preamp `0x23` → save `0x01`, respecting inter-frame delays (~25/50/200 ms, see `hid-protocol.md` §10).
3. **`LEN` & queue draining.** Flush stale HID input reports before each request and verify band-index echo.
4. **Licensing.** AutoEq and `data/targets/` curves are MIT; `Moondrop Position (B&K 5128).csv` comes from public manufacturer specs; `eqcaps` data is CC0. User-supplied `squig.link` / REW files stay local.

## 9. Verification Status & Quick CLI Start

Source beta testing runs via `python3 scripts/dsp_control.py --demo` (simulator) and `python3 scripts/dsp_control.py --diagnose` (physical DAC readback). On Position firmware 0.5 under EndeavourOS/KDE Wayland, hardware readback of slot 0/7, `LSQ`/`HSQ` Q2.30 coefficients, non-flash live preview with full restore, flash write + replug persistence, and pre-gain rounding (`−4.66 dB` → `−4.50 dB` confirmed readback) have been verified.

```bash
# 1) Fit a profile from measurement + target (auto-activates .venvs/autoeq)
scripts/eq_fit.py \
  -m "data/measurements/Moondrop Position (B&K 5128).csv" \
  -t "data/targets/Harman in-ear 2019.csv" \
  -o data/profiles/moondrop-position-harman.json

# 2) Or import Equalizer APO export from autoeq.app
scripts/moondrop_position.py import-eq --file eqapo.txt --out data/profiles/profile.json

# 3) Write to DAC (requires host udev rule)
scripts/moondrop_position.py write-eq --file data/profiles/profile.json --dry-run
scripts/moondrop_position.py write-eq --file data/profiles/profile.json --yes
```
