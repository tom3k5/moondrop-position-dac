"""Tests for DSP Control v0.6.0 Stage 1 features."""

from __future__ import annotations

import json
import os
import zipfile
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication

import dsp_control as gui


def _sample_bands(gains: list[float] | None = None) -> list[dict]:
    freqs = [105, 250, 500, 1000, 2000, 4000, 6000, 10000]
    types = ["LSQ", "PK", "PK", "PK", "PK", "PK", "HSQ", "PK"]
    qs = [0.71, 1.0, 1.2, 1.4, 1.2, 1.0, 0.71, 1.0]
    values = gains or [0.0] * len(freqs)
    return [
        {"band": i + 1, "type": types[i], "freq": freqs[i], "gain": values[i], "q": qs[i]}
        for i in range(gui.dac.BAND_COUNT)
    ]


def test_apply_macro_tone_adjusts_and_clamps_respecting_pk_only() -> None:
    bands = _sample_bands([0.0] * gui.dac.BAND_COUNT)
    shaped = gui.apply_macro_tone(bands, bass_db=3.0, mid_db=-1.5, treble_db=2.0, tilt_db_per_oct=-0.5)
    assert shaped[0]["gain"] > 0.0
    assert shaped[3]["gain"] < 0.0
    assert shaped[6]["gain"] != 0.0

    # Clamping to gain_range_db
    extreme = gui.apply_macro_tone(
        _sample_bands([10.0] * gui.dac.BAND_COUNT), bass_db=10.0, mid_db=10.0, treble_db=10.0
    )
    gain_min, gain_max = gui.default_device_spec().dsp.gain_range_db
    assert all(gain_min <= b["gain"] <= gain_max for b in extreme)

    # PK-only device spec must not introduce LSQ/HSQ even when activating neutral bands
    base_spec = gui.default_device_spec()
    pk_spec = replace(
        base_spec,
        model_id="pk-only",
        display_name="PK Only",
        dsp=replace(
            base_spec.dsp,
            supported_types=("PK",),
        ),
    )
    pk_bands = [{"band": i + 1, "type": "PK", "freq": 1000, "gain": 0.0, "q": 1.0} for i in range(gui.dac.BAND_COUNT)]
    pk_shaped = gui.apply_macro_tone(pk_bands, bass_db=3.0, treble_db=-2.0, spec=pk_spec)
    assert all(b["type"] == "PK" for b in pk_shaped)


def test_library_zip_export_import_roundtrip_and_conflicts(tmp_path: Path) -> None:
    lib_src = tmp_path / "lib_src"
    lib_src.mkdir()
    prof_a = gui.custom_profile(
        "Alpha Tune", gui.dac.CUSTOM_SLOT, _sample_bands([2.0, 0.0, 0.0, -1.0, 0, 0, 1.5, 0]), -2.0
    )
    prof_a.model_id = "moondrop-position"
    prof_a.headphone_selection = {"source": "autoeq", "model": "Sennheiser HD 600"}
    prof_a.muted_bands = {"2": {"band": 2, "type": "PK", "freq": 250, "gain": 3.5, "q": 1.2}}
    gui.save_profile(str(lib_src / "alpha.json"), prof_a)

    zip_path = tmp_path / "bundle.zip"
    assert gui.export_library_zip(lib_src, zip_path) == 1

    # Add a Zip Slip entry to ensure it is safely ignored
    with zipfile.ZipFile(zip_path, "a") as zf:
        zf.writestr("../evil.json", json.dumps({"name": "Evil", "bands": []}))

    lib_dst = tmp_path / "lib_dst"
    imported, skipped = gui.import_library_zip(zip_path, lib_dst, conflict="copy")
    assert (imported, skipped) == (1, 0)
    assert not (tmp_path / "evil.json").exists()

    loaded_files = list(lib_dst.glob("*.json"))
    assert len(loaded_files) == 1
    loaded = gui.load_profile(loaded_files[0])
    assert loaded.name == "Alpha Tune"
    assert loaded.model_id == "moondrop-position"
    assert loaded.headphone_selection == {"source": "autoeq", "model": "Sennheiser HD 600"}
    assert loaded.muted_bands == {"2": {"band": 2, "type": "PK", "freq": 250, "gain": 3.5, "q": 1.2}}

    # Skip conflict
    assert gui.import_library_zip(zip_path, lib_dst, conflict="skip") == (0, 1)
    # Copy conflict
    assert gui.import_library_zip(zip_path, lib_dst, conflict="copy") == (1, 0)
    assert len(list(lib_dst.glob("*.json"))) == 2
    # Overwrite conflict
    assert gui.import_library_zip(zip_path, lib_dst, conflict="overwrite") == (1, 0)


