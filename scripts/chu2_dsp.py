#!/usr/bin/env python3
"""Experimental driver for MOONDROP CHU II DSP (31b2:0113, KTMicro KT0210).

Protocol documented in open-source references:
  * jeromeof/devicePEQ (0BSD) — devicePEQ/ktmicroUsbHidHandler.js, ktmicro_chu2_dsp.json
  * jcharvet/chu2-studio (MIT) — docs/PROTOCOL.md

Frame format (HID report 0x4B, 10-byte payload excluding report ID):
    [reg, 0x00, 0x00, 0x00, cmd, 0x00, v0, v1, v2, v3]
    cmd: 0x52 ('R' read), 0x57 ('W' write), 0x53 ('S' commit), 0x43 ('C' clear)

Hardware note: committing EQ (0x53) restarts the USB device for ~1-1.5 s.
"""

from __future__ import annotations

import struct
import time

from dac_devices import DacModel
from dac_transport import HidError, HidrawTransport, HidReport

REPORT_ID = 0x4B
PAYLOAD_LEN = 10
VENDOR_ID = 0x31B2
PRODUCT_ID = 0x0113
MODEL_NAME = "MOONDROP CHU II DSP"
BAND_COUNT = 5
CUSTOM_SLOT = 0x03
OFF_SLOT = 0x02
SLOT_NAMES = {OFF_SLOT: "Off", CUSTOM_SLOT: "Custom"}
SUPPORTED_TYPES = ("PK", "LSQ", "HSQ")
GAIN_RANGE = (-12.0, 12.0)
PREAMP_RANGE = (0.0, 0.0)

CMD_CLEAR = 0x43
CMD_READ = 0x52
CMD_COMMIT = 0x53
CMD_WRITE = 0x57

REG_COMMIT = 0x00
REG_SLOT = 0x24
REG_BAND_BASE = 0x26
REG_PREGAIN = 0x66

TYPE_TO_CODE = {"PK": 0, "LSQ": 3, "HSQ": 4}
CODE_TO_TYPE = {v: k for k, v in TYPE_TO_CODE.items()}

REPLY_TIMEOUT_MS = 800
DELAY_BAND_MS = 15


