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
    assert pos.headphone_attachment == "detachable"
    assert pos.allows_headphone_selection is True
    assert pos.has_default_headphone is True
    assert pos.dsp.band_count == 8
    assert pos.dsp.sample_rate_hz == 96000.0
    assert pos.dsp.slots.factory == 0
    assert pos.dsp.slots.custom == 7
    assert pos.acoustics.measurement_includes_factory_eq is True
    assert len(pos.measured_curve()) > 400
    assert len(pos.builtin_profiles) == 1

    chu2 = specs["moondrop-chu2-dsp"]
    assert chu2.form_factor == "integrated_iem"
    assert chu2.headphone_attachment == "detachable"
    assert chu2.allows_headphone_selection is True
    assert chu2.has_default_headphone is True
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
    assert echo.headphone_attachment == "standalone"
    assert echo.allows_headphone_selection is True
    assert echo.has_default_headphone is False
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


def test_headphone_selection_mvp_for_integrated_detachable_and_standalone(tmp_path: Path):
    _app()
    lib = tmp_path / "profiles"
    lib.mkdir()
    custom_csv = tmp_path / "Sennheiser HD 600.csv"
    custom_csv.write_text("frequency,raw\n20,0.0\n1000,2.5\n20000,-4.0\n", encoding="utf-8")

    chu2_spec = device_specs.get_device_spec("moondrop-chu2-dsp")
    echo_spec = device_specs.get_device_spec("moondrop-echo-a")

    window = gui.ProfilesWindow(demo=True, library_directory=lib, demo_model_id="moondrop-position")
    try:
        # 1. Detachable (Position): headphone bar is visible, defaults to Position curve
        assert window.headphone_bar.isVisibleTo(window) is True
        assert window.headphone_selection.mode == "default"
        assert window.response_section.isVisibleTo(window) is True

        # 2. Detachable (CHU II DSP): headphone bar visible, defaults to CHU II, Flat hides acoustic section
        window.apply_device_spec(chu2_spec)
        assert window.headphone_bar.isVisibleTo(window) is True
        assert window.headphone_selection.mode == "default"
        assert window.response_section.isVisibleTo(window) is True
        assert window.autoeq_panel.headphone_cta.isVisibleTo(window.autoeq_panel) is False

        window.set_headphone_selection(gui.HeadphoneSelection(mode="flat"))
        assert window.response_section.isVisibleTo(window) is False
        assert window.correction_section.isVisibleTo(window) is True
        assert window.autoeq_panel.headphone_cta.isVisibleTo(window.autoeq_panel) is True

        window.set_headphone_selection(gui.HeadphoneSelection(mode="default"))
        assert window.response_section.isVisibleTo(window) is True
        assert len(window.preview_plot.factory_points) == len(chu2_spec.measured_curve())

        # 3. Standalone (ECHO-A): defaults to Flat, selecting local CSV enables acoustic preview + persists
        window.apply_device_spec(echo_spec)
        assert window.headphone_bar.isVisibleTo(window) is True
        assert window.headphone_selection.mode == "flat"
        assert window.response_section.isVisibleTo(window) is False
        assert window.correction_section.isVisibleTo(window) is True
        assert window.autoeq_panel.headphone_cta.isVisibleTo(window.autoeq_panel) is True

        # Editor in Flat mode has no acoustic tab
        flat_editor = gui.EqualizerDialog(
            window,
            None,
            None,
            window.factory_profile,
            device_spec=echo_spec,
            measurement_curve=window.active_measurement_curve(),
        )
        try:
            assert flat_editor.acoustic_plot.factory_points == []
        finally:
            flat_editor.close()
            flat_editor.deleteLater()

        # Select local headphone CSV
        window.set_headphone_selection(
            gui.HeadphoneSelection(
                mode="file",
                name="Sennheiser HD 600",
                source=custom_csv.name,
                path=str(custom_csv),
                form="over-ear",
            )
        )
        assert window.response_section.isVisibleTo(window) is True
        assert window.autoeq_panel.headphone_cta.isVisibleTo(window.autoeq_panel) is False
        assert len(window.preview_plot.factory_points) == 3
        assert window.active_headphone_name() == "Sennheiser HD 600"

        # Picker dialog filters model entries (including hyphenated queries like "kz-zsn pro x") and supports Flat
        picker = gui.HeadphonePickerDialog(window, echo_spec, window.autoeq_panel.entries)
        try:
            assert picker.list_model.rowCount() > 0
            picker.search.setText("kz-zsn pro x")
            assert picker.list_model.rowCount() >= 1
            first_entry = picker.list_model.index(0, 0).data(gui.PROFILE_ROLE)
            assert first_entry is not None
            assert "KZ ZSN Pro X" in first_entry.name
            picker.pick_flat()
            assert picker.selected_headphone == gui.HeadphoneSelection(mode="flat")
        finally:
            picker.close()
            picker.deleteLater()
    finally:
        window.allow_quit = True
        window.close()
        window.deleteLater()

    # Re-open window on ECHO-A and verify selection persisted in settings.json
    reopened = gui.ProfilesWindow(demo=True, library_directory=lib, demo_model_id="moondrop-echo-a")
    try:
        assert reopened.headphone_selection.mode == "file"
        assert reopened.headphone_selection.name == "Sennheiser HD 600"
        assert len(reopened.preview_plot.factory_points) == 3
        assert reopened.response_section.isVisibleTo(reopened) is True
    finally:
        reopened.allow_quit = True
        reopened.close()
        reopened.deleteLater()