def test_editor_mute_solo_ab_targets_and_macro_panel(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    QStandardPaths.setTestModeEnabled(True)

    app = QApplication.instance() or QApplication([])
    window = gui.ProfilesWindow(demo=True, library_directory=tmp_path / "profiles")
    try:
        prof = gui.custom_profile(
            "Mute Solo Test",
            gui.dac.CUSTOM_SLOT,
            _sample_bands([3.0, -2.0, 1.5, 0.0, 0.0, 0.0, 2.0, 0.0]),
            -3.0,
        )
        compare = gui.custom_profile(
            "Compare B",
            gui.dac.CUSTOM_SLOT,
            _sample_bands([1.0, 0.0, -1.0, 0.5, 0.0, 0.0, 0.0, 0.0]),
            -1.0,
        )
        dialog = gui.EqualizerDialog(window, prof, None, None, device_path=None, compare_profile=compare)
        try:
            dialog.show()
            app.processEvents()

            # Mute band 1: live draft writes 0.0 gain while select_draft() saves original in muted_bands
            enabled_cb, _, _ = dialog.band_mute_solo[0]
            enabled_cb.setChecked(False)
            app.processEvents()
            live_draft = dialog.draft(include_solo=True)
            assert live_draft.bands[0]["gain"] == 0.0
            dialog.select_draft()
            saved_draft = dialog.result_profile
            assert saved_draft is not None
            assert saved_draft.bands[0]["gain"] == 0.0
            assert saved_draft.muted_bands is not None
            assert "1" in saved_draft.muted_bands
            assert saved_draft.muted_bands["1"]["gain"] == 3.0

            # Restoring via set_profile preserves muted state and original gain
            dialog.set_profile(saved_draft)
            assert not dialog.band_mute_solo[0][0].isChecked()
            assert abs(dialog.rows[0][2].value() - 3.0) < 1e-6
            dialog.band_mute_solo[0][0].setChecked(True)
            app.processEvents()

            # Solo band 2: live draft isolates band 2, but select_draft() ignores temporary solo
            _, solo_btn, _ = dialog.band_mute_solo[1]
            solo_btn.setChecked(True)
            app.processEvents()
            solo_draft = dialog.draft(include_solo=True)
            assert solo_draft.bands[1]["gain"] == -2.0
            assert solo_draft.bands[0]["gain"] == 0.0
            assert solo_draft.bands[2]["gain"] == 0.0
            dialog.select_draft()
            saved_with_solo = dialog.result_profile
            assert saved_with_solo is not None
            assert saved_with_solo.bands[0]["gain"] == 3.0
            assert saved_with_solo.bands[2]["gain"] == 1.5
            dialog.show()
            dialog.clear_solo()
            assert not solo_btn.isChecked()

            # A/B targets: flat, initial, compare
            assert dialog.ab_target_mode == "flat"
            dialog._set_ab_target_mode("initial")
            assert dialog.ab_target_mode == "initial"
            dialog._set_ab_target_mode("compare")
            assert dialog.ab_target_mode == "compare"
            dialog.ab_bypass.setChecked(True)
            app.processEvents()
            dialog.ab_bypass.setChecked(False)
            app.processEvents()

            # Macro panel toggle, slider change, revert, apply
            assert not dialog.macro_panel.isVisible()
            dialog.macro_toggle.setChecked(True)
            app.processEvents()
            assert dialog.macro_panel.isVisible()
            before_band1 = dialog.rows[0][2].value()
            dialog.macro_controls["bass"].setValue(2.0)
            app.processEvents()
            assert dialog.rows[0][2].value() > before_band1
            dialog.revert_macro()
            app.processEvents()
            assert abs(dialog.rows[0][2].value() - before_band1) < 1e-6
            dialog.macro_controls["bass"].setValue(1.5)
            dialog.apply_macro()
            app.processEvents()
            assert dialog.macro_controls["bass"].value() == 0.0
        finally:
            dialog.close()
    finally:
        window.close()
        app.processEvents()


def test_profiles_window_compare_b_preserves_plot_geometry(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    QStandardPaths.setTestModeEnabled(True)

    app = QApplication.instance() or QApplication([])
    window = gui.ProfilesWindow(demo=True, library_directory=tmp_path / "profiles")
    try:
        for width, height in ((1140, 820), (608, 592)):
            window.resize(width, height)
            window.show()
            app.processEvents()
            window.clear_compare_profile()
            app.processEvents()
            preview_before = window.preview_plot.geometry()
            correction_before = window.correction_plot.geometry()

            prof_b = gui.custom_profile(
                "Ref B", gui.dac.CUSTOM_SLOT, _sample_bands([2.0, 0, 0, -1.0, 0, 0, 1.0, 0]), -2.0
            )
            window.set_compare_profile(prof_b)
            app.processEvents()

            assert window.compare_profile is not None
            assert window.compare_clear_btn.isEnabled()
            assert window.preview_plot.geometry() == preview_before
            assert window.correction_plot.geometry() == correction_before
            assert "Ref B" in window.preview_key.chips[1].label.text()
            assert "Ref B" in window.correction_key.chips[1].label.text()
    finally:
        window.close()
        app.processEvents()