class Chu2Dsp:
    """Experimental KTMicro KT0210 HID driver for MOONDROP CHU II DSP."""

    model_id = "moondrop-chu2-dsp"
    model_name = MODEL_NAME
    experimental = True
    band_count = BAND_COUNT
    supported_types = SUPPORTED_TYPES
    gain_range = GAIN_RANGE
    preamp_range = PREAMP_RANGE
    custom_slot = CUSTOM_SLOT
    slot_names = SLOT_NAMES
    sample_rate_hz = 48000.0
    reconnect_on_save = True

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
        if len(payload) != PAYLOAD_LEN:
            raise ValueError(f"Expected {PAYLOAD_LEN}-byte payload, got {len(payload)}")
        self.transport.write_report(bytes([REPORT_ID]) + payload)

    def _read_reply(self, reg: int, cmd: int) -> bytes | None:
        deadline = time.monotonic() + self.timeout_ms / 1000.0
        while True:
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                return None
            raw = self.transport.read_report(remaining_ms, size=PAYLOAD_LEN + 1)
            if raw is None or len(raw) < PAYLOAD_LEN + 1 or raw[0] != REPORT_ID:
                continue
            payload = raw[1 : 1 + PAYLOAD_LEN]
            if payload[0] == reg and payload[4] == cmd:
                return payload

    def request(
        self, reg: int, cmd: int, v0: int = 0, v1: int = 0, v2: int = 0, v3: int = 0, *, retries: int = 2
    ) -> bytes:
        frame = bytes((reg & 0xFF, 0, 0, 0, cmd & 0xFF, 0, v0 & 0xFF, v1 & 0xFF, v2 & 0xFF, v3 & 0xFF))
        for attempt in range(retries + 1):
            self.transport.drain(size=PAYLOAD_LEN + 1)
            self._write_frame(frame)
            reply = self._read_reply(reg, cmd)
            if reply is not None:
                return reply
            if attempt < retries:
                time.sleep(0.02)
        raise HidError(f"Brak odpowiedzi CHU II DSP dla reg=0x{reg:02x} cmd=0x{cmd:02x}.")

    def version(self) -> str:
        return "KT0210"

    def slot(self) -> int:
        reply = self.request(REG_SLOT, CMD_READ, v0=CUSTOM_SLOT)
        return reply[6]

    def set_slot(self, slot: int, *, legacy: bool = False) -> bytes:
        del legacy
        target = CUSTOM_SLOT if slot != OFF_SLOT else OFF_SLOT
        return self.request(REG_SLOT, CMD_WRITE, v0=target)

    def read_band(self, index: int, *, include_coefficients: bool = False) -> dict | None:
        if not 0 <= index < BAND_COUNT:
            raise ValueError(f"CHU II DSP ma 5 pasm (0..4), podano {index}.")
        gain_reg = REG_BAND_BASE + index * 2
        q_reg = gain_reg + 1
        gf = self.request(gain_reg, CMD_READ)
        qt = self.request(q_reg, CMD_READ)
        gain_raw, freq = struct.unpack("<hH", gf[6:10])
        q_raw = struct.unpack("<H", qt[6:8])[0]
        ftype_code = qt[8]
        ftype = CODE_TO_TYPE.get(ftype_code, "PK")
        band = {
            "band": index + 1,
            "freq": int(freq),
            "gain": round(gain_raw / 10.0, 2),
            "q": round(q_raw / 1000.0, 3),
            "type": ftype,
        }
        if include_coefficients:
            band["coefficients"] = b""
        return band

    def read_eq(self, bands: int | None = None, *, include_coefficients: bool = False) -> list[dict]:
        count = BAND_COUNT if bands is None else min(bands, BAND_COUNT)
        result = []
        for idx in range(count):
            band = self.read_band(idx, include_coefficients=include_coefficients)
            if band is not None:
                result.append(band)
            time.sleep(DELAY_BAND_MS / 1000.0)
        return result

    def preamp(self) -> float:
        # 0x66 reads back an acknowledged byte, but has no live audible effect on CHU II DSP.
        reply = self.request(REG_PREGAIN, CMD_READ)
        val = struct.unpack("<b", reply[6:7])[0]
        return float(val)

    def global_gain(self) -> int | None:
        return None

    def write_band(
        self,
        index: int,
        ftype: int | str,
        freq: float,
        gain: float,
        q: float,
        *,
        slot: int | None = None,
    ) -> bytes:
        del slot
        if not 0 <= index < BAND_COUNT:
            raise ValueError(f"CHU II DSP ma 5 pasm (0..4), podano {index}.")
        type_name = CODE_TO_TYPE.get(ftype, "PK") if isinstance(ftype, int) else str(ftype)
        if type_name not in TYPE_TO_CODE:
            raise ValueError(f"CHU II DSP nie obsługuje typu filtra {type_name}.")
        ftype_code = TYPE_TO_CODE[type_name]
        gain_i16 = max(-120, min(120, round(float(gain) * 10.0)))
        freq_u16 = max(20, min(20000, round(float(freq))))
        q_u16 = max(100, min(10000, round(float(q) * 1000.0)))

        gain_reg = REG_BAND_BASE + index * 2
        q_reg = gain_reg + 1
        gf_payload = struct.pack("<hH", gain_i16, freq_u16)
        qt_payload = struct.pack("<HBB", q_u16, ftype_code, 0)
        self._write_frame(bytes((gain_reg, 0, 0, 0, CMD_WRITE, 0)) + gf_payload)
        time.sleep(DELAY_BAND_MS / 1000.0)
        self._write_frame(bytes((q_reg, 0, 0, 0, CMD_WRITE, 0)) + qt_payload)
        time.sleep(DELAY_BAND_MS / 1000.0)
        return gf_payload + qt_payload

    def latch_band(self, index: int) -> bytes:
        del index
        return b""

    def set_preamp(self, db: float, *, legacy: bool = True) -> bytes:
        del db, legacy
        return b""

    def save(self) -> bytes:
        # Commit causes CHU II DSP to restart over USB for ~1-1.5 s.
        frame = bytes((REG_COMMIT, 0, 0, 0, CMD_COMMIT, 0, 0, 0, 0, 0))
        self.transport.drain(size=PAYLOAD_LEN + 1)
        self._write_frame(frame)
        reply = self._read_reply(REG_COMMIT, CMD_COMMIT)
        return reply or frame

    def _expected_band(self, index: int, band: dict) -> dict:
        gain = max(-12.0, min(12.0, float(band["gain"])))
        freq = max(20, min(20000, round(float(band["freq"]))))
        q = max(0.1, min(10.0, float(band["q"])))
        return {
            "band": index + 1,
            "freq": freq,
            "gain": round(round(gain * 10.0) / 10.0, 2),
            "q": round(round(q * 1000.0) / 1000.0, 3),
            "type": band["type"],
        }

    def verify_profile(self, bands: list[dict], slot: int | None = None, preamp: float | None = None) -> None:
        del preamp
        if slot is not None and slot not in (OFF_SLOT, CUSTOM_SLOT):
            raise HidError(
                f"CHU II DSP obsługuje wyłącznie sloty {OFF_SLOT} (Off) i {CUSTOM_SLOT} (Custom), podano {slot}."
            )
        actual_slot = self.slot()
        if slot is not None and actual_slot != slot:
            raise HidError(f"CHU II DSP slot: odczytano {actual_slot}, oczekiwano {slot}.")
        for index, band in enumerate(bands):
            expected = self._expected_band(index, band)
            actual = self.read_band(index)
            if actual != expected:
                raise HidError(f"CHU II DSP pasmo {index + 1}: odczytano {actual}, oczekiwano {expected}.")
            time.sleep(DELAY_BAND_MS / 1000.0)

    def apply_preamp(self, db: float) -> bool:
        del db
        return False

    def write_profile(
        self,
        bands: list[dict],
        preamp: float | None = None,
        *,
        slot: int | None = None,
        persist: bool = True,
        previous_bands: list[dict] | None = None,
    ) -> float | None:
        del preamp
        if not 1 <= len(bands) <= BAND_COUNT:
            raise HidError(f"CHU II DSP obsługuje od 1 do {BAND_COUNT} pasm.")
        for band in bands:
            if (
                band["type"] not in TYPE_TO_CODE
                or not 20 <= band["freq"] <= 20000
                or not 0.1 <= band["q"] <= 10.0
                or not -12.0 <= band["gain"] <= 12.0
            ):
                raise HidError(f"Nieprawidłowe parametry pasma {band.get('band', '?')} dla CHU II DSP.")
        target_slot = CUSTOM_SLOT if slot is None else slot
        if target_slot not in (OFF_SLOT, CUSTOM_SLOT):
            raise HidError(
                f"CHU II DSP obsługuje wyłącznie sloty {OFF_SLOT} (Off) i {CUSTOM_SLOT} (Custom), podano {target_slot}."
            )
        if self.slot() != target_slot:
            self.set_slot(target_slot)
            previous_bands = None
        for index, band in enumerate(bands):
            if (
                previous_bands is not None
                and index < len(previous_bands)
                and self._expected_band(index, band) == self._expected_band(index, previous_bands[index])
            ):
                continue
            self.write_band(index, band["type"], band["freq"], band["gain"], band["q"], slot=target_slot)
        self.verify_profile(bands, target_slot)
        if persist:
            # Flash commit triggers USB re-enumeration (~1-1.5 s); close old handle cleanly.
            self.save()
            self.transport.close()
        return None


CHU2_MODEL = DacModel(
    model_id="moondrop-chu2-dsp",
    display_name=MODEL_NAME,
    usb_id=(VENDOR_ID, PRODUCT_ID),
    reports=frozenset(HidReport(REPORT_ID, kind, PAYLOAD_LEN) for kind in ("input", "output")),
    connect=Chu2Dsp,
)
