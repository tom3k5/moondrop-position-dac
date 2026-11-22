"""Testy smoke GUI PySide6 w trybie offscreen i symulatora (--demo)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QRect, QStandardPaths, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

import position_gui as gui


def test_diagnose_serializes_dsp_coefficients(monkeypatch, capsys) -> None:
    demo = gui.DemoDevice()
    monkeypatch.setattr(gui, "open_position", lambda: demo)
    monkeypatch.setattr(sys, "argv", ["position_gui.py", "--diagnose"])
    assert gui.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["slot"] == 0
    assert len(report["coefficients"]) == gui.dac.BAND_COUNT
    assert bytes.fromhex(report["coefficients"][0]) == gui.coefficients_for_band(gui.POSITION_FACTORY_BANDS[0])


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


def test_guide_tooltips_and_support_links(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    QStandardPaths.setTestModeEnabled(True)

    app = QApplication.instance() or QApplication([])
    window = gui.ProfilesWindow(demo=True, library_directory=tmp_path / "profiles")
    try:
        assert window.tabs.count() == 3
        assert "InnoVibe" in window.guide_author_btn.text()
        assert window.guide_coffee_btn.toolTip()
        assert window.guide_coffee_btn.parentWidget() is window.guide_support_box
        links = window.links_box.layout()
        assert [links.itemAt(index).widget() for index in range(links.count())] == [
            window.report_button,
            window.guide_author_btn,
            window.guide_hub_btn,
        ]
        opened = []
        monkeypatch.setattr(window, "open_external_url", opened.append)
        window.guide_coffee_btn.click()
        assert opened == [gui.tr("footer.coffee_url")]
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
        assert app.palette().highlightedText().color().name() == "#1c1917"
        assert window.preview_plot.series_pen(2).color().name() == "#0284c7"
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
        window.fit_detail_button.click()
        dialog = window.findChild(QMessageBox)
        assert dialog.informativeText() == window.fit_summary.toolTip()
        assert dialog.text() == window.fit_summary.text()
        dialog.close()
        assert "-4.66 dB" in window.preamp_summary.text()
        assert window.preview_plot.points != window.preview_plot.factory_points
        assert window.correction_plot.points == gui.response_points(sample, gui.EQ_PLOT_FREQUENCIES)

        editor = gui.EqualizerDialog(window, sample, sample, window.factory_profile, device_path=None)
        assert editor.plot.correction and editor.plot.interactive
        assert not editor.acoustic_plot.correction
        assert not editor.upload.autoDefault()
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


@pytest.mark.parametrize("font", [None, "DejaVu Sans"])
def test_builtin_profiles_keep_plot_geometry(tmp_path: Path, font: str | None) -> None:
    app = QApplication.instance() or QApplication([])
    original_font = app.font()
    if font:
        app.setFont(QFont(font, 9))
    (tmp_path / "settings.json").write_text('{"language":"pl","theme":"dark"}')
    window = gui.ProfilesWindow(demo=True, library_directory=tmp_path / "profiles")
    try:
        harman_item = window.profiles.currentItem()
        sample = window.selected_profile()
        drive = window.open_device()
        drive.set_slot(gui.dac.CUSTOM_SLOT)
        drive.set_preamp(-4.50)
        for index, band in enumerate(sample.bands):
            drive.write_band(index, band["freq"], band["gain"], band["q"], band["type"], gui.dac.CUSTOM_SLOT)
        window.timer.stop()
        window.refresh_done(gui.read_state(drive), "")
        window.show()

        def plot_geometry(plot):
            return plot.mapTo(window, QPoint()), plot.size()

        window.setMinimumWidth(608)
        for width, height in ((1140, 820), (840, 620), (608, 592)):
            window.resize(width, height)
            window.profiles.setCurrentItem(harman_item)
            QTest.qWait(40)
            reference = [plot_geometry(plot) for plot in (window.preview_plot, window.correction_plot)]
            assert window.preview_plot.width() <= window.preview_scroll.viewport().width()
            assert window.fit_detail_button.isEnabled()
            assert not window.apply_button.isEnabled()
            assert not window.connection.wordWrap()
            assert window.apply_button.geometry().right() == window.apply_button.parentWidget().rect().right()
            if window.edit_button.y() == window.apply_button.y():
                assert window.edit_button.geometry().right() < window.apply_button.geometry().left()
            else:
                assert window.edit_button.geometry().right() == window.apply_button.geometry().right()

            for item in (window.flat_item, window.factory_item):
                window.profiles.setCurrentItem(item)
                QTest.qWait(40)
                assert plot_geometry(window.preview_plot) == reference[0]
                if window.correction_plot.isVisible():
                    assert plot_geometry(window.correction_plot) == reference[1]
                assert not window.fit_detail_button.isEnabled()
                assert window.apply_button.isEnabled()

            if width >= 840:
                window.applying_profile = window.flat_item.data(gui.PROFILE_ROLE)
                window.refresh_buttons()
                QTest.qWait(40)
                assert window.apply_status.isVisible()
                assert plot_geometry(window.preview_plot) == reference[0]
                assert plot_geometry(window.correction_plot) == reference[1]
                status_rect = QRect(window.apply_status.mapTo(window, QPoint()), window.apply_status.size())
                edit_rect = QRect(window.edit_button.mapTo(window, QPoint()), window.edit_button.size())
                assert status_rect.right() < edit_rect.left()
                assert abs(status_rect.center().y() - edit_rect.center().y()) <= 2
                window.applying_profile = None
                window.refresh_buttons()
                QTest.qWait(40)
    finally:
        window.quit_from_tray()
        app.processEvents()
        app.setFont(original_font)


def test_device_form_uses_shared_alignment_and_responsive_actions(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    (tmp_path / "settings.json").write_text('{"language":"pl","theme":"dark"}')
    window = gui.ProfilesWindow(demo=True, library_directory=tmp_path / "profiles")
    try:
        window.setMinimumWidth(608)
        window.resize(1140, 820)
        window.show()
        window.tabs.setCurrentIndex(1)
        QTest.qWait(50)
        assert window.playback_stream_label.x() == window.playback_force_label.x() == window.pipewire_scope.x()
        assert window.global_gain_button.x() == window.mic_gain_button.x()
        assert window.theme_combo.x() == window.language_combo.x()
        assert window.theme_combo.width() == window.language_combo.width()
        assert window.backup_button.y() == window.defaults_button.y()
        assert abs(window.backup_button.width() - window.defaults_button.width()) <= 1

        window.resize(608, 592)
        QTest.qWait(50)
        assert window.backup_button.x() == window.defaults_button.x()
        assert window.backup_button.width() == window.defaults_button.width()
        assert window.backup_button.geometry().bottom() < window.defaults_button.y()
    finally:
        window.quit_from_tray()
        app.processEvents()


def test_action_hover_and_hold_use_distinct_states(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = gui.ProfilesWindow(demo=True, library_directory=tmp_path / "profiles")
    try:
        window.refresh_done(gui.read_state(window.open_device()), "")
        window.show()
        QTest.qWait(50)
        applied = []
        window.apply_button.clicked.disconnect(window.apply_selected)
        window.apply_button.clicked.connect(lambda: applied.append(True))

        for theme in ("dark", "light"):
            window.theme_combo.setCurrentIndex(window.theme_combo.findData(theme))
            for button in (window.edit_button, window.apply_button):
                QTest.mouseMove(window.connection, window.connection.rect().center())
                normal = button.grab().toImage()
                QTest.mouseMove(button, button.rect().center())
                QTest.qWait(20)
                assert button.grab().toImage() != normal

        button = window.apply_button
        hovered = button.grab().toImage()
        QTest.mousePress(button, Qt.MouseButton.LeftButton)
        QTest.qWait(650)
        assert button.isDown() and not applied
        assert button.grab().toImage() != hovered
        QTest.mouseRelease(button, Qt.MouseButton.LeftButton)
        assert applied == [True]

        chip = window.preview_key.chips[0]
        chip.setFocus()
        QTest.keyPress(chip, Qt.Key.Key_Return)
        assert chip.isDown() and not window.preview_plot.is_role_hidden([0])
        QTest.keyRelease(chip, Qt.Key.Key_Return)
        assert window.preview_plot.is_role_hidden([0])
    finally:
        window.quit_from_tray()
        app.processEvents()


def test_compact_tuning_keeps_actions_visible_and_blocks_stale_autoeq(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    (tmp_path / "settings.json").write_text('{"language":"pl","theme":"light"}')
    window = gui.ProfilesWindow(demo=True, library_directory=tmp_path / "profiles")
    try:
        assert window.width() <= window.screen().availableGeometry().width()
        assert window.height() <= window.screen().availableGeometry().height()
        window.resize(840, 620)
        window.show()
        window.switch_source(1)
        panel = window.autoeq_panel
        assert panel.source_filter.y() < panel.mode.y() < panel.search.y()
        panel.add_custom_target_path(gui.HARMAN_TARGET)
        panel.fit_range.setCurrentIndex(3)
        panel.result_entry = panel.current_entry()
        panel.result_range = panel.fit_range.currentData()
        sample = gui.load_profile(gui.BUILTIN_PROFILE, "Bardzo długa nazwa profilu z pomiaru porównawczego AutoEq")
        panel.result = sample
        window.refresh_done(gui.read_state(window.open_device()), "")
        window.update_selection()
        QTest.qWait(60)
        assert window.candidate_profile() == sample
        assert window.apply_button.isVisible() and window.apply_button.isEnabled()
        assert window.apply_button.parentWidget().rect().contains(window.apply_button.geometry())
        window.setMinimumWidth(608)
        window.resize(608, 592)
        QTest.qWait(40)
        actions = (panel.generate, window.save_fit_button, window.edit_button, window.apply_button)
        action_bar = window.apply_button.parentWidget().rect()
        rows: dict[int, int] = {}
        for action in actions:
            rect = action.geometry()
            assert action.isVisible() and action_bar.contains(rect)
            rows[rect.top()] = max(rect.right(), rows.get(rect.top(), 0))
        assert len(rows) > 1
        assert all(right == action_bar.right() for right in rows.values())
        assert window.plot_switcher.isVisible()
        window.plot_view_group.button(1).click()
        assert window.correction_plot.isVisible() and not window.preview_plot.isVisible()

        panel.fit_range.setCurrentIndex(0)
        assert window.candidate_profile() is None
        assert not window.apply_button.isEnabled()
        assert not window.save_fit_button.isEnabled()
        assert "do 2 khz" in window.fit_provenance.text().casefold()
        assert panel.generate.text() == "Przelicz profil"
    finally:
        window.quit_from_tray()
        app.processEvents()