def test_recent_headphones_limited_to_three_and_save_setup_profile(tmp_path: Path):
    _app()
    lib = tmp_path / "profiles"
    lib.mkdir()
    echo_spec = device_specs.get_device_spec("moondrop-echo-a")

    window = gui.ProfilesWindow(demo=True, library_directory=lib, demo_model_id="moondrop-echo-a")
    try:
        # Select 4 distinct local headphone CSVs -> recent list keeps 3 most recent in MRU order
        for idx in range(4):
            csv_file = tmp_path / f"HP-{idx}.csv"
            csv_file.write_text("frequency,raw\n20,0.0\n1000,1.0\n20000,-2.0\n", encoding="utf-8")
            window.set_headphone_selection(
                gui.HeadphoneSelection(mode="file", name=f"HP-{idx}", source=csv_file.name, path=str(csv_file))
            )

        recent = gui.load_recent_headphones(window.settings_path, echo_spec)
        assert [item.name for item in recent] == ["HP-3", "HP-2", "HP-1"]

        # Combo box exposes Flat + separator + 3 recent headphones
        combo_names = [
            window.headphone_combo.itemData(i).name
            for i in range(window.headphone_combo.count())
            if isinstance(window.headphone_combo.itemData(i), gui.HeadphoneSelection)
            and window.headphone_combo.itemData(i).mode == "file"
        ]
        assert combo_names == ["HP-3", "HP-2", "HP-1"]

        # Picker dialog renders the 3 recent headphones as quick-pick buttons
        picker = gui.HeadphonePickerDialog(window, echo_spec, window.autoeq_panel.entries, recent=recent)
        try:
            picker.pick_recent(recent[1])
            assert picker.selected_headphone == recent[1]
        finally:
            picker.close()
            picker.deleteLater()

        # Build & persist DAC x headphones x settings profile onto My profiles
        setup_prof = window.build_current_setup_profile("ECHO-A × HP-3")
        assert setup_prof.model_id == "moondrop-echo-a"
        assert setup_prof.headphone_name == "HP-3"
        assert len(setup_prof.bands) == 8
        assert window.persist_profile(setup_prof) is True
        assert window.selected_profile() is not None
        assert window.selected_profile().name == "ECHO-A × HP-3"
        assert window.selected_profile().headphone_name == "HP-3"
    finally:
        window.allow_quit = True
        window.close()
        window.deleteLater()


def test_semver_and_update_check(monkeypatch):
    assert gui.parse_semver_tuple("v0.5.0") == (0, 5, 0)
    assert gui.parse_semver_tuple("0.4.2-beta.1") == (0, 4, 2)
    assert gui.is_newer_version("v0.5.0", "0.4.2") is True
    assert gui.is_newer_version("v0.4.2", "0.4.2") is False
    assert gui.is_newer_version("0.4.1", "0.4.2") is False

    class _FakeResp:
        def geturl(self):
            return "https://github.com/tom3k5/moondrop-position-dac/releases/tag/v0.5.0"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(gui.urllib.request, "urlopen", lambda req, timeout=6: _FakeResp())
    latest = gui.check_latest_release()
    assert latest == "0.5.0"
    assert gui.is_newer_version(latest, "0.4.2") is True


def test_eqapo_clipboard_paste_and_ab_bypass(tmp_path: Path):
    _app()
    lib = tmp_path / "profiles"
    lib.mkdir()
    window = gui.ProfilesWindow(demo=True, library_directory=lib)
    try:
        base = gui.custom_profile("Test", 7, gui.default_custom_bands(window.active_spec), 0.0, spec=window.active_spec)
        dlg = gui.EqualizerDialog(window, base, None, device_spec=window.active_spec)
        try:
            ok = dlg.paste_from_clipboard("Preamp: -4.2 dB\nFilter 1: ON PK Fc 100 Hz Gain 3.5 dB Q 1.2\n")
            assert ok is True
            draft = dlg.draft()
            assert abs(draft.preamp - (-4.2)) < 0.01
            assert abs(draft.bands[0]["freq"] - 100.0) < 1e-6
            assert abs(draft.bands[0]["gain"] - 3.5) < 0.05

            bypass = dlg._bypass_profile(draft)
            assert bypass.preamp == 0.0
            assert all(b["gain"] == 0.0 for b in bypass.bands)
        finally:
            dlg.close()
            dlg.deleteLater()
    finally:
        window.allow_quit = True
        window.close()
        window.deleteLater()


