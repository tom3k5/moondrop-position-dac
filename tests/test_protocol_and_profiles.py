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


@pytest.mark.parametrize(("kind", "gain"), [("LSQ", 12), ("LSQ", -12), ("HSQ", -12)])
def test_steep_shelves_have_damped_poles_and_requested_gain(kind: str, gain: int) -> None:
    band = {"band": 1, "type": kind, "freq": 1000, "gain": gain, "q": 10}
    code = dac.TYPE_TO_CODE[kind]
    coefficients = dac.biquad_coefficients(code, 1000, gain, 10, for_write=True)
    assert coefficients != dac.biquad_coefficients(code, 1000, gain, 5.1, for_write=True)
    _, _, _, negative_a1, negative_a2 = struct.unpack("<5i", coefficients)
    # Kryterium Jury dla mianownika drugiego rzędu po kwantyzacji Q2.30.
    assert abs(negative_a2) < dac.COEFF_SCALE
    assert dac.COEFF_SCALE - negative_a2 > abs(negative_a1)
    points = gui.response_points(gui.Profile("Shelf", 7, [band], 0), [20, 1000, 47000])
    low, high = (gain, 0) if kind == "LSQ" else (0, gain)
    assert [level for _, level in points] == pytest.approx([low, gain / 2, high], abs=0.02)


def test_unrepresentable_steep_shelf_leaves_device_state_intact() -> None:
    dev = gui.DemoDevice()
    bands = gui.default_custom_bands()
    bands[-1].update(type="HSQ", freq=1000, gain=12, q=10)
    original = dev.custom_coefficients[:]
    with pytest.raises(dac.HidError, match=r"Q2\.30"):
        dac.write_profile(dev, bands, -3)
    assert dev.slot() == 0
    assert dev.custom_coefficients == original


def test_apply_replaces_an_old_steep_shelf_and_skips_a_matching_one(monkeypatch) -> None:
    dev = gui.DemoDevice()
    dev.set_slot(dac.CUSTOM_SLOT)
    bands = gui.default_custom_bands()
    bands[0].update(type="LSQ", freq=1000, gain=12, q=10)
    profile = gui.custom_profile("Steep shelf", dac.CUSTOM_SLOT, bands, 0.0)
    dev.custom_bands = [dac.quantized_band(band) for band in bands]
    # Stary zapis miał bieguny bez tłumienia, ale te same parametry pasma.
    coefficients = gui.coefficients_for_band(bands[0])
    dev.custom_coefficients[0] = coefficients[:-4] + struct.pack("<i", -(1 << 30))
    saves = []
    monkeypatch.setattr(dev, "save", lambda: saves.append(True))
    monkeypatch.setattr(dac.time, "sleep", lambda _: None)

    assert not profile.matches(gui.read_state(dev))
    state = gui.apply_profile(lambda _path: dev, "demo", profile)
    assert state.coefficients[0] == coefficients
    assert profile.matches(state)
    gui.apply_profile(lambda _path: dev, "demo", profile)
    assert saves == [True]


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
    assert restored.coefficients == state.coefficients


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


def _git_object(obj_type: int, payload: bytes) -> tuple[str, bytes]:
    import hashlib

    names = {catalog.OBJ_COMMIT: "commit", catalog.OBJ_TREE: "tree", catalog.OBJ_BLOB: "blob"}
    sha = hashlib.sha1(f"{names[obj_type]} {len(payload)}\0".encode() + payload).hexdigest()
    return sha, payload


def _tree_payload(items: list[tuple[str, str, str]]) -> bytes:
    return b"".join(f"{mode} {name}\0".encode() + bytes.fromhex(sha) for mode, name, sha in items)


def _pack_v2(entries: list[tuple[int, bytes]]) -> bytes:
    import hashlib
    import struct
    import zlib

    body = bytearray(b"PACK")
    body.extend(struct.pack(">II", 2, len(entries)))
    for obj_type, data in entries:
        size = len(data)
        first = (obj_type << 4) | (size & 0x0F)
        size >>= 4
        if size:
            first |= 0x80
        body.append(first)
        while size:
            part = size & 0x7F
            size >>= 7
            if size:
                part |= 0x80
            body.append(part)
        body.extend(zlib.compress(data))
    body.extend(hashlib.sha1(body).digest())
    return bytes(body)


