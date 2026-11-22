"""Testy jednostkowe protokołu HID, walidacji profili i symulatora DAC-a."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

import autoeq_catalog as catalog
import i18n
import moondrop_position as dac
import position_gui as gui
from measurements import fit_to_target

ROOT = Path(__file__).resolve().parents[1]


def test_clamp_i16_bounds() -> None:
    assert dac.clamp_i16(0.0) == 0
    assert dac.clamp_i16(40000.0) == 32767
    assert dac.clamp_i16(-40000.0) == -32768


def test_preamp_payload_and_matching() -> None:
    payload = dac.preamp_payload(-2.5)
    assert len(payload) == 5
    assert payload[0] == dac.OP_WRITE
    assert payload[1] == dac.CMD_PRE_GAIN

    assert dac.preamp_matches(-2.5, -2.5)
    assert not dac.preamp_matches(-2.5, -2.65, allow_half_db=False)
    assert dac.preamp_matches(-2.5, -2.65, allow_half_db=True)


def test_biquad_coefficients_length_and_neutral_pk() -> None:
    coeffs = dac.biquad_coefficients(2, 1000.0, 0.0, 1.0)
    assert len(coeffs) == 20
    # Neutralny filtr PK (0 dB) ma b0=1.0 w formacie Q2.30 (1 << 30).
    b0 = int.from_bytes(coeffs[:4], byteorder="little", signed=True)
    assert b0 == 1 << 30


def test_band_readback_can_include_q30_coefficients(monkeypatch) -> None:
    device = dac.MoondropPosition.__new__(dac.MoondropPosition)
    payload = bytearray(63)
    coefficients = dac.biquad_coefficients(2, 1000.3, 4.12, 1.11)
    payload[7:27] = coefficients
    struct.pack_into("<HhhB", payload, 27, 1000, round(1.11 * 256), round(4.12 * 256), 2)
    monkeypatch.setattr(device, "request", lambda *_args, **_kwargs: payload)
    band = device.read_band(0)
    assert band["freq"] == 1000
    assert "coefficients" not in band
    assert device.read_band(0, include_coefficients=True) == {**band, "coefficients": coefficients}


def test_harman_fit_uses_one_level_offset_and_excludes_upper_treble() -> None:
    profile = gui.load_profile(gui.BUILTIN_PROFILE)
    measured = gui.measured_position()
    eq = gui.response_points(profile, [hz for hz, _ in measured])
    predicted = [(hz, measured_db + eq_db) for (hz, measured_db), (_, eq_db) in zip(measured, eq, strict=True)]
    fit = fit_to_target(predicted, profile.target_curve)
    assert (fit.low_hz, fit.high_hz) == (20, 10000)
    assert fit.rms_db == pytest.approx(0.72, abs=0.01)
    assert fit.peak_hz == pytest.approx(9300, abs=150)
    raised = [(hz, db + (30 if hz > 11000 else 5)) for hz, db in predicted]
    raised_fit = fit_to_target(raised, profile.target_curve)
    assert raised_fit.rms_db == pytest.approx(fit.rms_db)
    assert raised_fit.offset_db == pytest.approx(fit.offset_db + 5)


def test_validate_profile_accepts_example_and_rejects_invalid() -> None:
    bands, meta = dac.load_eq_file(str(ROOT / "dane" / "przyklad-eq.json"))
    dac.validate_profile(bands, meta.get("slot"), meta.get("preamp"))

    with pytest.raises(dac.HidError):
        dac.validate_profile([], 7, 0.0)

    bad_band = [{**bands[0], "freq": 5}]
    with pytest.raises(dac.HidError):
        dac.validate_profile(bad_band, 7, 0.0)


def test_parse_eqapo(tmp_path: Path) -> None:
    eq_file = tmp_path / "sample.txt"
    eq_file.write_text(
        "Preamp: -3.2 dB\n"
        "Filter 1: ON PK Fc 105 Hz Gain 2.4 dB Q 0.70\n"
        "Filter 2: OFF PK Fc 500 Hz Gain -1.0 dB Q 1.00\n"
        "Filter 3: ON PK Fc 4200 Hz Gain -3.1 dB Q 2.50\n",
        encoding="utf-8",
    )
    bands, preamp = dac.parse_eqapo(str(eq_file))
    assert preamp == pytest.approx(-3.2)
    assert len(bands) == 2
    assert bands[0]["freq"] == 105
    assert bands[1]["type"] == "PK"


def test_demo_device_apply_and_live_eq_restore() -> None:
    dev = gui.DemoDevice()
    assert dev.slot() == 0
    open_demo = lambda _path=None: dev  # noqa: E731

    profile = gui.load_profile(ROOT / "dane" / "profile" / "moondrop-position-harman.json")
    state = gui.apply_profile(open_demo, "demo", profile)
    assert state.slot == dac.CUSTOM_SLOT
    assert len(state.bands) == dac.BAND_COUNT
    actual = gui.profile_from_readback(state)
    assert actual.bands[0]["freq"] == round(profile.bands[0]["freq"])
    assert actual.coefficients[0] == gui.coefficients_for_band(profile.bands[0])
    assert actual.coefficients[0] != gui.coefficients_for_band(actual.bands[0])
    assert gui.response_points(actual, [30, 1000, 9300]) == gui.response_points(profile, [30, 1000, 9300])

    snapshot = gui.begin_live_eq(open_demo, "demo")
    edited = gui.custom_profile(
        "Test Live",
        dac.CUSTOM_SLOT,
        [{**b, "gain": 1.5} if i == 0 else b for i, b in enumerate(state.bands)],
        -4.0,
    )
    gui.listen_live_eq(open_demo, snapshot, edited, profile, state.preamp)
    assert dev.preamp() == pytest.approx(-4.0)

    gui.end_live_eq(open_demo, snapshot, edited)
    restored = gui.read_state(dev)
    assert restored.slot == dac.CUSTOM_SLOT
    assert dac.preamp_matches(restored.preamp, profile.preamp or 0.0, allow_half_db=True)


def test_parse_alsa_stream0_and_demo_playback_quality() -> None:
    sample_stream0 = (
        "MOONDROP MOONDROP Position at usb-0000:00:14.0-1, high speed : USB Audio\n\n"
        "Playback:\n"
        "  Status: Running\n"
        "    Interface = 2\n"
        "    Altset = 3\n"
        "    Momentary freq = 96000 Hz (0xc.0000)\n"
        "  Interface 2\n"
        "    Altset 1\n"
        "    Format: S16_LE\n"
        "    Channels: 2\n"
        "  Interface 2\n"
        "    Altset 3\n"
        "    Format: S32_LE\n"
        "    Channels: 2\n"
        "Capture:\n"
        "  Status: Stop\n"
    )
    parsed = gui.parse_alsa_stream0(sample_stream0)
    assert parsed["altset"] == 3
    assert parsed["audio_format"] == "S32_LE"
    assert parsed["channels"] == 2
    assert parsed["rate_hz"] == 96000
    assert parsed["running"] is True

    demo_quality = gui.read_playback_quality(demo=True, demo_forced_rate=192000)
    assert demo_quality.altset == 3
    assert demo_quality.audio_format == "S32_LE"
    assert demo_quality.rate_hz == 192000
    assert gui.format_rate_khz(44100) == "44,1 kHz"
    assert gui.format_rate_khz(384000) == "384 kHz"


def test_autoeq_catalog_headphone_form() -> None:
    iem = catalog.describe_path("measurements/oratory1990/data/in-ear/MOONDROP Position.csv")
    over = catalog.describe_path("measurements/oratory1990/data/over-ear/Sennheiser HD 600.csv")
    target = catalog.describe_path("targets/Harman in-ear 2019.csv")
    assert iem is not None and catalog.headphone_form(iem) == "in-ear"
    assert over is not None and catalog.headphone_form(over) == "over-ear"
    assert target is not None and catalog.headphone_form(target) == "other"
    assert catalog.measurement_source(iem) == "oratory1990"
    assert catalog.measurement_source(target) == "AutoEq"


def test_i18n_languages_switch_and_extensibility(tmp_path: Path) -> None:
    langs = dict(i18n.available_languages())
    assert "pl" in langs
    assert "en" in langs

    assert i18n.detect_system_language("pl_PL.UTF-8") == "pl"
    assert i18n.detect_system_language("en_US.UTF-8") == "en"
    assert i18n.detect_system_language("fr_FR.UTF-8") == "en"

    i18n.set_language("en")
    assert i18n.tr("tab.tuning") == "Tuning"
    assert i18n.tr("tab.device") == "Device"

    i18n.set_language("pl")
    assert i18n.tr("tab.tuning") == "Strojenie"
    assert i18n.tr("tab.device") == "Urządzenie"

    # Nowy plik tłumaczenia w katalogu i18n jest wykrywany automatycznie.
    custom_dir = tmp_path / "i18n"
    custom_dir.mkdir()
    (custom_dir / "pl.json").write_text(json.dumps({"_meta": {"name": "Polski"}}), encoding="utf-8")
    (custom_dir / "de.json").write_text(json.dumps({"_meta": {"name": "Deutsch"}}), encoding="utf-8")
    custom_langs = dict(i18n.available_languages(custom_dir))
    assert custom_langs["de"] == "Deutsch"


def test_autoeq_read_github_https_fallback(monkeypatch) -> None:
    class FakeResponse:
        def __init__(self, payload: bytes) -> None:
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_exc) -> None:
            pass

        def read(self, _n: int) -> bytes:
            return self.payload

    monkeypatch.setattr(catalog.shutil, "which", lambda _cmd: None)
    monkeypatch.setattr(catalog.urllib.request, "urlopen", lambda _req, timeout=18: FakeResponse(b'{"tree": []}'))
    data = catalog.read_github("repos/jaakkopasanen/AutoEq/git/trees/master", 1024)
    assert data == b'{"tree": []}'


def test_shelves_supported_in_custom_profile_and_eq_fit() -> None:
    import eq_fit

    bands = [
        {"band": 1, "type": "LSQ", "freq": 105, "gain": 3.0, "q": 0.7},
        {"band": 2, "type": "HSQ", "freq": 10000, "gain": -2.5, "q": 0.7},
        *[{"band": i, "type": "PK", "freq": 1000 * (i - 2), "gain": 0.0, "q": 1.0} for i in range(3, 9)],
    ]
    profile = gui.custom_profile("Shelves Test", gui.dac.CUSTOM_SLOT, bands, -3.1)
    assert profile.bands[0]["type"] == "LSQ"
    assert profile.bands[1]["type"] == "HSQ"

    cfg_shelves = eq_fit.build_peq_config(8, 20.0, 20000.0, 0.1, 10.0, -12.0, 6.0, 0.008, None, with_shelves=True)
    assert [f["type"] for f in cfg_shelves["filters"]] == ["LOW_SHELF", "HIGH_SHELF", *(["PEAKING"] * 6)]

    cfg_pk = eq_fit.build_peq_config(8, 20.0, 20000.0, 0.1, 10.0, -12.0, 6.0, 0.008, None, with_shelves=False)
    assert [f["type"] for f in cfg_pk["filters"]] == ["PEAKING"] * 8