def test_autoeq_fit_options_and_headphone_autosync(tmp_path: Path):
    _app()
    lib = tmp_path / "profiles"
    lib.mkdir()
    window = gui.ProfilesWindow(demo=True, library_directory=lib, demo_model_id="moondrop-echo-a")
    try:
        panel = window.autoeq_panel
        assert panel.pk_only.isEnabled() is True
        panel.bass_boost.setValue(2.5)
        panel.tilt.setValue(-0.4)
        panel.pk_only.setChecked(True)
        assert panel.current_fit_options() == (2.5, -0.4, True)

        hp_csv = tmp_path / "KZ-ZSN.csv"
        hp_csv.write_text("frequency,raw\n20,0.0\n1000,1.0\n20000,-1.0\n", encoding="utf-8")
        sel = gui.HeadphoneSelection(mode="file", name="KZ ZSN Pro X", source=hp_csv.name, path=str(hp_csv))
        window.set_headphone_selection(sel)
        setup_prof = window.build_current_setup_profile("ECHO-A × KZ")
        assert setup_prof.headphone_selection == sel.to_dict()
        assert window.persist_profile(setup_prof) is True

        # Switch to another profile & Flat headphones, then select the saved profile -> headphones auto-sync back
        window.profiles.setCurrentRow(0)
        window.set_headphone_selection(gui.HeadphoneSelection(mode="flat"))
        assert window.headphone_selection.mode == "flat"
        for row in range(window.profiles.count()):
            item = window.profiles.item(row)
            prof = item.data(gui.PROFILE_ROLE)
            if prof is not None and prof.name == "ECHO-A × KZ":
                window.profiles.setCurrentItem(item)
                break
        assert window.headphone_selection.mode == "file"
        assert window.headphone_selection.name == "KZ ZSN Pro X"
    finally:
        window.allow_quit = True
        window.close()
        window.deleteLater()


def test_v05_zero_eq_and_last_profile_per_dac(tmp_path: Path):
    _app()
    lib = tmp_path / "profiles"
    lib.mkdir()
    pos_spec = device_specs.get_device_spec("moondrop-position")
    echo_spec = device_specs.get_device_spec("moondrop-echo-a")
    gui.save_profile(
        str(lib / "pos-custom.json"),
        gui.custom_profile("Pos Saved", 7, pos_spec.default_custom_bands(), -2.0, spec=pos_spec),
    )
    gui.save_profile(
        str(lib / "echo-custom.json"),
        gui.custom_profile("Echo Saved", 0, echo_spec.default_custom_bands(), -1.5, spec=echo_spec),
    )

    window = gui.ProfilesWindow(demo=True, library_directory=lib, demo_model_id="moondrop-position")
    try:
        assert window.update_status_label.full_title == ""
        # Select Pos Saved on Position, switch to ECHO-A and select Echo Saved, then switch back
        for row in range(window.profiles.count()):
            p = window.profiles.item(row).data(gui.PROFILE_ROLE)
            if p is not None and p.name == "Pos Saved":
                window.profiles.setCurrentRow(row)
                break
        assert gui.load_last_profile_for_model(window.settings_path, "moondrop-position") == "Pos Saved"

        window.apply_device_spec(echo_spec)
        for row in range(window.profiles.count()):
            p = window.profiles.item(row).data(gui.PROFILE_ROLE)
            if p is not None and p.name == "Echo Saved":
                window.profiles.setCurrentRow(row)
                break
        assert gui.load_last_profile_for_model(window.settings_path, "moondrop-echo-a") == "Echo Saved"

        window.apply_device_spec(pos_spec)
        assert window.selected_profile() is not None
        assert window.selected_profile().name == "Pos Saved"

        dlg = gui.EqualizerDialog(window, window.selected_profile(), None, device_spec=pos_spec)
        try:
            dlg.reset_to_flat()
            draft = dlg.draft()
            assert draft.preamp == 0.0
            assert all(b["gain"] == 0.0 for b in draft.bands)
        finally:
            dlg.close()
            dlg.deleteLater()
    finally:
        window.allow_quit = True
        window.close()
        window.deleteLater()