def test_autoeq_download_index_uses_git_smart_http_without_rest_api(tmp_path: Path, monkeypatch) -> None:
    blob_sha = "11" * 20
    target_sha = "22" * 20
    in_ear_sha, in_ear_tree = _git_object(catalog.OBJ_TREE, _tree_payload([("100644", "Test IEM.csv", blob_sha)]))
    data_sha, data_tree = _git_object(catalog.OBJ_TREE, _tree_payload([("40000", "in-ear", in_ear_sha)]))
    src_sha, src_tree = _git_object(catalog.OBJ_TREE, _tree_payload([("40000", "data", data_sha)]))
    meas_sha, meas_tree = _git_object(catalog.OBJ_TREE, _tree_payload([("40000", "oratory1990", src_sha)]))
    targ_sha, targ_tree = _git_object(
        catalog.OBJ_TREE, _tree_payload([("100644", "Harman in-ear 2019.csv", target_sha)])
    )
    root_sha, root_tree = _git_object(
        catalog.OBJ_TREE, _tree_payload([("40000", "measurements", meas_sha), ("40000", "targets", targ_sha)])
    )
    commit_sha, commit_data = _git_object(catalog.OBJ_COMMIT, f"tree {root_sha}\nauthor a\n\ninit\n".encode())
    pack = _pack_v2(
        [
            (catalog.OBJ_COMMIT, commit_data),
            (catalog.OBJ_TREE, root_tree),
            (catalog.OBJ_TREE, meas_tree),
            (catalog.OBJ_TREE, src_tree),
            (catalog.OBJ_TREE, data_tree),
            (catalog.OBJ_TREE, in_ear_tree),
            (catalog.OBJ_TREE, targ_tree),
        ]
    )
    refs_payload = (
        catalog._pkt_line(b"# service=git-upload-pack\n")
        + b"0000"
        + catalog._pkt_line(f"{commit_sha} refs/heads/master\x00filter\n".encode())
    )

    class FakeResponse:
        def __init__(self, payload: bytes) -> None:
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_exc) -> None:
            pass

        def read(self, _n: int) -> bytes:
            return self.payload

    seen_urls: list[str] = []

    def fake_urlopen(request, *, timeout):
        seen_urls.append(request.full_url)
        assert "api.github.com" not in request.full_url
        assert request.get_header("Authorization") is None
        if request.full_url.endswith("/info/refs?service=git-upload-pack"):
            return FakeResponse(refs_payload)
        assert request.full_url.endswith("/git-upload-pack")
        assert b"filter blob:none\n" in request.data
        return FakeResponse(b"0008NAK\n" + pack)

    monkeypatch.setattr(catalog.urllib.request, "urlopen", fake_urlopen)
    index_path = tmp_path / "catalog.json"
    entries = catalog.download_index(index_path)
    assert len(seen_urls) == 2
    assert {entry.kind for entry in entries} == {"model", "target"}
    assert catalog.load_index(index_path) == entries


def test_autoeq_resolve_curve_uses_raw_https_and_bundled_targets_offline(tmp_path: Path, monkeypatch) -> None:
    bundled = tmp_path / "targety"
    bundled.mkdir()
    bundled_target = bundled / "Harman in-ear 2019.csv"
    bundled_target.write_text("frequency,raw\n20,0\n1000,0\n", encoding="utf-8")

    def fail_network(*_args, **_kwargs):
        raise AssertionError("Bundled target should resolve offline without network calls")

    monkeypatch.setattr(catalog.urllib.request, "urlopen", fail_network)
    target_entry = catalog.Entry("Harman in-ear 2019", "AutoEq", "target", "targets/Harman in-ear 2019.csv", False)
    assert catalog.resolve_curve(target_entry, tmp_path / "curves", bundled_targets=bundled) == bundled_target

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_exc) -> None:
            pass

        def read(self, _n: int) -> bytes:
            return b"frequency,raw\n20,-1\n1000,0\n"

    requested_urls: list[str] = []

    def fake_raw_open(request, *, timeout):
        requested_urls.append(request.full_url)
        assert request.full_url.startswith("https://raw.githubusercontent.com/jaakkopasanen/AutoEq/master/")
        assert "api.github.com" not in request.full_url
        return FakeResponse()

    monkeypatch.setattr(catalog.urllib.request, "urlopen", fake_raw_open)
    model_entry = catalog.Entry(
        "MOONDROP Chu",
        "oratory1990",
        "model",
        "measurements/oratory1990/data/in-ear/MOONDROP Chu.csv",
        False,
        "ab" * 20,
    )
    curves_dir = tmp_path / "curves"
    cached = catalog.resolve_curve(model_entry, curves_dir, bundled_targets=bundled)
    assert cached.is_file() and len(requested_urls) == 1

    # Drugi odczyt offline korzysta z zapisanej pamięci podręcznej.
    monkeypatch.setattr(catalog.urllib.request, "urlopen", fail_network)
    assert catalog.resolve_curve(model_entry, curves_dir, bundled_targets=bundled) == cached


