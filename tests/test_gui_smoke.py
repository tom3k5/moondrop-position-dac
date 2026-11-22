"""Testy smoke GUI PySide6 w trybie offscreen i symulatora (--demo)."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication

import position_gui as gui


def test_demo_window_launches_and_opens_editor(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    QStandardPaths.setTestModeEnabled(True)

    app = QApplication.instance() or QApplication([])
    window = gui.ProfilesWindow(demo=True, library_directory=tmp_path / "profiles")
    try:
        assert window.tabs.count() >= 2
        assert window.profiles.count() >= 1
        window.show()
        app.processEvents()

        # Otwórz edytor EQ bez zapisu i zamknij czysto.
        sample_bands = [
            {"band": i + 1, "type": "PK", "freq": 1000, "gain": 0.0, "q": 1.0} for i in range(gui.dac.BAND_COUNT)
        ]
        sample = gui.custom_profile("Smoke Test", gui.dac.CUSTOM_SLOT, sample_bands, 0.0)
        dialog = gui.EqualizerDialog(window, sample, None, None, device_path=None)
        dialog.show()
        app.processEvents()
        dialog.close()
    finally:
        window.close()
        app.processEvents()


def test_close_hides_to_tray_when_tray_visible(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    QStandardPaths.setTestModeEnabled(True)

    app = QApplication.instance() or QApplication([])
    window = gui.ProfilesWindow(demo=True, library_directory=tmp_path / "profiles")

    class FakeTray:
        def __init__(self) -> None:
            self.visible = True

        def isVisible(self) -> bool:
            return self.visible

        def supportsMessages(self) -> bool:
            return False

        def hide(self) -> None:
            self.visible = False

        def setToolTip(self, _text: str) -> None:
            pass

    window.tray = FakeTray()
    try:
        window.show()
        app.processEvents()
        assert window.isVisible()

        window.close()
        app.processEvents()
        assert not window.isVisible()
        assert window.timer.isActive()
    finally:
        window.quit_from_tray()
        app.processEvents()


def test_single_instance_server_activates_existing(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    activated = []
    server_name = f"moondrop-position-test-{tmp_path.name}"
    server = gui.start_instance_server(server_name, lambda: activated.append(True))
    assert server is not None
    try:
        assert gui.activate_existing_instance(server_name) is True
        app.processEvents()
        assert activated == [True]
    finally:
        server.close()


def test_help_dialog_tooltips_and_footer_links(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    QStandardPaths.setTestModeEnabled(True)

    app = QApplication.instance() or QApplication([])
    window = gui.ProfilesWindow(demo=True, library_directory=tmp_path / "profiles")
    try:
        assert window.tabs.count() == 3
        assert window.author_button.text() == "InnoVibe"
        assert window.coffee_button.toolTip()
        assert window.report_button.toolTip()
        assert "Mode: demo" in window.diagnostic_summary()
        window.state = gui.DeviceState(path="/dev/hidraw0", firmware="0.5", slot=7, preamp=-2.5, bands=[])
        diag = window.diagnostic_summary()
        assert "Firmware: 0.5" in diag
        assert "Active slot: 7 (Custom)" in diag

        assert window.why_label.text()
        assert window.guide_tips_label.text()
        assert window.guide_hub_btn.text()

        # Sprawdź przełączanie motywu InnoVibe (ciemny / jasny)
        dark_idx = window.theme_combo.findData("dark")
        light_idx = window.theme_combo.findData("light")
        assert dark_idx >= 0 and light_idx >= 0
        window.theme_combo.setCurrentIndex(dark_idx)
        assert app.palette().window().color().name() == "#161210"
        assert app.palette().highlight().color().name() == "#ff8a1f"
        window.theme_combo.setCurrentIndex(light_idx)
        assert app.palette().window().color().name() == "#faf7f2"
        assert app.palette().highlight().color().name() == "#ff6a00"
    finally:
        window.quit_from_tray()
        app.processEvents()


def test_phase1_phase2_eq_features(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    QStandardPaths.setTestModeEnabled(True)

    app = QApplication.instance() or QApplication([])
    window = gui.ProfilesWindow(demo=True, library_directory=tmp_path / "profiles")
    try:
        sample = gui.load_profile(gui.BUILTIN_PROFILE, "Harman In-Ear 2019")
        apo_path = tmp_path / "test.txt"
        apo_path.write_text(gui.dac.format_eqapo(sample.bands, sample.preamp), encoding="utf-8")
        parsed_bands, parsed_preamp = gui.dac.parse_eqapo(str(apo_path))
        assert len(parsed_bands) == len(sample.bands)
        assert parsed_preamp == round(sample.preamp, 2)

        assert window.autoeq_panel.fit_range.count() == 4
        assert window.acceptDrops() is True
        assert "1.06 dB" in window.fit_summary.text()
        assert "20 Hz–10 kHz" in window.fit_summary.text()
        assert "-4.66 dB" in window.preamp_summary.text()
        assert window.preview_plot.points != window.preview_plot.factory_points
        assert window.correction_plot.points == gui.response_points(sample, gui.EQ_PLOT_FREQUENCIES)

        editor = gui.EqualizerDialog(window, sample, sample, window.factory_profile, device_path=None)
        editor.preamp.setValue(0.0)
        editor.on_plot_band_changed(0, 120.0, 5.5)
        assert editor.rows[0][1].value() == 120
        assert editor.rows[0][2].value() == 5.5
        prev_q = editor.rows[0][3].value()
        editor.on_plot_band_q_changed(0, 0.5)
        assert editor.rows[0][3].value() > prev_q
        editor.apply_auto_headroom()
        assert editor.preamp.value() < 0.0
        editor.close()

        # Verify State A AutoEq target preview, DSP reference curve, and legend chip toggle/solo
        window.readback_profile = sample
        window.source_group.button(1).click()
        window.autoeq_panel.preview_entry = gui.catalog.Entry(
            "Test Target", "Test Source", "model", "test/path.csv", False
        )
        window.autoeq_panel.preview_curve = [(20.0, 0.0), (1000.0, 0.0), (20000.0, -4.0)]
        window.update_selection()
        assert len(window.preview_plot.factory_points) > 0
        assert len(window.preview_plot.reference_points) > 0
        assert len(window.preview_plot.target_points) > 0
        assert window.correction_plot.points == []

        window.preview_key.chips[1]._trigger_toggle()
        assert window.preview_plot.is_role_hidden([1])
        assert window.correction_plot.is_role_hidden([1])
        window.preview_plot.set_solo_role(2)
        assert window.preview_plot.solo_role == 2
        window.preview_plot.set_solo_role(None)
        window.preview_key.chips[1]._trigger_toggle()
        assert not window.preview_plot.is_role_hidden([1])
        assert not window.correction_plot.is_role_hidden([1])
    finally:
        window.quit_from_tray()
        app.processEvents()
