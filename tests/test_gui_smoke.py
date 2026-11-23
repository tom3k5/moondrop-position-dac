"""Testy smoke GUI PySide6 w trybie offscreen i symulatora (--demo)."""

from __future__ import annotations

import json
import os
import re
import sys
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QRect, QStandardPaths, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QMessageBox, QStyle, QStyleOptionComboBox, QWidget

import dsp_control as gui


def test_diagnose_serializes_dsp_coefficients(monkeypatch, capsys) -> None:
    demo = gui.DemoDevice()
    monkeypatch.setattr(gui, "open_dac", lambda: demo)
    monkeypatch.setattr(sys, "argv", ["dsp_control.py", "--diagnose"])
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
        assert gui.APP_VERSION in window.guide_version_label.text()
        assert window.guide_version_label.toolTip()
        assert f"App: {gui.tr('app.title')} {gui.APP_VERSION}" in window.diagnostic_summary()
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


def test_guide_fits_at_start_with_larger_font(tmp_path: Path, monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    original_font = app.font()
    app.setFont(QFont("DejaVu Sans", 12))
    (tmp_path / "settings.json").write_text('{"language":"pl","theme":"dark"}')
    with monkeypatch.context() as roomy_screen:
        roomy_screen.setattr(gui, "size_to_screen", QWidget.resize)
        window = gui.ProfilesWindow(demo=True, library_directory=tmp_path / "profiles")
    try:
        window.show()
        QTest.qWait(50)
        start_size = window.size()
        for index in (1, 2):
            window.tabs.setCurrentIndex(index)
            QTest.qWait(50)
            assert window.tabs.currentWidget().verticalScrollBar().maximum() == 0
            assert window.size() == start_size
    finally:
        window.quit_from_tray()
        app.processEvents()
        app.setFont(original_font)


def test_source_labels_fit_compact_and_wide_windows(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    original_font = app.font()
    app.setFont(QFont("DejaVu Sans", 13))
    (tmp_path / "settings.json").write_text('{"language":"pl","theme":"dark"}')
    window = gui.ProfilesWindow(demo=True, library_directory=tmp_path / "profiles")
    try:
        window.resize(720, 592)
        window.show()
        window.source_panel.parentWidget().setSizes([245, 400])
        QTest.qWait(60)
        buttons = list(window.source_group.buttons())
        assert [button.text() for button in buttons] == ["Profile", "AutoEq"]
        assert [button.accessibleName() for button in buttons] == ["Moje profile", "Katalog AutoEq"]
        assert buttons[1].toolTip().startswith("Katalog AutoEq")
        assert window.add_button.text() == "Dodaj"
        assert window.add_button.toolTip()
        assert buttons[0].geometry().right() < buttons[1].geometry().left()
        for button in buttons:
            assert button.width() >= button.fontMetrics().horizontalAdvance(button.text()) + 20
            assert window.source_panel.rect().contains(button.geometry())
        window.refresh_done(gui.read_state(window.open_device()), "")
        QTest.qWait(60)
        assert window.connection.text() == window.connection.accessibleName()
        assert "MOONDROP:Gravity Position" in window.connection.text()

        window.language_combo.setCurrentIndex(window.language_combo.findData("en"))
        assert [button.text() for button in buttons] == ["Profiles", "AutoEq"]
        assert window.add_button.text() == "Add"
        window.resize(1140, 820)
        window.source_panel.parentWidget().setSizes([365, 700])
        QTest.qWait(60)
        assert [button.text() for button in buttons] == ["My profiles", "AutoEq catalog"]
        assert window.windowTitle() == "DSP Control"
    finally:
        window.quit_from_tray()
        app.processEvents()
        app.setFont(original_font)


def test_device_picker_uses_selected_demo_model_and_clears_disconnected_state(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    (tmp_path / "settings.json").write_text('{"language":"en","theme":"dark"}')
    window = gui.ProfilesWindow(demo=True, library_directory=tmp_path / "profiles")
    first = gui.DemoDevice()
    second = gui.DemoDevice()
    second.path = "second-demo"
    second.model_name = "USB DAC with an intentionally long name for compact layout verification"
    available = [first, second]
    window.list_devices = lambda: [gui.DeviceChoice(device.path, device.model_name) for device in available]
    window.open_device = lambda target: next((device for device in available if device.path == target), None)

    def wait_until(predicate):
        for _ in range(100):
            QTest.qWait(20)
            if predicate():
                return
        pytest.fail("Device UI did not complete the refresh")

    try:
        window.resize(720, 592)
        window.show()
        window.tabs.setCurrentIndex(1)
        wait_until(lambda: window.device_select.count() == 3)
        assert window.state is None and window.device_select.isEnabled()
        window.device_select.setCurrentIndex(2)
        wait_until(lambda: window.state is not None)
        assert window.state.path == second.path
        assert second.model_name in window.connection.accessibleName()
        assert second.model_name in window.device_select.itemData(2, Qt.ItemDataRole.ToolTipRole)
        assert window.heading.geometry().right() < window.connection.geometry().left()
        assert window.rect().contains(window.connection.geometry())

        available.remove(second)
        window.refresh()
        wait_until(lambda: window.state is None and window.device_select.count() == 2)
        assert not window.apply_button.isEnabled()
        window.device_select.setCurrentIndex(1)
        wait_until(lambda: window.state is not None)
        assert window.state.path == first.path
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

        with monkeypatch.context() as roomy_screen:
            roomy_screen.setattr(gui, "size_to_screen", QWidget.resize)
            editor = gui.EqualizerDialog(window, sample, sample, window.factory_profile, device_path=None)
        editor.show()
        QTest.qWait(50)
        assert editor.editor_scroll.verticalScrollBar().maximum() == 0
        for field in editor.findChildren(QAbstractSpinBox):
            assert field.lineEdit().textMargins().left() >= 6
        editor.preamp.setValue(editor.preamp.minimum())
        preamp_text = editor.preamp.lineEdit()
        margins = preamp_text.textMargins()
        assert preamp_text.fontMetrics().horizontalAdvance(preamp_text.text()) + margins.left() + margins.right() <= (
            preamp_text.width()
        )
        assert editor.plot.correction and editor.plot.interactive
        assert not editor.acoustic_plot.correction
        assert not editor.upload.autoDefault()
        for kind, frequency, gain, q in editor.rows:
            assert {field.font().pointSizeF() for field in (kind, frequency, gain, q)} == {kind.font().pointSizeF()}
            assert abs(kind.height() - max(frequency.height(), gain.height(), q.height())) <= 1
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
        window.autoeq_panel.preview_timer.stop()
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
            window.last_applied_profile = None
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

            actions = [plot_geometry(button) for button in (window.edit_button, window.apply_button)]
            window.applying_profile = sample
            window.apply_done(window.state, "")
            QTest.qWait(40)
            assert window.apply_status.isVisible()
            assert window.apply_status.text().startswith("DAC -4.50 dB")
            assert "-4.50 dB" in window.apply_status.accessibleDescription()
            assert "-4.66 dB" in window.apply_status.accessibleDescription()
            assert window.feedback.isHidden()
            assert plot_geometry(window.preview_plot) == reference[0]
            assert [plot_geometry(button) for button in (window.edit_button, window.apply_button)] == actions

            for item in (window.flat_item, window.factory_item):
                window.profiles.setCurrentItem(item)
                QTest.qWait(40)
                assert plot_geometry(window.preview_plot) == reference[0]
                if window.correction_plot.isVisible():
                    assert plot_geometry(window.correction_plot) == reference[1]
                assert not window.fit_detail_button.isEnabled()
                assert window.apply_button.isEnabled()
                assert window.apply_status.isHidden()

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


def test_app_version_matches_release_metadata_and_translates(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    pyproject_version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    metainfo_tree = ET.parse(root / "flatpak/pl.innovibe.DspControl.metainfo.xml")
    metainfo_version = metainfo_tree.find("./releases/release").attrib["version"]
    assert gui.APP_VERSION == pyproject_version == metainfo_version

    app = QApplication.instance() or QApplication([])
    (tmp_path / "settings.json").write_text('{"language":"en","theme":"dark"}')
    window = gui.ProfilesWindow(demo=True, library_directory=tmp_path / "profiles")
    try:
        assert not hasattr(window, "version_badge")
        assert window.guide_version_label.text() == f"Version {gui.APP_VERSION} · MIT License"
        window.show()
        window.tabs.setCurrentIndex(2)
        QTest.qWait(40)
        assert (
            window.guide_version_label.geometry().bottom() == window.guide_version_label.parentWidget().rect().bottom()
        )
        assert window.guide_version_label.geometry().right() == window.guide_version_label.parentWidget().rect().right()
        window.language_combo.setCurrentIndex(window.language_combo.findData("pl"))
        QTest.qWait(30)
        assert window.guide_version_label.text() == f"Wersja {gui.APP_VERSION} · Licencja MIT"
        assert re.search(rf"\b{re.escape(gui.APP_VERSION)}\b", window.diagnostic_summary())
    finally:
        window.quit_from_tray()
        app.processEvents()


def test_tuning_plots_keep_geometry_with_dynamic_scale(tmp_path: Path, monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    (tmp_path / "settings.json").write_text('{"language":"pl","theme":"dark"}')
    window = gui.ProfilesWindow(demo=True, library_directory=tmp_path / "profiles")
    try:
        window.resize(1140, 820)
        window.show()
        QTest.qWait(50)

        def plot_geometry(plot: gui.ResponsePlot):
            return plot.mapTo(window, QPoint()), plot.size()

        baseline = (plot_geometry(window.preview_plot), plot_geometry(window.correction_plot))
        assert window.correction_key.chips[1].x() < window.correction_key.chips[0].x()
        assert window.preamp_summary.x() >= window.correction_key.geometry().right()
        edit_x = window.edit_button.mapTo(window, QPoint()).x()
        apply_x = window.apply_button.mapTo(window, QPoint()).x()
        apply_size = window.apply_button.size()
        add_button_height = window.add_button.height()
        add_button_y = window.add_button.mapTo(window, QPoint()).y()

        # Selecting a group header hides all preview action buttons and empties profile_info.
        window.profiles.setCurrentRow(0)
        QTest.qWait(50)
        assert (plot_geometry(window.preview_plot), plot_geometry(window.correction_plot)) == baseline

        window.source_group.button(1).click()
        panel = window.autoeq_panel
        QTest.qWait(40)
        assert panel.source_filter.y() < panel.mode.y() < panel.fit_controls.y() < panel.search.y()
        assert panel.search.y() < panel.catalog_list.y()
        assert panel.catalog_button.height() == add_button_height
        assert panel.catalog_button.mapTo(window, QPoint()).y() == add_button_y
        assert panel.status.x() > panel.catalog_button.geometry().right()
        with monkeypatch.context() as pending:
            pending.setattr(panel, "start_job", lambda *_: None)
            panel.download_catalog()
            QTest.qWait(20)
            assert panel.catalog_progress.isVisible() and panel.catalog_progress.wordWrap()
            assert panel.catalog_progress.text() == gui.tr("autoeq.loading_catalog")
            assert panel.catalog_progress.parentWidget() is panel.catalog_list
            assert panel.catalog_list.contentsRect().contains(panel.catalog_progress.geometry())
            assert not panel.status.text()
        cached_entries = list(panel.entries)
        cached_sources = [panel.source_filter.itemText(i) for i in range(panel.source_filter.count())]
        panel.catalog_downloaded(None, "GitHub API zwróciło błąd HTTP 403.")
        QTest.qWait(20)
        assert not panel.catalog_progress.isVisible()
        assert panel.catalog_error.isVisible()
        assert panel.catalog_error.parentWidget() is panel.catalog_list
        assert panel.catalog_list.contentsRect().contains(panel.catalog_error.geometry())
        assert panel.targets.geometry().bottom() < panel.catalog_error.geometry().top()
        assert panel.catalog_error.accessibleName() == "Błąd"
        assert "HTTP 403" in panel.catalog_error.toolTip()
        assert panel.entries == cached_entries
        assert [panel.source_filter.itemText(i) for i in range(panel.source_filter.count())] == cached_sources
        opened = []
        monkeypatch.setattr(window, "open_external_url", opened.append)
        QTest.mouseClick(
            panel.catalog_error, Qt.MouseButton.LeftButton, pos=QPoint(16, panel.catalog_error.height() // 2)
        )
        assert len(opened) == 1
        assert opened[0].startswith(f"{gui.GITHUB_REPO_URL}/issues/new?")
        assert "template=bug_report.yml" in opened[0] and "HTTP%20403" in opened[0]
        panel.set_catalog_error("")
        fit_option = QStyleOptionComboBox()
        panel.fit_range.initStyleOption(fit_option)
        fit_rect = panel.fit_range.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox, fit_option, QStyle.SubControl.SC_ComboBoxEditField, panel.fit_range
        )
        assert fit_rect.width() >= panel.fit_range.fontMetrics().horizontalAdvance(panel.fit_range.currentText())
        extreme_entry = gui.catalog.Entry(
            "1MORE Fit Open Earbuds S50 Very Long Name That Would Wrap Without Eliding",
            "HypetheSonics · in-ear/GRAS RA0045 · extra long measurement description",
            "model",
            "test/extreme.csv",
            False,
        )
        panel.entries = [extreme_entry]
        panel.update_results()
        panel.preview_timer.stop()
        panel.preview_entry = extreme_entry
        panel.preview_curve = [(20.0, -40.0), (1000.0, 0.0), (10000.0, 12.0), (20000.0, -65.0)]
        window.update_selection()
        QTest.qWait(50)
        assert (plot_geometry(window.preview_plot), plot_geometry(window.correction_plot)) == baseline
        assert window.preview_plot.plot_bounds[1] < 30
        assert panel.generate.isVisible()
        assert panel.generate.size() == apply_size
        compute_geo = (panel.generate.mapTo(window, QPoint()), panel.generate.size())
        assert compute_geo[0].x() == apply_x
        assert apply_size.height() == window.edit_button.height()

        # Running a fresh fit replaces "Oblicz profil" with "Anuluj obliczenia" in the exact same box.
        panel.fit_active = True
        panel.update_actions()
        QTest.qWait(40)
        assert panel.cancel.isVisible()
        assert (panel.cancel.mapTo(window, QPoint()), panel.cancel.size()) == compute_geo
        panel.fit_active = False

        sample = gui.load_profile(gui.BUILTIN_PROFILE, "Harman In-Ear 2019")
        panel.result_entry = panel.preview_entry
        panel.result_range = panel.fit_range.currentData()
        panel.result = gui.replace(sample, name=panel.preview_entry.name, source="AutoEq · HypetheSonics")
        panel.update_actions()
        window.update_selection()
        QTest.qWait(50)
        assert (plot_geometry(window.preview_plot), plot_geometry(window.correction_plot)) == baseline
        assert not panel.generate.isVisible()
        assert not panel.cancel.isVisible()
        assert window.save_fit_button.isVisible()
        assert window.edit_button.isVisible()
        assert window.apply_button.isVisible()
        assert window.edit_button.mapTo(window, QPoint()).x() == edit_x
        assert window.apply_button.size() == compute_geo[1]
        assert (window.apply_button.mapTo(window, QPoint()), window.apply_button.size()) == compute_geo
        save_geo = (window.save_fit_button.mapTo(window, QPoint()), window.save_fit_button.size())

        # Saving changes "Zapisz profil" -> "Zapisano" without shifting adjacent buttons.
        window.save_fit_button.setText(gui.tr("actions.saved"))
        window.save_fit_button.setEnabled(False)
        QTest.qWait(40)
        assert (window.save_fit_button.mapTo(window, QPoint()), window.save_fit_button.size()) == save_geo
        assert window.edit_button.mapTo(window, QPoint()).x() == edit_x
        assert (window.apply_button.mapTo(window, QPoint()), window.apply_button.size()) == compute_geo

        # Changing range invalidates ready_result() and restores primary "Przelicz profil" in the exact right slot.
        panel.fit_range.setCurrentIndex(2)
        QTest.qWait(50)
        assert (plot_geometry(window.preview_plot), plot_geometry(window.correction_plot)) == baseline
        assert panel.generate.isVisible()
        assert panel.generate.text() == "Przelicz profil"
        assert (panel.generate.mapTo(window, QPoint()), panel.generate.size()) == compute_geo
        assert not window.save_fit_button.isVisible()
        assert not window.edit_button.isVisible()
        assert not window.apply_button.isVisible()

        panel.fit_active = True
        panel.update_actions()
        QTest.qWait(40)
        assert panel.cancel.isVisible()
        assert (panel.cancel.mapTo(window, QPoint()), panel.cancel.size()) == compute_geo
        panel.fit_active = False
    finally:
        window.quit_from_tray()
        app.processEvents()


def test_device_form_uses_shared_alignment_and_responsive_actions(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    (tmp_path / "settings.json").write_text('{"language":"en","theme":"dark"}')
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

        combo = window.sample_rate_combo
        for lang, automatic in (("pl", "Automatyczna (PipeWire)"), ("en", "Automatic (PipeWire)")):
            window.language_combo.setCurrentIndex(window.language_combo.findData(lang))
            QTest.qWait(50)
            assert combo.currentText() == automatic
            option = QStyleOptionComboBox()
            combo.initStyleOption(option)
            text_rect = combo.style().subControlRect(
                QStyle.ComplexControl.CC_ComboBox, option, QStyle.SubControl.SC_ComboBoxEditField, combo
            )
            assert all(
                text_rect.width() >= combo.fontMetrics().horizontalAdvance(combo.itemText(index))
                for index in range(combo.count())
            )
            assert window.refresh_rate_button.geometry().right() <= window.playback_box.contentsRect().right()
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
        actions = (window.save_fit_button, window.edit_button, window.apply_button)
        action_bar = window.apply_button.parentWidget().rect()
        rows: dict[int, int] = {}
        assert not panel.generate.isVisible()
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
        assert not window.apply_button.isVisible()
        assert not window.edit_button.isVisible()
        assert not window.save_fit_button.isVisible()
        assert "do 2 khz" in window.fit_provenance.text().casefold()
        assert panel.generate.isVisible()
        assert panel.generate.text() == "Przelicz profil"
    finally:
        window.quit_from_tray()
        app.processEvents()


def test_apply_and_restore_previous_profile(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    (tmp_path / "settings.json").write_text('{"language":"pl","theme":"dark"}')
    window = gui.ProfilesWindow(demo=True, library_directory=tmp_path / "profiles")

    def wait_for(predicate) -> None:
        for _ in range(200):
            QTest.qWait(25)
            app.processEvents()
            if predicate():
                return
        raise AssertionError("Timed out waiting for async demo operation")

    try:
        window.resize(1024, 757)
        window.show()
        wait_for(lambda: window.state is not None)
        assert window.state.slot == 0

        harman_row = next(
            row
            for row in range(window.profiles.count())
            if (p := window.profiles.item(row).data(gui.PROFILE_ROLE)) is not None and p.name == "Harman In-Ear 2019"
        )
        flat_row = next(
            row
            for row in range(window.profiles.count())
            if (p := window.profiles.item(row).data(gui.PROFILE_ROLE)) is not None
            and p.slot == gui.dac.CUSTOM_SLOT
            and p.preamp == 0
        )

        window.profiles.setCurrentRow(harman_row)
        QTest.qWait(40)
        assert window.apply_button.text() == "Wgraj do DAC-a"
        assert window.apply_button.isEnabled()
        initial_apply_geo = (window.apply_button.mapTo(window, QPoint()), window.apply_button.size())
        initial_edit_geo = (window.edit_button.mapTo(window, QPoint()), window.edit_button.size())

        # Flash Harman over Factory EQ -> button becomes "Przywróć poprzedni" in the exact same box.
        window.apply_button.click()
        wait_for(lambda: not window.command_active and window.state.slot == gui.dac.CUSTOM_SLOT)
        assert window.state.slot == gui.dac.CUSTOM_SLOT
        assert window.apply_button.text() == "Przywróć poprzedni"
        assert window.apply_button.isEnabled()
        assert (window.apply_button.mapTo(window, QPoint()), window.apply_button.size()) == initial_apply_geo
        assert (window.edit_button.mapTo(window, QPoint()), window.edit_button.size()) == initial_edit_geo

        # Selecting a different profile still offers "Wgraj do DAC-a"; returning restores "Przywróć poprzedni".
        window.profiles.setCurrentRow(flat_row)
        QTest.qWait(30)
        assert window.apply_button.text() == "Wgraj do DAC-a"
        window.profiles.setCurrentRow(harman_row)
        QTest.qWait(30)
        assert window.apply_button.text() == "Przywróć poprzedni"

        # Clicking "Przywróć poprzedni" restores Factory EQ (slot 0) and reverts button to "Wgraj do DAC-a".
        window.apply_button.click()
        wait_for(lambda: not window.command_active and window.state.slot == 0)
        assert window.state.slot == 0
        assert window.apply_button.text() == "Wgraj do DAC-a"
        assert window.apply_button.isEnabled()

        # Also verify restoring from Custom -> Custom preserves exact Custom slot bands & preamp.
        window.profiles.setCurrentRow(flat_row)
        QTest.qWait(30)
        window.apply_button.click()
        wait_for(lambda: not window.command_active and window.state.slot == gui.dac.CUSTOM_SLOT)
        window.profiles.setCurrentRow(harman_row)
        QTest.qWait(30)
        window.apply_button.click()
        wait_for(lambda: not window.command_active and window.state.preamp != 0)
        assert window.apply_button.text() == "Przywróć poprzedni"
        window.apply_button.click()
        wait_for(lambda: not window.command_active and window.state.preamp == 0)
        assert window.state.slot == gui.dac.CUSTOM_SLOT
        assert window.state.preamp == 0
        assert window.apply_button.text() == "Wgraj do DAC-a"
    finally:
        window.quit_from_tray()
        app.processEvents()


def test_autoeq_clean_install_and_offline_behavior(tmp_path: Path, monkeypatch) -> None:
    import urllib.error

    app = QApplication.instance() or QApplication([])
    (tmp_path / "settings.json").write_text('{"language":"pl","theme":"dark"}')

    def offline_open(*_args, **_kwargs):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(gui.catalog.urllib.request, "urlopen", offline_open)
    window = gui.ProfilesWindow(demo=True, library_directory=tmp_path / "profiles")
    try:
        window.resize(1080, 760)
        window.show()
        window.switch_source(1)
        panel = window.autoeq_panel
        panel.preview_timer.stop()

        # Czysta instalacja bez cache ma wbudowany indeks modeli i źródeł od pierwszego uruchomienia.
        assert not panel.index_path.exists()
        assert len(panel.entries) > 6000
        assert panel.source_filter.count() > 10
        assert panel.target_model.rowCount() > 6000

        # Przełączenie na wbudowane cele MIT działa w pełni offline.
        panel.mode.setCurrentIndex(panel.mode.findData("target"))
        panel.search.setText("JM-1 with Harman filters")
        QTest.qWait(30)
        assert panel.target_model.rowCount() >= 1
        panel.load_selected_preview()
        for _ in range(40):
            QTest.qWait(20)
            app.processEvents()
            if panel.preview_curve:
                break
        assert len(panel.preview_curve) > 50

        # Nieudane odświeżenie offline zachowuje istniejący katalog i zgłasza błąd.
        before_entries = list(panel.entries)
        panel.download_catalog()
        for _ in range(40):
            QTest.qWait(20)
            app.processEvents()
            if panel.catalog_error.isVisible():
                break
        assert panel.catalog_error.isVisible()
        assert panel.entries == before_entries

        # Próba obliczenia niesbuforowanego modelu offline zwraca czytelny błąd i nie niszczy listy.
        panel.mode.setCurrentIndex(panel.mode.findData("all"))
        panel.search.setText("MOONDROP")
        QTest.qWait(30)
        panel.preview_timer.stop()
        assert panel.target_model.rowCount() > 0
        panel.generate_profile()
        for _ in range(40):
            QTest.qWait(20)
            app.processEvents()
            if not panel.fit_active:
                break
        assert not panel.fit_active
        assert panel.fit_status.isVisible() and panel.fit_status.text()
        assert panel.entries == before_entries
    finally:
        window.quit_from_tray()
        app.processEvents()


@pytest.mark.parametrize("language", ["pl", "en"])
def test_compact_autoeq_pl_en_large_font(tmp_path: Path, language: str) -> None:
    app = QApplication.instance() or QApplication([])
    original_font = app.font()
    large_font = QFont(original_font)
    large_font.setPointSize(max(13, original_font.pointSize() + 3))
    app.setFont(large_font)
    (tmp_path / "settings.json").write_text(json.dumps({"language": language, "theme": "dark"}))
    window = gui.ProfilesWindow(demo=True, library_directory=tmp_path / "profiles")
    try:
        window.setMinimumWidth(640)
        window.resize(640, 620)
        window.show()
        window.switch_source(1)
        panel = window.autoeq_panel
        panel.preview_timer.stop()
        QTest.qWait(40)
        assert window.plot_switcher.isVisible()
        assert panel.source_filter.y() < panel.mode.y() < panel.fit_controls.y() < panel.search.y()
        assert panel.search.y() < panel.catalog_list.y()
        assert panel.catalog_button.isVisible()
        assert panel.generate.isVisible()
        assert panel.generate.parentWidget().rect().contains(panel.generate.geometry())
        for combo in (panel.source_filter, panel.mode, panel.fit_range):
            assert combo.width() <= panel.width()
        for tab_idx in (0, 1, 2):
            window.tabs.setCurrentIndex(tab_idx)
            QTest.qWait(20)
            assert window.width() == 640
    finally:
        window.quit_from_tray()
        app.setFont(original_font)
        app.processEvents()