@pytest.mark.parametrize("failure", ["missing_target_tree", "empty_targets", "bad_checksum", "http_403"])
def test_autoeq_failed_refresh_keeps_existing_index_and_curve(tmp_path, monkeypatch, failure) -> None:
    index = tmp_path / "catalog.json"
    original = catalog.Entry(
        "Existing", "oratory1990", "model", "measurements/oratory1990/data/in-ear/Existing.csv", False
    )
    catalog.save_index(index, [original])
    saved_index = index.read_bytes()
    curve = tmp_path / "saved-measurement.csv"
    saved_curve = b"frequency,raw\n100,0\n"
    curve.write_bytes(saved_curve)

    if failure == "http_403":
        monkeypatch.setattr(
            catalog,
            "_fetch_master_oid",
            lambda: (_ for _ in ()).throw(ValueError("Serwer AutoEq zwrócił błąd HTTP 403.")),
        )
    elif failure == "bad_checksum":
        bad_pack = bytearray(_pack_v2([]))
        bad_pack[-1] ^= 0xFF
        monkeypatch.setattr(catalog, "_fetch_master_oid", lambda: "aa" * 20)
        monkeypatch.setattr(catalog, "_fetch_tree_pack", lambda _oid: bytes(bad_pack))
    else:
        blob_sha = "11" * 20
        in_ear_sha, in_ear_tree = _git_object(catalog.OBJ_TREE, _tree_payload([("100644", "New.csv", blob_sha)]))
        data_sha, data_tree = _git_object(catalog.OBJ_TREE, _tree_payload([("40000", "in-ear", in_ear_sha)]))
        src_sha, src_tree = _git_object(catalog.OBJ_TREE, _tree_payload([("40000", "data", data_sha)]))
        meas_sha, meas_tree = _git_object(catalog.OBJ_TREE, _tree_payload([("40000", "new-source", src_sha)]))
        targ_sha, targ_tree = _git_object(catalog.OBJ_TREE, _tree_payload([]))
        root_items = [("40000", "measurements", meas_sha)]
        if failure != "missing_target_tree":
            root_items.append(("40000", "targets", targ_sha))
        root_sha, root_tree = _git_object(catalog.OBJ_TREE, _tree_payload(root_items))
        commit_sha, commit_data = _git_object(catalog.OBJ_COMMIT, f"tree {root_sha}\nauthor a\n\ninit\n".encode())
        objs = {
            commit_sha: (catalog.OBJ_COMMIT, commit_data),
            root_sha: (catalog.OBJ_TREE, root_tree),
            meas_sha: (catalog.OBJ_TREE, meas_tree),
            src_sha: (catalog.OBJ_TREE, src_tree),
            data_sha: (catalog.OBJ_TREE, data_tree),
            in_ear_sha: (catalog.OBJ_TREE, in_ear_tree),
            targ_sha: (catalog.OBJ_TREE, targ_tree),
        }
        monkeypatch.setattr(catalog, "fetch_repo_tree", lambda: (objs, root_sha))

    with pytest.raises(ValueError, match=r"AutoEq|HTTP 403|Suma kontrolna"):
        catalog.download_index(index)
    assert index.read_bytes() == saved_index
    assert curve.read_bytes() == saved_curve


def test_bundled_autoeq_index_and_targets_present_in_repo_and_manifest() -> None:
    root = Path(__file__).resolve().parents[1]
    bundled_index = root / "dane" / "autoeq-catalog.json"
    assert bundled_index.is_file()
    entries = catalog.load_index(bundled_index)
    assert sum(1 for entry in entries if entry.kind == "model") > 6000
    assert sum(1 for entry in entries if entry.kind == "target") >= 50

    targets_dir = root / "dane" / "targety"
    bundled_targets = sorted(targets_dir.glob("*.csv"))
    assert len(bundled_targets) >= 9
    for target_path in bundled_targets:
        assert len(gui.read_target_curve(target_path)) > 50

    manifest = json.loads((root / "local.moondrop.Position.json").read_text(encoding="utf-8"))
    app_module = next(mod for mod in manifest["modules"] if mod["name"] == "position-dac")
    source_paths = {item["path"] for item in app_module["sources"]}
    assert "dane/autoeq-catalog.json" in source_paths
    for target_path in bundled_targets:
        assert f"dane/targety/{target_path.name}" in source_paths


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
