"""Modular declarative device specifications loaded from data/devices/<model_id>/device.json."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from measurements import read_squig_txt

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEVICES_DIR = DATA_DIR / "devices"
DEFAULT_MODEL_ID = "moondrop-position"
VALID_FORM_FACTORS = frozenset({"integrated_iem", "dongle_dac"})
VALID_FILTER_TYPES = frozenset({"PK", "LSQ", "HSQ", "LP", "HP"})


@dataclass(frozen=True)
class FitRangeSpec:
    id: str
    max_fc: int
    bands: int


@dataclass(frozen=True)
class BuiltinProfileSpec:
    name: str
    path: Path


@dataclass(frozen=True)
class SlotSpec:
    factory: int | None
    custom: int
    names: dict[int, str]


@dataclass(frozen=True)
class ControlsSpec:
    global_gain_db: tuple[int, int] | None
    mic_gain: bool


@dataclass(frozen=True)
class DspSpec:
    sample_rate_hz: float
    band_count: int
    supported_types: tuple[str, ...]
    freq_range_hz: tuple[float, float]
    gain_range_db: tuple[float, float]
    q_range: tuple[float, float]
    preamp_range_db: tuple[float, float]
    default_frequencies_hz: tuple[float, ...]
    default_q: float
    reconnect_on_save: bool
    slots: SlotSpec
    controls: ControlsSpec


@dataclass(frozen=True)
class AcousticsSpec:
    measurement_path: Path | None
    measurement_rig: str | None
    measurement_source: str | None
    measurement_includes_factory_eq: bool
    factory_bands: tuple[dict, ...]
    default_autoeq_measurement: str | None
    default_target: str | None
    fit_ranges: tuple[FitRangeSpec, ...]


@dataclass(frozen=True)
class DeviceSpec:
    model_id: str
    display_name: str
    form_factor: str
    experimental: bool
    vendor_id: int
    product_id: int
    driver: str
    dsp: DspSpec
    acoustics: AcousticsSpec
    builtin_profiles: tuple[BuiltinProfileSpec, ...]
    root_dir: Path

    @property
    def usb_id_str(self) -> str:
        return f"{self.vendor_id:04x}:{self.product_id:04x}"

    @property
    def is_dongle(self) -> bool:
        return self.form_factor == "dongle_dac"

    @property
    def has_factory_slot(self) -> bool:
        return self.dsp.slots.factory is not None

    def default_custom_bands(self) -> list[dict]:
        freqs = self.dsp.default_frequencies_hz
        return [
            {
                "band": index,
                "type": "PK",
                "freq": freqs[index - 1] if index - 1 < len(freqs) else 1000,
                "gain": 0.0,
                "q": self.dsp.default_q,
            }
            for index in range(1, self.dsp.band_count + 1)
        ]

    def factory_bands_copy(self) -> list[dict]:
        return [dict(band) for band in self.acoustics.factory_bands]

    def measured_curve(self) -> list[tuple[float, float]]:
        path = self.acoustics.measurement_path
        if path is None:
            return []
        return list(_load_measurement_curve(path))


@lru_cache(maxsize=32)
def _load_measurement_curve(path: Path) -> tuple[tuple[float, float], ...]:
    try:
        freqs, dbs = read_squig_txt(path)
    except (OSError, ValueError):
        return ()
    return tuple((hz, db) for hz, db in zip(freqs, dbs, strict=False) if 20 <= hz <= 20000 and math.isfinite(db))


def _parse_hex_int(value: str | int) -> int:
    if isinstance(value, int):
        return value
    return int(str(value), 0)


def parse_device_spec(spec_path: Path) -> DeviceSpec:
    raw = json.loads(spec_path.read_text(encoding="utf-8"))
    root_dir = spec_path.parent
    if raw.get("schema_version") != 1:
        raise ValueError(f"{spec_path}: unsupported schema_version={raw.get('schema_version')!r}")

    model_id = str(raw["model_id"])
    if model_id != root_dir.name:
        raise ValueError(f"{spec_path}: model_id {model_id!r} does not match folder name {root_dir.name!r}")

    form_factor = str(raw["form_factor"])
    if form_factor not in VALID_FORM_FACTORS:
        raise ValueError(f"{spec_path}: invalid form_factor={form_factor!r}")

    usb = raw["usb"]
    dsp_raw = raw["dsp"]
    ac_raw = raw["acoustics"]

    supported_types = tuple(str(t) for t in dsp_raw["supported_types"])
    invalid_types = [t for t in supported_types if t not in VALID_FILTER_TYPES]
    if invalid_types:
        raise ValueError(f"{spec_path}: invalid filter types {invalid_types!r}")

    band_count = int(dsp_raw["band_count"])
    default_freqs = tuple(float(f) for f in dsp_raw["default_frequencies_hz"])
    if len(default_freqs) != band_count:
        raise ValueError(
            f"{spec_path}: default_frequencies_hz length ({len(default_freqs)}) != band_count ({band_count})"
        )

    slots_raw = dsp_raw["slots"]
    slot_names = {int(k): str(v) for k, v in slots_raw["names"].items()}
    custom_slot = int(slots_raw["custom"])
    factory_slot = int(slots_raw["factory"]) if slots_raw.get("factory") is not None else None
    if custom_slot not in slot_names:
        raise ValueError(f"{spec_path}: custom slot {custom_slot} missing from slots.names")
    if factory_slot is not None and factory_slot not in slot_names:
        raise ValueError(f"{spec_path}: factory slot {factory_slot} missing from slots.names")

    controls_raw = dsp_raw.get("controls", {})
    gg_raw = controls_raw.get("global_gain_db")
    global_gain = (int(gg_raw[0]), int(gg_raw[1])) if gg_raw is not None else None

    dsp = DspSpec(
        sample_rate_hz=float(dsp_raw["sample_rate_hz"]),
        band_count=band_count,
        supported_types=supported_types,
        freq_range_hz=(float(dsp_raw["freq_range_hz"][0]), float(dsp_raw["freq_range_hz"][1])),
        gain_range_db=(float(dsp_raw["gain_range_db"][0]), float(dsp_raw["gain_range_db"][1])),
        q_range=(float(dsp_raw["q_range"][0]), float(dsp_raw["q_range"][1])),
        preamp_range_db=(float(dsp_raw["preamp_range_db"][0]), float(dsp_raw["preamp_range_db"][1])),
        default_frequencies_hz=default_freqs,
        default_q=float(dsp_raw["default_q"]),
        reconnect_on_save=bool(dsp_raw.get("reconnect_on_save", False)),
        slots=SlotSpec(factory=factory_slot, custom=custom_slot, names=slot_names),
        controls=ControlsSpec(global_gain_db=global_gain, mic_gain=bool(controls_raw.get("mic_gain", False))),
    )

    bundled_rel = ac_raw.get("bundled_measurement")
    measurement_path = (root_dir / bundled_rel) if bundled_rel else None
    if measurement_path is not None and not measurement_path.is_file():
        raise ValueError(f"{spec_path}: bundled_measurement does not exist: {measurement_path}")

    factory_bands = tuple(dict(b) for b in ac_raw.get("factory_bands", ()))
    fit_ranges = tuple(
        FitRangeSpec(id=str(fr["id"]), max_fc=int(fr["max_fc"]), bands=int(fr["bands"]))
        for fr in ac_raw.get("fit_ranges", ())
    )
    for fr in fit_ranges:
        if fr.bands < 1 or fr.bands > band_count:
            raise ValueError(f"{spec_path}: fit_range {fr.id!r} bands={fr.bands} exceeds band_count={band_count}")

    acoustics = AcousticsSpec(
        measurement_path=measurement_path,
        measurement_rig=ac_raw.get("measurement_rig"),
        measurement_source=ac_raw.get("measurement_source"),
        measurement_includes_factory_eq=bool(ac_raw.get("measurement_includes_factory_eq", False)),
        factory_bands=factory_bands,
        default_autoeq_measurement=ac_raw.get("default_autoeq_measurement"),
        default_target=ac_raw.get("default_target"),
        fit_ranges=fit_ranges,
    )

    builtin_profiles: list[BuiltinProfileSpec] = []
    for bp in raw.get("builtin_profiles", ()):
        bp_path = root_dir / str(bp["file"])
        if not bp_path.is_file():
            raise ValueError(f"{spec_path}: builtin profile does not exist: {bp_path}")
        builtin_profiles.append(BuiltinProfileSpec(name=str(bp["name"]), path=bp_path))

    return DeviceSpec(
        model_id=model_id,
        display_name=str(raw["display_name"]),
        form_factor=form_factor,
        experimental=bool(raw.get("experimental", False)),
        vendor_id=_parse_hex_int(usb["vendor_id"]),
        product_id=_parse_hex_int(usb["product_id"]),
        driver=str(usb["driver"]),
        dsp=dsp,
        acoustics=acoustics,
        builtin_profiles=tuple(builtin_profiles),
        root_dir=root_dir,
    )


@lru_cache(maxsize=4)
def load_device_specs(devices_dir: Path = DEVICES_DIR) -> dict[str, DeviceSpec]:
    specs: dict[str, DeviceSpec] = {}
    if not devices_dir.is_dir():
        return specs
    for spec_path in sorted(devices_dir.glob("*/device.json")):
        spec = parse_device_spec(spec_path)
        specs[spec.model_id] = spec
    return specs


def get_device_spec(model_id: str | None, devices_dir: Path = DEVICES_DIR) -> DeviceSpec:
    specs = load_device_specs(devices_dir)
    if model_id and model_id in specs:
        return specs[model_id]
    if DEFAULT_MODEL_ID in specs:
        return specs[DEFAULT_MODEL_ID]
    if specs:
        return next(iter(specs.values()))
    raise FileNotFoundError(f"Brak definicji urządzeń w {devices_dir}")


def default_device_spec(devices_dir: Path = DEVICES_DIR) -> DeviceSpec:
    return get_device_spec(DEFAULT_MODEL_ID, devices_dir)
