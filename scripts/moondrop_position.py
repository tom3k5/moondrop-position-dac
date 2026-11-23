#!/usr/bin/env python3
"""MOONDROP:Gravity Position (35d8:0123) — odczyt i zapis DSP przez HID report 0x4B.

Protokół odtworzony z publicznych implementacji (patrz docs/sources.md):
  * devicePEQ / moondropUsbHidHandler.js  (0BSD)
  * FreeDSP Studio / dsp2.rs              (MIT)
  * eqcaps: profil moondrop-position      (MIT / CC)

Ramka (64 B, report ID 0x4B, endpointy przerwań):
    [0x4B] [OP] [CMD] [LEN] [payload...]
    OP = 0x01 zapis, 0x80 odczyt; odpowiedź wraca jako input report
    z tym samym CMD.

Dostęp do /dev/hidraw wymaga reguły udev (patrz udev/). Zapis zmienia EQ
w pamięci flash urządzenia. Opcja --dry-run pokazuje ramki bez zapisu.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import struct
import sys
import time

from chu2_dsp import CHU2_MODEL
from dac_devices import DacModel, DacRegistry, DeviceTarget
from dac_transport import HidDeviceMissing, HidError, HidPermissionError, HidrawTransport, HidReport
from echo_a import ECHO_A_MODEL

REPORT_ID = 0x4B
VENDOR_ID = 0x35D8
PRODUCT_ID = 0x0123
POSITION_NAME = "MOONDROP:Gravity Position"
SLOT_NAMES = {0: "Default", 7: "Custom"}
CUSTOM_SLOT = 7
BAND_COUNT = 8

OP_WRITE = 0x01
OP_READ = 0x80

CMD_SAVE_EQ = 0x01  # zapis EQ do flash
CMD_MIC_GAIN = 0x02  # wzmocnienie ADC mikrofonu (16-bit)
CMD_GLOBAL_GAIN = 0x03  # offset DAC / global gain (1 B)
CMD_SAVE_OFFSET = 0x04  # zapis offsetu do flash
CMD_RESET = 0x05  # "memory refresh" / reset EQ
CMD_EQ_UPDATE = 0x09  # odczyt/zapis pasma
CMD_EQ_COEFF = 0x0A  # zatrzaśnięcie współczynników (per pasmo)
CMD_VERSION = 0x0C  # wersja firmware
CMD_ACTIVE_SLOT = 0x0F  # aktywny slot EQ
CMD_DAC_FILTER = 0x11  # filtr DAC
CMD_BALANCE = 0x16  # balans L/P
CMD_LED = 0x18  # dioda
CMD_DAC_GAIN = 0x19  # wzmocnienie DAC
CMD_DAC_MODE = 0x1D  # tryb pracy DAC
CMD_PRE_GAIN = 0x23  # pre-gain (16-bit, krok 1/256 dB)

TYPE_TO_CODE = {"LSQ": 1, "PK": 2, "HSQ": 3, "LP": 4, "HP": 5}
CODE_TO_TYPE = {v: k for k, v in TYPE_TO_CODE.items()}

# Biquady urządzenia liczą się przy stałym 96 kHz i są zapisywane jako Q2.30.
COEFF_FS = 96000.0
COEFF_SCALE = float(1 << 30)

PAYLOAD_LEN = 63  # report 0x4B: 63 B danych + 1 B report ID

# Opóźnienia zalecane przez implementacje referencyjne (urządzenie gubi ramki).
DELAY_BAND_MS = 25
DELAY_OP_MS = 50
DELAY_FLASH_MS = 200
DELAY_WRITE_EQ_MS = 150
REPLY_TIMEOUT_MS = 600


class MoondropPosition:
    model_id = "moondrop-position"
    model_name = POSITION_NAME
    experimental = False
    band_count = BAND_COUNT
    supported_types = tuple(TYPE_TO_CODE)
    gain_range = (-18.0, 12.0)
    preamp_range = (-128.0, 0.0)
    custom_slot = CUSTOM_SLOT
    slot_names = SLOT_NAMES
    sample_rate_hz = COEFF_FS
    reconnect_on_save = False

    def __init__(self, transport: HidrawTransport, timeout_ms: int = REPLY_TIMEOUT_MS):
        self.transport = transport
        self.interface = transport.interface
        self.path = self.interface.node
        self.timeout_ms = timeout_ms

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.transport.close()

    def _write_frame(self, payload: bytes) -> None:
        if len(payload) > PAYLOAD_LEN:
            raise ValueError(f"payload {len(payload)} B > {PAYLOAD_LEN} B")
        self.transport.write(bytes([REPORT_ID]) + payload.ljust(PAYLOAD_LEN, b"\x00"))

    def _drain(self) -> None:
        """Wyrzuca zaległe odpowiedzi (kilka poleceń dzieli CMD 0x09)."""
        for _ in range(64):
            if self.transport.read(PAYLOAD_LEN + 1) is None:
                return
        raise HidError("Kolejka raportów HID nie opróżniła się.")

    def _read_reply(self, cmd: int, index: int | None = None) -> bytes | None:
        deadline = time.monotonic() + self.timeout_ms / 1000.0
        while (remaining := deadline - time.monotonic()) > 0:
            data = self.transport.read(PAYLOAD_LEN + 1, remaining)
            if data is None:
                return None
            payload = data[1:] if data[0] == REPORT_ID else data
            if len(payload) < 2:
                continue
            if payload[0] != OP_READ or payload[1] != cmd:
                continue  # np. klawisze konsumenckie albo spóźniona odpowiedź
            if len(payload) < {CMD_EQ_UPDATE: 34, CMD_GLOBAL_GAIN: 5, CMD_PRE_GAIN: 5}.get(cmd, 4):
                continue
            if index is not None and (len(payload) < 5 or payload[4] != index):
                continue  # odpowiedź na inne pasmo
            return payload
        return None

    def request(self, cmd: int, payload: bytes, index: int | None = None, retries: int = 2) -> bytes:
        for _ in range(retries):
            self._drain()
            self._write_frame(payload)
            reply = self._read_reply(cmd, index=index)
            if reply is not None:
                return reply
        raise HidError(f"Brak odpowiedzi na CMD 0x{cmd:02X} (timeout {self.timeout_ms} ms)")

    # -- odczyt ------------------------------------------------------------
    def version(self) -> str:
        p = self.request(CMD_VERSION, bytes([OP_READ, CMD_VERSION]))
        raw = p[3:9].split(b"\x00", 1)[0]
        return raw.decode("ascii", "replace") or "?"

    def slot(self) -> int:
        p = self.request(CMD_ACTIVE_SLOT, bytes([OP_READ, CMD_ACTIVE_SLOT, 0x00]))
        return p[3]

    def read_band(self, index: int, *, include_coefficients: bool = False) -> dict | None:
        p = self.request(CMD_EQ_UPDATE, bytes([OP_READ, CMD_EQ_UPDATE, 0x18, 0x00, index, 0x00]), index=index)
        freq = struct.unpack_from("<H", p, 27)[0]
        q = struct.unpack_from("<h", p, 29)[0] / 256.0
        gain = struct.unpack_from("<h", p, 31)[0] / 256.0
        ftype = CODE_TO_TYPE.get(p[33], f"0x{p[33]:02X}")
        valid = 10 < freq < 24000 and not math.isnan(gain) and not math.isnan(q)
        if not valid:
            return None
        band = {"band": index + 1, "freq": freq, "gain": gain, "q": q, "type": ftype}
        if include_coefficients:
            band["coefficients"] = bytes(p[7:27])
        return band

    def read_eq(self, bands: int, *, include_coefficients: bool = False) -> list[dict]:
        out = []
        for i in range(bands):
            band = self.read_band(i, include_coefficients=include_coefficients)
            if band is None:
                break
            out.append(band)
            time.sleep(DELAY_BAND_MS / 1000.0)
        return out

    def preamp(self) -> float:
        p = self.request(CMD_PRE_GAIN, bytes([OP_READ, CMD_PRE_GAIN]))
        return struct.unpack_from("<h", p, 3)[0] / 256.0

    def global_gain(self) -> int:
        p = self.request(CMD_GLOBAL_GAIN, bytes([OP_READ, CMD_GLOBAL_GAIN, 0x00]))
        return struct.unpack_from("<b", p, 4)[0]

    def mic_gain_raw(self) -> int:
        reply = self.request(CMD_MIC_GAIN, bytes([OP_READ, CMD_MIC_GAIN, 0x00]))
        if len(reply) < 5 or reply[2] != 2:
            raise HidError(f"Nieznany format odczytu wzmocnienia mikrofonu: {reply[:5].hex(' ')}.")
        return struct.unpack_from("<h", reply, 3)[0]

    # -- zapis -------------------------------------------------------------
    def write_band(
        self,
        index: int,
        freq: float,
        gain: float,
        q: float,
        ftype: str,
        slot: int,
        *,
        coefficients: bytes | None = None,
    ) -> bytes:
        code = TYPE_TO_CODE.get(ftype.upper())
        if code is None:
            raise ValueError(f"Nieznany typ filtra: {ftype!r} (dozwolone: {', '.join(TYPE_TO_CODE)})")
        payload = bytearray(63)
        payload[0] = OP_WRITE
        payload[1] = CMD_EQ_UPDATE
        payload[2] = 0x18
        payload[4] = index
        payload[7:27] = (
            biquad_coefficients(code, freq, gain, q, for_write=True) if coefficients is None else coefficients
        )
        struct.pack_into("<H", payload, 27, round(freq))
        struct.pack_into("<h", payload, 29, clamp_i16(q * 256))
        struct.pack_into("<h", payload, 31, clamp_i16(gain * 256))
        payload[33] = code
        payload[34] = 0
        payload[35] = slot
        self._write_frame(bytes(payload))
        return bytes(payload)

    def latch_band(self, index: int) -> bytes:
        payload = bytes([OP_WRITE, CMD_EQ_COEFF, index, 0x00, 0xFF, 0xFF, 0xFF])
        self._write_frame(payload)
        return payload

    def save(self) -> bytes:
        payload = bytes([OP_WRITE, CMD_SAVE_EQ])
        self._write_frame(payload)
        return payload

    def set_preamp(self, db: float, *, legacy: bool = True) -> bytes:
        payload = preamp_payload(db, legacy=legacy)
        self._write_frame(payload)
        return payload

    def set_global_gain_volatile(self, db: int) -> None:
        if type(db) is not int or not -18 <= db <= 0:
            raise ValueError("Global gain musi być liczbą całkowitą od −18 do 0 dB.")
        payload = bytes([OP_WRITE, CMD_GLOBAL_GAIN, 0x02, 0x00]) + struct.pack("<b", db)
        self._write_frame(payload)

    def set_mic_gain_raw(self, value: int) -> None:
        if not -32767 <= value <= 32767:
            raise ValueError("Kod wzmocnienia mikrofonu jest poza zakresem.")
        payload = bytes([OP_WRITE, CMD_MIC_GAIN, 0x02]) + struct.pack("<h", value)
        self._write_frame(payload)

    def set_slot(self, slot: int, *, legacy: bool = False) -> bytes:
        body = [slot] if legacy else [1, slot]
        payload = bytes([OP_WRITE, CMD_ACTIVE_SLOT, *body])
        self._write_frame(payload)
        return payload


# --------------------------------------------------------------------------
# Biquady (RBJ, 96 kHz, Q2.30) — jak w Moondrop/Walkplay gen-2
# --------------------------------------------------------------------------


def clamp_i16(v: float) -> int:
    return max(-32768, min(32767, round(v)))


def preamp_payload(db: float, *, legacy: bool = True) -> bytes:
    length = 0 if legacy else 2
    return bytes([OP_WRITE, CMD_PRE_GAIN, length]) + struct.pack("<h", clamp_i16(db * 256))


def biquad_coefficients(ftype: int, freq: float, gain: float, q: float, *, for_write: bool = False) -> bytes:
    """Zwraca 20 B: b0,b1,b2,-a1,-a2 jako int32 LE w Q2.30 (a0 znormalizowane)."""
    freq = max(20.0, min(20000.0, freq))
    q = max(0.1, min(10.0, q))
    w0 = 2.0 * math.pi * freq / COEFF_FS
    cos_w0, sin_w0 = math.cos(w0), math.sin(w0)

    check_shelf_range = False
    if ftype in (1, 3):  # LSQ / HSQ
        big_a = 10.0 ** (gain / 40.0)
        # Wzór RBJ traktuje parametr półki jako nachylenie S. Przy dużym S
        # ogranicz tłumienie od dołu do sin(w0)/(2Q), aby bieguny pozostały stabilne.
        inner = (big_a + 1.0 / big_a) * (1.0 / q - 1.0) + 2.0
        if q > 1.0 and inner < 1.0 / q**2:
            inner = 1.0 / q**2
            check_shelf_range = for_write
        alpha = sin_w0 / 2.0 * math.sqrt(inner)
        s = 2.0 * math.sqrt(big_a) * alpha
        if ftype == 1:
            b = [
                big_a * ((big_a + 1) - (big_a - 1) * cos_w0 + s),
                2 * big_a * ((big_a - 1) - (big_a + 1) * cos_w0),
                big_a * ((big_a + 1) - (big_a - 1) * cos_w0 - s),
            ]
            a = [
                (big_a + 1) + (big_a - 1) * cos_w0 + s,
                -2 * ((big_a - 1) + (big_a + 1) * cos_w0),
                (big_a + 1) + (big_a - 1) * cos_w0 - s,
            ]
        else:
            b = [
                big_a * ((big_a + 1) + (big_a - 1) * cos_w0 + s),
                -2 * big_a * ((big_a - 1) + (big_a + 1) * cos_w0),
                big_a * ((big_a + 1) + (big_a - 1) * cos_w0 - s),
            ]
            a = [
                (big_a + 1) - (big_a - 1) * cos_w0 + s,
                2 * ((big_a - 1) - (big_a + 1) * cos_w0),
                (big_a + 1) - (big_a - 1) * cos_w0 - s,
            ]
    elif ftype in (4, 5):  # low-pass / high-pass
        alpha = sin_w0 / (2.0 * q)
        d = alpha + 1.0
        a = [1.0, -2.0 * cos_w0 / d, (1.0 - alpha) / d]
        if ftype == 4:
            b = [(1.0 - cos_w0) / 2.0 / d, (1.0 - cos_w0) / d, (1.0 - cos_w0) / 2.0 / d]
        else:
            b = [(1.0 + cos_w0) / 2.0 / d, (-1.0 - cos_w0) / d, (1.0 + cos_w0) / 2.0 / d]
    else:  # PK (2)
        big_a = 10.0 ** (gain / 40.0)
        alpha = sin_w0 / (2.0 * q)
        a = [1.0 + alpha / big_a, -2.0 * cos_w0, 1.0 - alpha / big_a]
        b = [1.0 + alpha * big_a, -2.0 * cos_w0, 1.0 - alpha * big_a]

    a0 = a[0]
    values = [b[0] / a0, b[1] / a0, b[2] / a0, -a[1] / a0, -a[2] / a0]
    out = bytearray()
    for value in values:
        # Współczynnik spoza int32 zawija się (a nie nasyca) — tak samo robi
        # urządzenie i implementacja referencyjna; dotyczy szerokich półek.
        raw = round(value * COEFF_SCALE)
        if check_shelf_range and not -(1 << 31) <= raw < 1 << 31:
            raise HidError("Stroma półka przekracza zakres współczynników DAC-a (Q2.30). Zmniejsz Q lub gain.")
        wrapped = ((raw + (1 << 31)) % (1 << 32)) - (1 << 31)
        out += struct.pack("<i", wrapped)
    return bytes(out)


# --------------------------------------------------------------------------
# Prezentacja / CLI
# --------------------------------------------------------------------------


def fmt_band(b: dict) -> str:
    return f"{b['band']:>2}. {b['type']:<3}  f={b['freq']:>6} Hz  gain={b['gain']:>+7.2f} dB  Q={b['q']:>6.3f}"


POSITION_MODEL = DacModel(
    model_id="moondrop-position",
    display_name=POSITION_NAME,
    usb_id=(VENDOR_ID, PRODUCT_ID),
    reports=frozenset(HidReport(REPORT_ID, kind, PAYLOAD_LEN) for kind in ("input", "output")),
    connect=MoondropPosition,
)
DEVICE_REGISTRY = DacRegistry((POSITION_MODEL, CHU2_MODEL, ECHO_A_MODEL))


def connect_device(target: DeviceTarget | None = None, timeout_ms: int = REPLY_TIMEOUT_MS):
    selected = DEVICE_REGISTRY.select(target)
    return DEVICE_REGISTRY.open(selected, timeout_ms) if selected is not None else None


def require_device(target: DeviceTarget | None = None, timeout_ms: int = REPLY_TIMEOUT_MS):
    device = connect_device(target, timeout_ms)
    if device is None:
        raise HidDeviceMissing(
            "Nie znaleziono obsługiwanego DAC-a (Position 35d8:0123, CHU II DSP 31b2:0113, ECHO-A 3302:12c5) "
            "z raportem HID 0x4B."
        )
    return device


def cmd_list(_args) -> int:
    devices = DEVICE_REGISTRY.detect()
    if not devices:
        print("Brak obsługiwanego urządzenia z raportem 0x4B (Position, CHU II DSP, ECHO-A).")
        return 1
    for selected in devices:
        interface = selected.interface
        print(
            f"{interface.node}  [{selected.model.display_name}]  "
            f"{interface.vendor_id:04x}:{interface.product_id:04x}  (report 0x4B)"
        )
        print(f"  sysfs: {interface.sysfs}")
        try:
            with DEVICE_REGISTRY.open(selected, REPLY_TIMEOUT_MS):
                print("  dostęp: OK")
        except HidPermissionError:
            print("  dostęp: BRAK (dodaj regułę udev — patrz --help / udev/)")
        except HidError as exc:
            print(f"  dostęp: błąd ({exc})")
    return 0


def open_device(args) -> MoondropPosition:
    return require_device(getattr(args, "device", None), args.timeout)


def cmd_info(args) -> int:
    with open_device(args) as dev:
        info = {
            "device": dev.path,
            "usb": "35d8:0123",
            "firmware": dev.version(),
            "slot": dev.slot(),
            "preamp_db": round(dev.preamp(), 3),
        }
        try:
            info["global_gain_db"] = dev.global_gain()
        except HidError:
            info["global_gain_db"] = None
        bands = dev.read_eq(args.bands)
        info["bands_read"] = len(bands)
        info["bands"] = bands
    if args.json:
        print(json.dumps(info, indent=2, ensure_ascii=False))
    else:
        print(f"Urządzenie : MOONDROP:Gravity Position ({info['usb']}) na {info['device']}")
        print(f"Firmware   : {info['firmware']}")
        print(f"Aktywny slot: {info['slot']}  (0 = Default, 7 = Custom wg oficjalnej apki)")
        print(f"Pre-gain   : {info['preamp_db']:+.2f} dB")
        if info["global_gain_db"] is not None:
            print(f"Global gain: {info['global_gain_db']} dB")
        print(f"Pasem odczytano: {info['bands_read']}")
        for band in bands:
            print("  " + fmt_band(band))
    return 0


def cmd_read_eq(args) -> int:
    with open_device(args) as dev:
        bands = dev.read_eq(args.bands)
        preamp = dev.preamp()
        slot = dev.slot()
    if args.json:
        print(json.dumps({"slot": slot, "preamp": preamp, "bands": bands}, indent=2, ensure_ascii=False))
    else:
        print(f"slot={slot}  preamp={preamp:+.2f} dB  pasm={len(bands)}")
        for band in bands:
            print("  " + fmt_band(band))
    return 0


def activate_slot(dev: MoondropPosition, slot: int) -> None:
    # devicePEQ omija LEN w tym poleceniu, FreeDSP wysyła LEN=1.
    # Użyj drugiej ramki tylko wtedy, gdy odczyt nie potwierdzi pierwszej.
    for legacy in (True, False):
        dev.set_slot(slot, legacy=legacy)
        time.sleep(DELAY_WRITE_EQ_MS / 1000.0)
        for attempt in range(3):
            if attempt:
                time.sleep(DELAY_OP_MS / 1000.0)
            actual = dev.slot()
            if actual == slot:
                return
    raise HidError(
        f"Nie potwierdzono przełączenia na slot {slot}: DAC zgłasza slot {actual} po próbie obu formatów polecenia."
    )


def cmd_dump_slots(args) -> int:
    with open_device(args) as dev:
        original_slot = dev.slot()
        firmware = dev.version()
        if args.switch and original_slot not in SLOT_NAMES:
            raise HidError(f"Nieznany aktywny slot {original_slot}. Użyj zrzutu bez --switch.")
        other_slots = [slot for slot in SLOT_NAMES if slot != original_slot]
        slots = [original_slot, *other_slots] if args.switch else [original_slot]
        profiles = []
        switched = False
        try:
            for slot in slots:
                if dev.slot() != slot:
                    if not profiles:
                        raise HidError("Aktywny slot zmienił się przed odczytem.")
                    switched = True
                    activate_slot(dev, slot)
                preamp = dev.preamp()
                global_gain = dev.global_gain()
                bands = []
                for index in range(BAND_COUNT):
                    bands.append(dev.read_band(index))
                    time.sleep(DELAY_BAND_MS / 1000.0)
                if dev.slot() != slot:
                    raise HidError("Aktywny slot zmienił się w trakcie odczytu.")
                filters = [band for band in bands if band is not None]
                non_neutral = any(
                    band["type"] in ("LP", "HP") or (band["type"] in ("PK", "LSQ", "HSQ") and band["gain"] != 0)
                    for band in filters
                )
                known = len(filters) == BAND_COUNT and all(band["type"] in TYPE_TO_CODE for band in filters)
                profiles.append(
                    {
                        "slot": slot,
                        "name": SLOT_NAMES.get(slot),
                        "preamp": preamp,
                        "global_gain_db": global_gain,
                        "bands": bands,
                        "filter_curve_flat": False if non_neutral else (True if known else None),
                    }
                )
        finally:
            if switched:
                try:
                    activate_slot(dev, original_slot)
                    initial = profiles[0]
                    if dev.preamp() != initial["preamp"] or dev.global_gain() != initial["global_gain_db"]:
                        raise HidError("Po powrocie do slotu początkowego zmienił się gain.")
                except HidError as exc:
                    raise HidError(f"Nie potwierdzono przywrócenia stanu slotu {original_slot}: {exc}") from exc
    print(
        json.dumps(
            {
                "usb": "35d8:0123",
                "firmware": firmware,
                "initial_slot": original_slot,
                "slots": profiles,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def load_eq_file(path: str) -> tuple[list[dict], dict]:
    """Zwraca (pasma, metadane z pliku: slot/preamp)."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    meta: dict = {}
    if isinstance(data, dict):
        meta = {
            k: data[k]
            for k in (
                "name",
                "source",
                "slot",
                "preamp",
                "global_gain_db",
                "mic_gain_raw",
                "target_name",
                "target_curve",
                "meta",
            )
            if k in data
        }
        data = data.get("bands", data.get("filters", []))
    if not isinstance(data, list):
        raise SystemExit("Plik EQ musi być listą pasm lub obiektem z polem 'bands'.")
    bands = []
    for i, item in enumerate(data):
        try:
            bands.append(
                {
                    "band": i + 1,
                    "freq": float(item["freq"]),
                    "gain": float(item["gain"]),
                    "q": float(item.get("q", 0.7071068)),
                    "type": str(item.get("type", "PK")).upper(),
                }
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SystemExit(f"Błąd w paśmie {i + 1}: {exc}") from exc
    return bands, meta


def requested_profile(args) -> tuple[list[dict], int | None, float | None]:
    bands, meta = load_eq_file(args.file)
    slot = args.slot if args.slot is not None else meta.get("slot")
    preamp = args.preamp if args.preamp is not None else meta.get("preamp")
    validate_profile(bands, slot, preamp)
    return bands, slot, preamp


def validate_profile(bands: list[dict], slot: int | None, preamp: float | None) -> None:
    if not 1 <= len(bands) <= BAND_COUNT:
        raise HidError(f"Profil musi zawierać od 1 do {BAND_COUNT} pasm.")
    for band in bands:
        if (
            band["type"] not in TYPE_TO_CODE
            or not 20 <= band["freq"] <= 20000
            or not 0.1 <= band["q"] <= 10
            or not -128 <= band["gain"] <= 32767 / 256
        ):
            raise HidError(f"Nieprawidłowe parametry pasma {band['band']}.")
    if slot is not None and (type(slot) is not int or not 0 <= slot <= 255):
        raise HidError("Nieprawidłowy numer slotu.")
    if preamp is not None and (not isinstance(preamp, (int, float)) or not -128 <= preamp <= 32767 / 256):
        raise HidError("Nieprawidłowy pre-gain.")


def quantized_band(band: dict) -> dict:
    return {
        **band,
        "freq": round(band["freq"]),
        "gain": clamp_i16(band["gain"] * 256) / 256,
        "q": clamp_i16(band["q"] * 256) / 256,
    }


def expected_band_readback(band: dict) -> dict:
    expected = quantized_band(band)
    # Starszy zapis półki o dużym Q może mieć te same parametry i inne współczynniki.
    if "coefficients" not in expected and band["type"] in ("LSQ", "HSQ") and band["q"] > 1:
        expected["coefficients"] = biquad_coefficients(
            TYPE_TO_CODE[band["type"]], band["freq"], band["gain"], band["q"]
        )
    return expected


def _nearest_half_db(raw: int) -> float:
    # Połówki zaokrąglamy w stronę większego tłumienia.
    return ((raw + 63) // 128) / 2


def preamp_matches(actual: float, requested: float, *, allow_half_db: bool = False) -> bool:
    raw = clamp_i16(requested * 256)
    rounded = _nearest_half_db(raw)
    return actual == raw / 256 or (allow_half_db and actual == rounded and rounded < 128)


def verify_profile(
    dev: MoondropPosition, bands: list[dict], slot: int | None, preamp: float | None, *, allow_half_db: bool = False
) -> None:
    if not isinstance(dev, MoondropPosition) and hasattr(dev, "verify_profile"):
        dev.verify_profile(bands, slot, preamp)
        return
    actual_slot = dev.slot()
    if slot is not None and actual_slot != slot:
        raise HidError(f"Slot: odczytano {actual_slot}, oczekiwano {slot}.")
    for index, band in enumerate(bands):
        expected = expected_band_readback(band)
        actual = dev.read_band(index, include_coefficients="coefficients" in expected)
        if actual != expected:
            raise HidError(f"Pasmo {index + 1}: odczytano {actual}, oczekiwano {expected}.")
        time.sleep(DELAY_BAND_MS / 1000.0)
    if preamp is not None:
        expected_preamp = clamp_i16(preamp * 256) / 256
        actual_preamp = dev.preamp()
        if not preamp_matches(actual_preamp, preamp, allow_half_db=allow_half_db):
            raise HidError(f"Pre-gain: odczytano {actual_preamp}, oczekiwano {expected_preamp}.")
    if dev.slot() != actual_slot:
        raise HidError("Aktywny slot zmienił się w trakcie weryfikacji.")


def apply_preamp(dev: MoondropPosition, db: float) -> bool:
    if not isinstance(dev, MoondropPosition) and hasattr(dev, "apply_preamp"):
        return dev.apply_preamp(db)
    return _write_preamp(dev, db)[0]


def _write_preamp(dev: MoondropPosition, db: float, *, allow_half_db: bool = False) -> tuple[bool, float]:
    raw = clamp_i16(db * 256)
    expected = raw / 256
    initial = dev.preamp()
    if initial == expected:
        return False, initial
    rounded = _nearest_half_db(raw)
    targets = (expected, rounded) if allow_half_db and expected != rounded and rounded < 128 else (expected,)
    # devicePEQ wysyła LEN=0, FreeDSP Studio wysyła LEN=2.
    for target in targets:
        for legacy in (True, False):
            dev.set_preamp(target, legacy=legacy)
            time.sleep(DELAY_OP_MS / 1000.0)
            actual = dev.preamp()
            if actual == target:
                return actual != initial, actual
        if len(targets) == 2 and actual == rounded:
            return actual != initial, actual
    raise HidError(f"Pre-gain po próbie obu formatów: odczytano {actual:+.3f} dB, oczekiwano {expected:+.3f} dB.")


def write_profile(
    dev: MoondropPosition,
    bands: list[dict],
    preamp: float | None,
    slot: int = CUSTOM_SLOT,
    *,
    persist: bool = True,
    previous_bands: list[dict] | None = None,
    allow_half_db: bool = False,
) -> float | None:
    if not isinstance(dev, MoondropPosition) and hasattr(dev, "write_profile"):
        return dev.write_profile(bands, preamp, slot=slot, persist=persist, previous_bands=previous_bands)
    validate_profile(bands, slot, preamp)
    if slot != CUSTOM_SLOT:
        raise HidError("Zapis EQ jest dostępny tylko w slocie 7 (Custom).")
    coefficients = [
        band["coefficients"]
        if "coefficients" in band
        else biquad_coefficients(TYPE_TO_CODE[band["type"]], band["freq"], band["gain"], band["q"], for_write=True)
        for band in bands
    ]
    if dev.slot() != slot:
        activate_slot(dev, slot)
        previous_bands = None
    for index, band in enumerate(bands):
        if previous_bands is not None and index < len(previous_bands):
            expected = expected_band_readback(band)
            previous = expected_band_readback(previous_bands[index])
            if "coefficients" not in expected:
                previous.pop("coefficients", None)
            if expected == previous:
                continue
        dev.write_band(
            index, band["freq"], band["gain"], band["q"], band["type"], slot, coefficients=coefficients[index]
        )
        time.sleep(DELAY_BAND_MS / 1000.0)
        dev.latch_band(index)
        time.sleep(DELAY_BAND_MS / 1000.0)
    applied_preamp = None
    if preamp is not None:
        _, applied_preamp = _write_preamp(dev, preamp, allow_half_db=allow_half_db)
    verify_profile(dev, bands, slot, applied_preamp)
    if persist:
        dev.save()
        time.sleep(DELAY_FLASH_MS / 1000.0)
        verify_profile(dev, bands, slot, applied_preamp)
    return applied_preamp


def cmd_verify_eq(args) -> int:
    bands, slot, preamp = requested_profile(args)
    with open_device(args) as dev:
        verify_profile(dev, bands, slot, preamp, allow_half_db=True)
    print(f"Zgodność profilu potwierdzona odczytem ({len(bands)} pasm).")
    return 0


def cmd_write_eq(args) -> int:
    bands, slot, preamp = requested_profile(args)
    if slot is not None and slot != CUSTOM_SLOT:
        raise HidError("Zapis EQ jest dostępny tylko w slocie 7 (Custom).")

    if args.dry_run:
        print(
            f"DRY-RUN: {len(bands)} pasm, slot={slot if slot is not None else '?'}"
            f", preamp={preamp if preamp is not None else '(bez zmian)'}"
        )
        for i, band in enumerate(bands):
            code = TYPE_TO_CODE.get(band["type"])
            if code is None:
                raise SystemExit(f"Nieznany typ filtra: {band['type']}")
            payload = bytearray(63)
            payload[0] = OP_WRITE
            payload[1] = CMD_EQ_UPDATE
            payload[2] = 0x18
            payload[4] = i
            payload[7:27] = biquad_coefficients(code, band["freq"], band["gain"], band["q"], for_write=True)
            struct.pack_into("<H", payload, 27, round(band["freq"]))
            struct.pack_into("<h", payload, 29, clamp_i16(band["q"] * 256))
            struct.pack_into("<h", payload, 31, clamp_i16(band["gain"] * 256))
            payload[33] = code
            payload[35] = slot if slot is not None else 7
            print(f"  pasmo {i + 1}: " + " ".join(f"{b:02x}" for b in payload[:36]))
        if preamp is not None:
            for legacy in (True, False):
                payload = preamp_payload(preamp, legacy=legacy)
                print(f"  preamp (LEN={payload[2]}): " + " ".join(f"{b:02x}" for b in payload))
        print("  save  : 01 01")
        return 0

    with open_device(args) as dev:
        active_slot = dev.slot()
        current_slot = active_slot if slot is None else slot
        if current_slot != CUSTOM_SLOT:
            raise HidError("Zapis EQ jest dostępny tylko w slocie 7 (Custom).")
        print(f"Urządzenie: {dev.path}  firmware={dev.version()}  slot docelowy={current_slot}")
        if not args.yes and sys.stdin.isatty():
            answer = input(f"Zapisać {len(bands)} pasm do flash urządzenia? [t/N] ")
            if answer.strip().lower() not in ("t", "tak", "y", "yes"):
                print("Przerwano.")
                return 1
        applied_preamp = write_profile(dev, bands, preamp, current_slot, allow_half_db=True)
    if preamp is not None and not preamp_matches(applied_preamp, preamp):
        print(f"Pre-gain z odczytu: {applied_preamp:+.2f} dB (profil: {preamp:+.2f} dB).")
    print(f"Zapis zakończony; odczyt potwierdził zgodność {len(bands)} pasm.")
    return 0


def cmd_preamp(args) -> int:
    with open_device(args) as dev:
        if args.value is None:
            print(f"{dev.preamp():+.3f} dB")
        else:
            if apply_preamp(dev, args.value):
                dev.save()
                time.sleep(DELAY_FLASH_MS / 1000.0)
                verify_profile(dev, [], None, args.value)
            print(f"Pre-gain potwierdzony odczytem: {dev.preamp():+.3f} dB")
    return 0


def cmd_slot(args) -> int:
    with open_device(args) as dev:
        if args.value is None:
            print(dev.slot())
        else:
            if dev.slot() != args.value:
                activate_slot(dev, args.value)
                dev.save()
                time.sleep(DELAY_FLASH_MS / 1000.0)
                verify_profile(dev, [], args.value, None)
            print(f"Potwierdzono aktywny slot {args.value}.")
    return 0


# --------------------------------------------------------------------------
# Import z autoeq.app / Equalizer APO
# --------------------------------------------------------------------------

EQAPO_TYPES = {
    "PK": "PK",
    "PEAK": "PK",
    "PEAKING": "PK",
    "LS": "LSQ",
    "LSC": "LSQ",
    "LSQ": "LSQ",
    "LOW_SHELF": "LSQ",
    "HS": "HSQ",
    "HSC": "HSQ",
    "HSQ": "HSQ",
    "HIGH_SHELF": "HSQ",
    "LP": "LP",
    "LPQ": "LP",
    "LOW_PASS": "LP",
    "HP": "HP",
    "HPQ": "HP",
    "HIGH_PASS": "HP",
}

RE_EQAPO_PREAMP = re.compile(r"^\s*Preamp:\s*(-?[\d.]+)\s*dB", re.IGNORECASE)
# Filter 3: ON PK Fc 170 Hz Gain -2.8 dB Q 0.87
RE_EQAPO_FILTER = re.compile(
    r"Filter\s*\d+:\s*(ON|OFF)\s+(\w+)\s+Fc\s+([\d.]+)\s*Hz"
    r"(?:\s+Gain\s+(-?[\d.]+)\s*dB)?(?:\s+Q\s+([\d.]+))?",
    re.IGNORECASE,
)


def parse_eqapo(path: str) -> tuple[list[dict], float | None]:
    """Parsuje eksport Equalizer APO (m.in. z autoeq.app) na pasma urządzenia."""
    bands: list[dict] = []
    preamp: float | None = None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            match = RE_EQAPO_PREAMP.search(line)
            if match:
                preamp = float(match.group(1))
                continue
            match = RE_EQAPO_FILTER.search(line)
            if not match:
                continue
            enabled, raw_type, freq, gain, q = match.groups()
            if enabled.upper() != "ON":
                continue
            ftype = EQAPO_TYPES.get(raw_type.upper())
            if ftype is None:
                raise SystemExit(f"Nieznany typ filtra w pliku: {raw_type}")
            bands.append(
                {
                    "band": len(bands) + 1,
                    "freq": round(float(freq), 1),
                    "gain": round(float(gain or 0.0), 3),
                    "q": round(float(q or 0.7071068), 3),
                    "type": ftype,
                }
            )
    if not bands:
        raise SystemExit(f"Nie znaleziono filtrów Equalizer APO w {path}")
    return bands, preamp


def format_eqapo(bands: list[dict], preamp: float | None = None) -> str:
    """Formatuje pasma urządzenia jako tekst konfiguracyjny Equalizer APO."""
    type_map = {"PK": "PK", "LP": "LPQ", "HP": "HPQ"}
    lines: list[str] = []
    if preamp is not None:
        lines.append(f"Preamp: {preamp:.2f} dB")
    for idx, band in enumerate(bands, 1):
        apo_type = type_map.get(str(band.get("type", "PK")).upper(), "PK")
        freq = float(band.get("freq", 1000.0))
        gain = float(band.get("gain", 0.0))
        q = float(band.get("q", 1.0))
        lines.append(f"Filter {idx}: ON {apo_type} Fc {freq:.1f} Hz Gain {gain:.2f} dB Q {q:.3f}")
    return "\n".join(lines) + "\n"


def cmd_import_eq(args) -> int:
    bands, file_preamp = parse_eqapo(args.file)
    preamp = args.preamp if args.preamp is not None else file_preamp
    out_of_range = [b for b in bands if not (20 <= b["freq"] <= 20000 and b["q"] > 0)]
    if out_of_range:
        print(
            "Uwaga: część pasm poza typowymi limitami urządzenia "
            "(freq 20–20 000 Hz): " + ", ".join(str(b["band"]) for b in out_of_range),
            file=sys.stderr,
        )
    profile = {
        "device": "MOONDROP:Gravity Position",
        "usb": "35d8:0123",
        "slot": args.slot,
        "preamp": round(preamp, 2) if preamp is not None else 0.0,
        "bands": bands,
        "meta": {
            "source": os.path.basename(args.file),
            "imported": "Equalizer APO / autoeq.app",
        },
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(profile, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"Zaimportowano {len(bands)} pasm (preamp {profile['preamp']:+.2f} dB) → {args.out}")
    for band in bands:
        print("  " + fmt_band(band))
    print(f"\nZapis do DAC-a: moondrop_position.py write-eq --file {args.out} --yes")
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--device", metavar="PATH", help="ścieżka /dev/hidrawN (domyślnie autodetekcja)")
    common.add_argument(
        "--timeout", type=int, default=REPLY_TIMEOUT_MS, metavar="MS", help="timeout odpowiedzi HID (ms)"
    )
    common.add_argument("--json", action="store_true", help="wyjście JSON")

    parser = argparse.ArgumentParser(
        description="MOONDROP:Gravity Position (35d8:0123): odczyt/zapis DSP przez HID 0x4B",
        epilog="Przykłady:\n"
        "  %(prog)s list\n"
        "  %(prog)s info\n"
        "  %(prog)s read-eq --json\n"
        "  %(prog)s write-eq --file data/example-eq.json --dry-run\n"
        "  %(prog)s write-eq --file data/example-eq.json --yes\n"
        "  %(prog)s import-eq --file eqapo.txt --out data/profiles/profile.json\n"
        "  %(prog)s preamp --value -3.5\n"
        "  %(prog)s slot --value 7\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list", help="pokaż urządzenie i uprawnienia")
    p_list.set_defaults(func=cmd_list)

    p_info = sub.add_parser("info", parents=[common], help="firmware, slot, preamp i pasma EQ")
    p_info.add_argument("--bands", type=int, default=8, help="ile pasm odczytać (domyślnie 8)")
    p_info.set_defaults(func=cmd_info)

    p_read = sub.add_parser("read-eq", parents=[common], help="odczytaj EQ")
    p_read.add_argument("--bands", type=int, default=8, help="ile pasm odczytać (domyślnie 8)")
    p_read.set_defaults(func=cmd_read_eq)

    p_dump = sub.add_parser("dump-slots", parents=[common], help="zrzut EQ aktywnego slotu jako JSON")
    p_dump.add_argument(
        "--switch", action="store_true", help="przełącz tymczasowo między slotami 0 i 7 bez polecenia zapisu flash"
    )
    p_dump.set_defaults(func=cmd_dump_slots)

    p_verify = sub.add_parser("verify-eq", parents=[common], help="porównaj ustawienia DAC-a z profilem JSON")
    p_verify.add_argument("--file", required=True, metavar="JSON")
    p_verify.add_argument("--slot", type=int, metavar="N")
    p_verify.add_argument("--preamp", type=float, metavar="DB")
    p_verify.set_defaults(func=cmd_verify_eq)

    p_write = sub.add_parser("write-eq", parents=[common], help="zapisz EQ z pliku JSON do flash")
    p_write.add_argument("--file", required=True, metavar="JSON", help="lista pasm: [{freq,gain,q,type}, ...]")
    p_write.add_argument("--preamp", type=float, default=None, metavar="DB", help="pre-gain do zapisania")
    p_write.add_argument("--slot", type=int, default=None, metavar="N", help="slot docelowy (domyślnie bieżący)")
    p_write.add_argument("--dry-run", action="store_true", help="tylko pokaż ramki, nic nie zapisuj")
    p_write.add_argument("--yes", action="store_true", help="nie pytaj o potwierdzenie")
    p_write.set_defaults(func=cmd_write_eq)

    p_pre = sub.add_parser("preamp", parents=[common], help="odczyt/zapis pre-gain")
    p_pre.add_argument("--value", type=float, default=None, metavar="DB")
    p_pre.set_defaults(func=cmd_preamp)

    p_slot = sub.add_parser("slot", parents=[common], help="odczyt/zmiana slotu EQ")
    p_slot.add_argument("--value", type=int, default=None, metavar="N")
    p_slot.set_defaults(func=cmd_slot)

    p_import = sub.add_parser("import-eq", help="zaimportuj EQ z autoeq.app (eksport Equalizer APO) do profilu JSON")
    p_import.add_argument("--file", required=True, metavar="TXT", help="plik Equalizer APO (np. z autoeq.app)")
    p_import.add_argument("--out", required=True, metavar="JSON", help="docelowy profil JSON")
    p_import.add_argument("--preamp", type=float, default=None, metavar="DB", help="nadpisz preamp z pliku")
    p_import.add_argument("--slot", type=int, default=7, metavar="N", help="slot docelowy (domyślnie 7 = Custom)")
    p_import.set_defaults(func=cmd_import_eq)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        args = parser.parse_args((argv or []) + ["info"])
    try:
        return args.func(args)
    except HidError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
