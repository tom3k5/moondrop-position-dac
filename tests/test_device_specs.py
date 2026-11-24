"""Tests for modular device specifications, bundled measurements, and per-DAC profile filtering."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from PySide6.QtWidgets import QApplication  # noqa: E402

import device_specs  # noqa: E402
import dsp_control as gui  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_all_device_specs_load_and_match_hardware_capabilities():
    specs = device_specs.load_device_specs()
    assert set(specs) >= {"moondrop-position", "moondrop-chu2-dsp", "moondrop-echo-a"}

    pos = specs["moondrop-position"]
    assert pos.form_factor == "integrated_iem"
    assert pos.dsp.band_count == 8
    assert pos.dsp.sample_rate_hz == 96000.0
    assert pos.dsp.slots.factory == 0
    assert pos.dsp.slots.custom == 7
    assert pos.acoustics.measurement_includes_factory_eq is True
    assert len(pos.measured_curve()) > 400
    assert len(pos.builtin_profiles) == 1

    chu2 = specs["moondrop-chu2-dsp"]
    assert chu2.form_factor == "integrated_iem"
    assert chu2.dsp.band_count == 5
    assert chu2.dsp.sample_rate_hz == 48000.0
    assert chu2.dsp.supported_types == ("PK", "LSQ", "HSQ")
    assert chu2.dsp.slots.factory == 2
    assert chu2.dsp.slots.custom == 3
    assert chu2.dsp.reconnect_on_save is True
    assert chu2.acoustics.measurement_includes_factory_eq is False
    assert len(chu2.measured_curve()) > 600
    assert len(chu2.builtin_profiles) == 1
    chu2_harman = gui.load_profile(chu2.builtin_profiles[0].path, chu2.builtin_profiles[0].name, spec=chu2)
    assert len(chu2_harman.bands) == 5
    assert chu2_harman.model_id == "moondrop-chu2-dsp"
    assert chu2_harman.sample_rate_hz == 48000.0

    echo = specs["moondrop-echo-a"]
    assert echo.form_factor == "dongle_dac"
    assert echo.is_dongle is True
    assert echo.dsp.band_count == 8
    assert echo.dsp.sample_rate_hz == 93750.0
    assert echo.dsp.slots.factory is None
    assert echo.dsp.slots.custom == 0
    assert echo.measured_curve() == []
    assert echo.builtin_profiles == ()


def test_gui_switches_curves_and_filters_profiles_by_connected_dac(tmp_path: Path):
    _app()
    lib = tmp_path / "profiles"
    lib.mkdir()

    pos_spec = device_specs.get_device_spec("moondrop-position")
    chu2_spec = device_specs.get_device_spec("moondrop-chu2-dsp")
    echo_spec = device_specs.get_device_spec("moondrop-echo-a")

    gui.save_profile(
        str(lib / "my-position.json"),
        gui.custom_profile("My Position EQ", 7, pos_spec.default_custom_bands(), -2.0, spec=pos_spec),
    )
    gui.save_profile(
        str(lib / "my-chu2.json"),
        gui.custom_profile("My CHU2 EQ", 3, chu2_spec.default_custom_bands(), 0.0, spec=chu2_spec),
    )
    gui.save_profile(
        str(lib / "my-echo.json"),
        gui.custom_profile("My ECHO EQ", 0, echo_spec.default_custom_bands(), -1.0, spec=echo_spec),
    )

    window = gui.ProfilesWindow(demo=True, library_directory=lib, demo_model_id="moondrop-position")
    try:

        def visible_names() -> list[str]:
            names = []
            for idx in range(window.profiles.count()):
                item = window.profiles.item(idx)
                prof = item.data(gui.PROFILE_ROLE)
                if prof is not None and not item.isHidden():
                    names.append(prof.name)
            return names

        # Position active: sees only Position profiles and Position B&K 5128 curve
        pos_visible = visible_names()
        assert "My Position EQ" in pos_visible
        assert "My CHU2 EQ" not in pos_visible
        assert "My ECHO EQ" not in pos_visible
        assert len(window.preview_plot.factory_points) == len(pos_spec.measured_curve())

        # Switch to CHU II DSP: curve updates to Chu 2 GRAS, only CHU II profiles visible
        window.apply_device_spec(chu2_spec)
        chu2_visible = visible_names()
        assert "My CHU2 EQ" in chu2_visible
        assert "My Position EQ" not in chu2_visible
        assert "My ECHO EQ" not in chu2_visible
        assert len(window.preview_plot.factory_points) == len(chu2_spec.measured_curve())
        assert window.autoeq_panel.fit_range.itemData(0) == (20000, 5)

        # EqualizerDialog for CHU II DSP has 5 bands and 3 filter types (PK, LSQ, HSQ)
        editor = gui.EqualizerDialog(window, None, None, window.factory_profile, device_spec=chu2_spec)
        try:
            assert len(editor.rows) == 5
            types = [editor.rows[0][0].itemData(i) for i in range(editor.rows[0][0].count())]
            assert types == ["PK", "LSQ", "HSQ"]
            assert editor.preamp.isEnabled() is False
        finally:
            editor.close()
            editor.deleteLater()

        # Switch to ECHO-A (dongle DAC): no fixed acoustic curve, no factory slot, only ECHO-A profiles visible
        window.apply_device_spec(echo_spec)
        echo_visible = visible_names()
        assert "My ECHO EQ" in echo_visible
        assert "My Position EQ" not in echo_visible
        assert "My CHU2 EQ" not in echo_visible
        assert window.preview_plot.factory_points == []
        assert window.factory_item is None
    finally:
        window.allow_quit = True
        window.close()
        window.deleteLater()
