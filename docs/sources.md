# Sources & Licenses

## Control Protocol (HID `0x4B`)

| Project | License | Used For |
|---|---|---|
| [jeromeof/devicePEQ](https://github.com/jeromeof/devicePEQ) | 0BSD | `devicePEQ/moondropUsbHidHandler.js` — Moondrop command & frame layout; `ktmicroUsbHidHandler.js` + `tests/captures/ktmicro_chu2_dsp.json` (CHU II DSP); `walkplayHidHandler.js` + `walkplayHIDHandler.md` (ECHO-A); `usbDeviceConfig.js` (`0x0123` = scheme 13) |
| [jcharvet/chu2-studio](https://github.com/jcharvet/chu2-studio) | MIT | `docs/PROTOCOL.md` — KTMicro KT0210 USB topology and commit restart behavior for CHU II DSP (`31b2:0113`) |
| [Chronosauros/contour](https://github.com/Chronosauros/contour) | Apache-2.0 | `devices/moondrop-echo-a.json` & `echo-a-read-195126.log` — ECHO-A (`3302:12c5`) WalkPlay SchemeNo 11 hardware read capture & capabilities |
| [EffectiveEquivalent/FreeDSP-Studio](https://github.com/EffectiveEquivalent/FreeDSP-Studio) | MIT | `tools/app/src/dsp2.rs`, `hid_gen2.rs` — independent gen-2 coefficient/timing reference |
| [potatosalad775/eqcaps](https://github.com/potatosalad775/eqcaps) | code MIT, data CC0 | `data/profiles/moondrop/moondrop-position.json`, `data/bases/moondrop-hub.json` — official Moondrop app limits |
| [modernGraphTool — Hardware EQ](https://potatosalad775.github.io/modernGraphTool/docs/features/device-peq/) | — | WebHID device-PEQ documentation |
| [eqcaps — Hardware Catalog](https://potatosalad775.github.io/eqcaps/?kind=hardware) | — | Public device limits catalog |
| [hub.mondroplab.com](https://hub.mondroplab.com/) | — | Official "Custom EQ" web app (`1.8.0` build `26B1107`, POSITION config) |

Local reference copies live in `docs/ref/` (original filenames and licenses preserved).

## AutoEq / EQ Database

| Source | License | Used For |
|---|---|---|
| [jaakkopasanen/AutoEq](https://github.com/jaakkopasanen/AutoEq) | MIT (code & targets) | `autoeq` 4.1.2 PyPI library (`FrequencyResponse`, `optimize_parametric_eq`, `PEQ_CONFIGS`); MIT target curves in `data/targets/` and bundled model/source index `data/autoeq-catalog.json` |
| [autoeq.app](https://autoeq.app) | — | Equalizer APO export compatibility (`moondrop_position.py import-eq`) |
| [squig.link](https://squig.link) / REW | user-supplied input | `scripts/measurements.py` parses local REW / `squig.link` `.txt` files supplied by the user (not bundled) |
| MOONDROP Position specification | manufacturer spec | `data/measurements/Moondrop Position (B&K 5128).csv` (`POSITION (Original)`) |
| [docs/autoeq-integration.md](autoeq-integration.md) | — | Pipeline & optimization design notes |

Note: AutoEq's built-in `MOONDROP_FREE_DSP` config targets 9 PK bands; `scripts/eq_fit.py` builds a dedicated 8-band `96 kHz` config for Position.

## Hardware / Product

| Source | Notes |
|---|---|
| [MOONDROP Position — Linsoul](https://www.linsoul.com/products/moondrop-position) | 10 mm Al-Mg IEM, 18 Ω, 119 dB/Vrms, 15 Hz–38 kHz, USB-C DSP adapter |
| [17173 — Launch article](https://news.17173.com/content/09182026/160610463.shtml) | 24-bit, <5 ms, HRTF tuning, Web/App control |
| [IEMRanking — Moondrop Position](https://www.iemranking.com/show/moondrop-position) | Reviews & Super* Review notes |

## Linux System Layer

* `lsusb -v`, `/proc/asound/card*/{stream0,usbmixer,pcm*/info}`, `/sys/class/hidraw/*/device/report_descriptor`, `/run/udev/data/`, `/proc/bus/input/devices`.
* Kernel drivers: `snd-usb-audio` (UAC2), `usbhid`/`hid-generic`, `hidraw`.

## Runtime & Development Dependencies

### GUI, i18n & Flatpak

| Component | Version / Source | License | Role |
|---|---|---|---|
| **PySide6** | `6.11.3` (Flatpak) / `6.12.0` (host) | `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only` | Qt Widgets GUI, system tray, `QPainter` plots |
| **org.kde.Platform / org.kde.Sdk / io.qt.PySide.BaseApp** | `6.11` (Flathub) | LGPL / GPL / MIT / BSD | Flatpak runtime & PySide base |
| **PipeWire** (`pw-metadata`) | host tool | MIT | Read/force PipeWire sample rate (`clock.force-rate`) |
| **AutoEq HTTPS (`urllib.request` / `zlib`)** | Python stdlib | PSF | Refresh AutoEq index via Git Smart HTTP (`filter=blob:none`) and download curves from `raw.githubusercontent.com` without REST API rate limits |

### AutoEq Pipeline (`python3-autoeq` in Flatpak & `.venvs/autoeq`)

| Package | Version | License | Role |
|---|---|---|---|
| `autoeq` | `4.1.2` | MIT | 8-band parametric EQ optimization |
| `scipy` | `1.18.1` | BSD-3-Clause | Numerical optimization & filters |
| `numpy` | `2.5.5` | BSD-3-Clause / 0BSD / MIT / Zlib / CC0-1.0 | Array math & interpolation |
| `matplotlib` | `3.11.2` | Matplotlib License (PSF-based) | `autoeq` dependency & optional `--plot` PNG export |
| `pillow` | `13.0.0` | MIT-CMU | Image handling |
| `pyyaml` | `6.0.3` | MIT | YAML config parsing |
| `tabulate` | `0.10.0` | MIT | Table formatting |
| `contourpy` | `1.4.0` | BSD-3-Clause | `matplotlib` dependency |
| `cycler` | `0.12.1` | BSD-3-Clause | `matplotlib` dependency |
| `fonttools` | `4.68.0` | MIT | `matplotlib` dependency |
| `kiwisolver` | `1.5.1` | BSD-3-Clause | `matplotlib` dependency |
| `packaging` | `26.3` | Apache-2.0 OR BSD-2-Clause | `matplotlib` dependency |
| `pyparsing` | `3.3.3` | MIT | `matplotlib` dependency |
| `python-dateutil` | `4.0.0` | BSD-3-Clause | `matplotlib` dependency |
| `tzdata` | `2026.6` | Apache-2.0 | Timezone data |

### Quality & Tests

| Tool | Version | License | Role |
|---|---|---|---|
| `ruff` | `0.17.5` | MIT | Linter & formatter (`pyproject.toml`) |
| `pytest` | `9.2.0` | MIT | Unit & GUI smoke tests (`tests/`) |
| `pre-commit` | `.pre-commit-config.yaml` | MIT | Pre-commit quality checks |
