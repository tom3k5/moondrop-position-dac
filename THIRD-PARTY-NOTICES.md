# Third-Party Notices & Licenses

This project (`moondrop-position-dac`) is licensed under the **MIT License** (see `LICENSE`).
The application and Flatpak distribution use or bundle the following third-party components:

## Runtime & GUI Dependencies
- **PySide6 (Qt for Python)** (`6.11.3` / `6.12.0`): `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only` (used under the terms of `LGPL-3.0-only`).
- **org.kde.Platform / org.kde.Sdk / io.qt.PySide.BaseApp** (`6.11`): Flathub KDE & Qt runtime components (`LGPL`, `GPL`, `MIT`, `BSD`).
- **PipeWire** (`pw-metadata`): `MIT`.

## AutoEq & Scientific Python Packages (bundled in Flatpak `python3-autoeq`)
- **autoeq** (`4.1.2`): `MIT`
- **scipy** (`1.18.1`): `BSD-3-Clause`
- **numpy** (`2.5.5`): `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0`
- **matplotlib** (`3.11.2`): Matplotlib License (PSF-based)
- **pillow** (`13.0.0`): `MIT-CMU`
- **pyyaml** (`6.0.3`): `MIT`
- **tabulate** (`0.10.0`): `MIT`
- **contourpy** (`1.4.0`): `BSD-3-Clause`
- **cycler** (`0.12.1`): `BSD-3-Clause`
- **fonttools** (`4.68.0`): `MIT`
- **kiwisolver** (`1.5.1`): `BSD-3-Clause`
- **packaging** (`26.3`): `Apache-2.0 OR BSD-2-Clause`
- **pyparsing** (`3.3.3`): `MIT`
- **python-dateutil** (`4.0.0`): `BSD-3-Clause`
- **tzdata** (`2026.6`): `Apache-2.0`

## Reference Code & Data
- `docs/ref/moondropUsbHidHandler.js`, `usbHidProtocolUtils.js`, `walkplayHIDHandler.md` (from `jeromeof/devicePEQ`): `0BSD`
- `docs/ref/freedsp-gen2.rs` (from `EffectiveEquivalent/FreeDSP-Studio`): `MIT`
- `docs/ref/moondrop-position.json`, `moondrop-hub.json` (from `potatosalad775/eqcaps`): `CC0-1.0` (data) / `MIT` (code)
- `data/targets/*.csv` and `data/autoeq-catalog.json` index metadata (from `jaakkopasanen/AutoEq`): `MIT`

## Manufacturer Technical Data
- `data/measurements/Moondrop Position (B&K 5128).csv`: Factory frequency response curve digitized from public MOONDROP Position technical specification (`POSITION (Original)`).
