# Hardware Tester Guide (CHU II DSP & ECHO-A)

🌐 **Language:** English | [Polski](tester-guide.pl.md)

Thank you for helping verify the experimental drivers for **MOONDROP CHU II DSP** (`31b2:0113`) and **MOONDROP ECHO-A** (`3302:12c5`) on Linux!

> [!IMPORTANT]
> Run all tests from source (`main` branch) in a regular user session — **never as `root`**.

## 1. Install the `udev` rule (one-time)

```bash
sudo cp udev/70-dsp-control.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Unplug and replug your USB-C DAC/IEM cable.

## 2. Run the rootless diagnostic report

```bash
python3 scripts/dsp_control.py --diagnose
```

This prints a JSON report **without needing root**. Check:
- `hidraw_interfaces`: your device appears with `readable: true` and `writable: true`.
- `matched_model`: `"moondrop-chu2-dsp"` or `"moondrop-echo-a"`.
- `bands`: current EQ bands read from the device.

## 3. Back up your current EQ

Launch the GUI from source:

```bash
python3 scripts/dsp_control.py
```

Open **Device** → **Backup & Restore** → **Export EQ from DAC...** and save a JSON backup before making any changes.

## 4. Test write, replug, and restore

1. In **Tuning**, select a test profile or open **EQ Editor** and make a small, clearly audible change (e.g., `+3 dB` peaking at `1000 Hz`).
2. Apply to DAC and verify the readback succeeds.
   - **CHU II DSP note:** committing EQ (`0x53`) intentionally restarts the USB device for ~1–1.5 s. Wait for it to re-enumerate.
3. Unplug and replug the USB-C device, then run `python3 scripts/dsp_control.py --diagnose` again to confirm the EQ persisted.
4. Restore your exported backup and confirm the original state is back.

## 5. Submit your results

Open a [**Hardware Test Report**](https://github.com/tom3k5/moondrop-position-dac/issues/new?template=hardware-test-report.yml) on GitHub and paste the `--diagnose` JSON output along with your checklist results.
