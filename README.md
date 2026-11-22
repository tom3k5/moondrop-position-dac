# MOONDROP:Gravity Position — Native Linux DSP, AutoEq & Gaming Audio Controller

🌐 **Language:** English | [Polski](README.pl.md)

[![Platform: Linux](https://img.shields.io/badge/Platform-Linux%20(Wayland%20%2F%20X11)-2ea44f?logo=linux&logoColor=white)](#quick-start)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776ab?logo=python&logoColor=white)](#quick-start)
[![UI: PySide6](https://img.shields.io/badge/GUI-PySide6%20(Qt6)-41cd52?logo=qt&logoColor=white)](#screenshots)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Unlock the full hardware DSP of your MOONDROP:Gravity Position (`35d8:0123`) natively on Linux — no browser required, zero CPU overhead, and a 6,800+ model AutoEq catalog built in.**

Whether you play competitive games on Steam/Proton or tune your IEMs to Harman, Diffuse Field, or your own REW measurements, this desktop app brings **100% of the official web configurator ([hub.moondroplab.tech](https://hub.moondroplab.tech/))** offline to Linux — plus unlocked shelf filters (`LSQ` / `HSQ`), interactive EQ curve editing, and PipeWire UAC2 control.

---

## Quick Start

### 1. Install via Flatpak (Recommended)
Download `position-dac.flatpak` from [**GitHub Releases**](https://github.com/tom3k5/moondrop-position-dac/releases/latest) (bundles PySide6 and the full AutoEq optimizer):

```bash
flatpak install --user position-dac.flatpak
flatpak run local.moondrop.Position
```

### 2. Enable USB HID Access on Linux (One-Time `udev` Rule)
Audio playback works out of the box in PipeWire. To allow non-root DSP/EQ control over `/dev/hidraw*` (required for both Flatpak and running from source):

```bash
sudo cp udev/70-moondrop-position.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Replug your MOONDROP:Gravity Position and verify detection:

```bash
python3 skrypty/position_gui.py --diagnose
```

The JSON report outputs the active slot, pre-gain, band parameters, and raw hexadecimal Q2.30 biquad coefficients.

### 3. Try Without Hardware (Demo Simulator) or Run from Source
Explore the entire UI, charts, AutoEq catalog, and EQ editor with no DAC connected:

```bash
git clone https://github.com/tom3k5/moondrop-position-dac.git
cd moondrop-position-dac
python3 skrypty/position_gui.py --demo
```

To run against a physical DAC from source, omit `--demo`:

```bash
python3 skrypty/position_gui.py
```

*(Optional: to run the AutoEq optimizer from source, set up `.venvs/autoeq` with Python 3.11 as described in [`docs/integracja-autoeq.md`](docs/integracja-autoeq.md).)*

### 4. Build Flatpak Locally & Permissions
```bash
flatpak-builder --force-clean --disable-rofiles-fuse --repo=flatpak-repo flatpak-build local.moondrop.Position.json
flatpak build-bundle flatpak-repo position-dac.flatpak local.moondrop.Position
```

The manifest ([`local.moondrop.Position.json`](local.moondrop.Position.json)) requests `--device=all` (USB `hidraw` DSP access), `--share=network` (user-initiated AutoEq catalog downloads), `--talk-name=org.kde.StatusNotifierWatcher` (system tray icon), and `--socket=wayland` / `--socket=fallback-x11` / `--share=ipc` (desktop window).

The current HID transport opens `/dev/hidraw*` directly. Flatpak's USB portal supplies a raw USB handle for a libusb-style transport. If you use local profiles and cached curves, run `flatpak run --unshare=network local.moondrop.Position` for an offline session.

---

## Why Use the Native Linux App?

- **Hardware DSP, Zero CPU Load:** Your 8-band parametric EQ runs directly on the DAC chip (`< 5 ms` latency) and stays active in every Steam/Proton game, Discord call, and media player — even after closing the app or moving to another PC.
- **Unlocks `LSQ` & `HSQ` Shelf Filters:** While `hub.moondroplab.tech` disables shelf filters for Position (`PK / LP / HP` only), this app unlocks hardware `LSQ` and `HSQ` shelves verified on firmware `0.5`. AutoEq defaults to `1× LSQ + 1× HSQ + 6× PK`, drastically reducing target error (`0.47 dB` vs `2.20 dB` RMS on Position → Harman In-Ear 2019).
- **Safe Offline Workflow:** Browsing, AutoEq fitting, and saving profiles to disk are completely separate from flashing the DAC. Every write performs pre/post-flash readback verification, and live preview automatically restores your previous DAC state if you cancel.
- **System Tray & PipeWire Control:** Minimize to the tray to switch profiles in two clicks, check your active ALSA bit depth, and optionally force the PipeWire sample rate (`44.1–384 kHz`).

| Feature | Official Web Hub | MOONDROP:Gravity Position for Linux |
|---|---|---|
| 8-band Parametric EQ (`PK / LSQ / HSQ / LP / HP`) + Pre-gain | `PK / LP / HP` only (shelves disabled) | **Unlocks `LSQ / HSQ` (`1× LSQ + 1× HSQ + 6× PK`), native USB HID `0x4B`, offline** |
| Interactive EQ Curve & Headroom | Sliders only | **Drag handles `1–8` (Freq/Gain/Wheel Q) + Auto Headroom & Clip Check** |
| Live Auditioning | Yes | **Yes, auto-enabled with safe state restore on cancel** |
| Built-in AutoEq Optimizer | Basic presets | **6,800+ models + pre-fit target preview + selectable fit range + Drag & Drop** |
| Live DSP Comparison & Interactive Legend | No | **Compare against Current in DSP on both plots, toggle/solo pills, `Hz / dB / Δ dB` crosshair** |
| Output Gain (`-18…0 dB`) & Mic Gain | Yes | **Yes, optional per-profile bundling** |
| Local Library vs DAC Flash | Limited | **Full local library, Drag & Drop, JSON & Equalizer APO (`.txt`) import/export** |
| PipeWire UAC2 Monitor & Sample Rate | No | **Yes (`44.1–384 kHz` + ALSA bit-depth readout)** |
| Readback Verification & Backup | Basic | **Pre/post-flash verification, 1-click Restore previous & DAC backup** |
| Themes, Language & Built-in Guide | Web only | **InnoVibe Dark & Light themes, EN / PL, built-in Guide tab** |

---

## Screenshots

MOONDROP:Gravity Position v0.3.8 running in demo mode with the **InnoVibe Dark** theme.

### 1. Tuning & Frequency Response Preview
Browse **My profiles** on the left and inspect the prediction on the right without touching your DAC — **Selected profile** and **Active on DAC** stay clearly separated until you click **Apply to DAC** (which changes to **Restore previous** after flashing so you can revert in one click, or shows **Already active on DAC** for an unchanged active state).

- **Headphone response** compares the **Factory (B&K 5128)** baseline, **Target**, **Predicted result**, and **Current in DSP**; click **Details…** next to RMS to inspect the mean target offset and peak deviation in the `20 Hz–10 kHz` band (frequencies above `10 kHz` are shaded due to lower acoustic confidence).
- **EQ correction** displays the electrical filter curve at `96 kHz` with **Current in DSP** and **Profile EQ** legend pills alongside separate profile and DSP pre-gain on the right. Plot heights stay locked across tabs while Y-axis scales adapt dynamically; compact windows use a view switcher. Hover over a shortened fit summary or status message to read the full text.
- When the DAC confirms a rounded pre-gain, the action bar beside **Apply to DAC** shows the confirmed value and the profile value.
- Click legend pills to hide/show curves, hover a pill to **solo** it, or hover the plot for a live `Hz / dB / Δ dB` readout.

![Tuning with both plots and pre-gain beside the EQ correction legend](docs/screenshots/01-tuning-profiles.png)

<details>
<summary>Compact Tuning view</summary>

![Compact Tuning with a switch between frequency response and EQ correction](docs/screenshots/06-tuning-compact.png)

</details>

### 2. Built-in AutoEq Catalog (6,800+ Models)
Switch to **AutoEq catalog** to filter thousands of IEM and over-ear measurements by **Source**, **Headphone type**, and **Fit range**, then search by model (`Get catalog` and the result count sit on the shared bottom bar). You can also drop your own `.csv` / `.txt` curve onto the window.

- Pick a **Fit range** (`20 Hz–20 kHz` or up to `6 / 4 / 2 kHz` to keep upper bands free for manual treble tweaks) and click **Compute profile** — the action bar cleanly reveals **Save profile**, **Edit EQ…**, and **Apply to DAC** once fitted.
- Each computed profile records its fit range (including when saved to disk); if you change the range afterwards, **Recompute profile** replaces the right action button so you never apply or save a stale fit.

![AutoEq Catalog](docs/screenshots/02-autoeq-catalog.png)

### 3. 8-Band Parametric EQ Editor & Live Preview
Click **Edit EQ…** to open the dedicated editor. With a DAC connected, **Live preview** turns on automatically, lets you audition every tweak in real time without flashing memory, and safely restores your previous DAC settings if you turn it off or cancel.

- Drag numbered handles `1–8` directly on the **EQ correction** plot (Freq / Gain / scroll wheel Q), fine-tune with sliders or numeric fields, and click **Set automatically** to set pre-gain from available headroom.
- The editor fits all eight bands on opening when the available screen height allows it. Expand **Output and microphone gain in profile** below the bands to attach those settings.
- If a steep `LSQ` or `HSQ` exceeds the DAC's coefficient range, reduce Q or gain. Live preview restores the original coefficients and pre-gain when it ends.
- Switch to **Frequency response** to check the predicted acoustic curve, enable **Compare with initial profile**, and use the bottom bar to **Export profile…** (`.txt` / `.json`), **Save profile**, or **Apply to DAC**.

![EQ Editor](docs/screenshots/04-eq-editor.png)

### 4. Device Status, Gains & PipeWire UAC2 Quality
Check your active DAC profile, slot (`0` Factory / `7` Custom), pre-gain, and output/microphone gain at a glance.

- View the active ALSA playback stream and set the session-wide **PipeWire sample rate**. Choose **Automatic (PipeWire)** or a fixed rate (`44.1–384 kHz`) and select **Apply**. Expand **USB and PipeWire details** for raw USB format and firmware info.
- Back up your DAC's Custom slot to JSON, run a **Factory reset…**, and switch between **InnoVibe Dark / Light** themes and **EN / PL** languages.

![Device settings with the full Automatic (PipeWire) label](docs/screenshots/03-device-settings.png)

<details>
<summary>Compact Device view</summary>

![Compact Device view with the full sample-rate label and its Apply and Refresh buttons](docs/screenshots/07-device-compact.png)

</details>

### 5. Built-in Guide, Shortcuts & Diagnostics
Everything you need inside the app: quick walkthroughs for tuning and live preview, drag-and-drop import tips, keyboard shortcuts (`Ctrl+F` search, `Ctrl+O` import, `Ctrl+Q` quit), 1-click diagnostic copy for bug reports, the current version and license indicator in the bottom-right corner, and direct support links.

![Guide Tab](docs/screenshots/05-guide-tab.png)

---

## Technical Documentation

- [`docs/protokol-hid.md`](docs/protokol-hid.md) — Reverse-engineered USB HID `0x4B` DSP protocol (Q2.30 biquad encoding, slots, pre-gain, global/mic gain).
- [`docs/integracja-autoeq.md`](docs/integracja-autoeq.md) — AutoEq catalog pipeline and 8-band (`LSQ + HSQ + 6× PK` / `PK`) optimization details.
- [`docs/zrodla.md`](docs/zrodla.md) — Hardware USB descriptors, UAC2 modes, and reference configurations.

---

## Support the Project

> [!TIP]
> **Enjoying MOONDROP:Gravity Position on Linux?**
> If this app helps you get better sound out of your DAC on Linux, consider supporting continued development — every coffee helps keep updates, hardware testing, and new features coming!

- ☕ **Buy me a coffee:** Visit the [**InnoVibe support page**](https://innovibe.pl/en/ko-fi/) (choose your preferred amount and payment method) or click **Buy me a coffee…** under **Support the project** in the app's **Guide** tab.
- 👤 **Author:** [InnoVibe](https://www.innovibe.pl/en)
- 🐛 **Bugs & Feature Ideas:** Use **Report bug / Feature** in the **Guide** tab (includes a 1-click diagnostic copy) or open an issue on [GitHub Issues](https://github.com/tom3k5/moondrop-position-dac/issues/new/choose).
