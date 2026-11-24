# Device Definitions (`data/devices/`)

Each subdirectory in `data/devices/<model_id>/` is a self-contained specification bundle for a supported USB DSP DAC or DSP IEM:

- `device.json` — declarative hardware, DSP, acoustic, and preset specification (`schema_version: 1`).
- `measurement.csv` *(optional, for `form_factor: "integrated_iem"`)* — bundled baseline frequency response in AutoEq `frequency,raw` CSV format.
- `profiles/*.json` *(optional)* — built-in starter EQ profiles tailored to this model's band count, sample rate, and slot layout.

## Device Categories (`form_factor`)

- `integrated_iem`: Fixed acoustic transducer paired with onboard DSP (e.g. `moondrop-position`, `moondrop-chu2-dsp`). Uses its own baseline measurement curve for acoustic preview and AutoEq fitting.
- `dongle_dac`: Standalone USB-C to 3.5 mm / 4.4 mm DAC/AMP with flat electrical output (e.g. `moondrop-echo-a`). Has no fixed headphone curve; acoustic preview and AutoEq require selecting the connected headphones.

## Bundled Measurements

| Model | File | Source |
|---|---|---|
| `moondrop-position` | `moondrop-position/measurement.csv` | Derived from MOONDROP public specification (`POSITION (Original)`, `60 dB @ 500 Hz`, B&K 5128) |
| `moondrop-chu2-dsp` | `moondrop-chu2-dsp/measurement.csv` | AutoEq (`HypetheSonics · GRAS RA0045`, `Moondrop Chu 2`, MIT-licensed repository) |
| `moondrop-echo-a` | *(none)* | Standalone flat DAC dongle (no fixed transducer) |

## Adding a New Model

1. Create `data/devices/<new-model-id>/device.json` (plus optional `measurement.csv` and `profiles/*.json`).
2. Add the USB `VID:PID` rule to `udev/70-dsp-control.rules`.
3. If the model uses an existing HID protocol (`moondrop_position`, `chu2_dsp`, `echo_a`), no driver code changes are needed; otherwise add a driver module in `scripts/` and reference it via `"usb.driver"`.
4. Run `QT_QPA_PLATFORM=offscreen python3 scripts/check_quality.py` to validate the bundle schema and tests.
