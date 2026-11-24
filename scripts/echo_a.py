#!/usr/bin/env python3
"""Experimental driver for MOONDROP ECHO-A (3302:12c5, WalkPlay SchemeNo 11).

Protocol documented in open-source references:
  * Chronosauros/contour (Apache-2.0) — devices/moondrop-echo-a.json, echo-a-read-195126.log
  * jeromeof/devicePEQ (0BSD) — devicePEQ/walkplayHidHandler.js

Frame format (HID report 0x4B, 63-byte payload excluding report ID):
    [0x4B] [OP] [CMD] [LEN] [payload...]
    OP = 0x01 write, 0x80 read.
"""

from __future__ import annotations

import math
import struct
import time

from dac_devices import DacModel
from dac_transport import HidError, HidrawTransport, HidReport

REPORT_ID = 0x4B
PAYLOAD_LEN = 63
VENDOR_ID = 0x3302
PRODUCT_ID = 0x12C5
MODEL_NAME = "MOONDROP ECHO-A"
BAND_COUNT = 8
CUSTOM_SLOT = 0
SLOT_NAMES = {0: "Custom"}
SUPPORTED_TYPES = ("PK", "LSQ", "HSQ", "LP", "HP")
GAIN_RANGE = (-10.0, 10.0)
PREAMP_RANGE = (-30.0, 0.0)

OP_WRITE = 0x01
OP_READ = 0x80

CMD_FLASH_EQ = 0x01
CMD_GLOBAL_GAIN = 0x03
CMD_RESET_STEP = 0x05
CMD_PEQ_VALUES = 0x09
CMD_TEMP_WRITE = 0x0A
CMD_VERSION = 0x0C
CMD_COMMIT_PREP = 0x17

TYPE_TO_CODE = {"LSQ": 1, "PK": 2, "HSQ": 3, "LP": 4, "HP": 5}
CODE_TO_TYPE = {v: k for k, v in TYPE_TO_CODE.items()}

COEFF_FS = 93750.0
COEFF_SCALE = float(1 << 30)

DELAY_BAND_MS = 25
DELAY_OP_MS = 50
DELAY_FLASH_MS = 200
REPLY_TIMEOUT_MS = 700


def _clamp_i32(value: float) -> int:
    return max(-0x80000000, min(0x7FFFFFFF, round(value)))


def biquad_coefficients(ftype: int, freq: float, gain: float, q: float) -> bytes:
    """Compute Q2.30 RBJ biquad coefficients (20 bytes LE) for WalkPlay frames."""
    w0 = 2.0 * math.pi * float(freq) / COEFF_FS
    cos_w0 = math.cos(w0)
    sin_w0 = math.sin(w0)
    q_safe = max(0.1, float(q))
    amp = math.pow(10.0, float(gain) / 40.0)
    alpha = sin_w0 / (2.0 * q_safe)

    if ftype in (1, 3):  # LSQ / HSQ
        shelf_alpha = (sin_w0 / 2.0) * math.sqrt(max(0.0, (amp + 1.0 / amp) * (1.0 / q_safe - 1.0) + 2.0))
        two_sqrt_a_alpha = 2.0 * math.sqrt(amp) * shelf_alpha
        if ftype == 1:
            b0 = amp * ((amp + 1.0) - (amp - 1.0) * cos_w0 + two_sqrt_a_alpha)
            b1 = 2.0 * amp * ((amp - 1.0) - (amp + 1.0) * cos_w0)
            b2 = amp * ((amp + 1.0) - (amp - 1.0) * cos_w0 - two_sqrt_a_alpha)
            a0 = (amp + 1.0) + (amp - 1.0) * cos_w0 + two_sqrt_a_alpha
            a1 = -2.0 * ((amp - 1.0) + (amp + 1.0) * cos_w0)
            a2 = (amp + 1.0) + (amp - 1.0) * cos_w0 - two_sqrt_a_alpha
        else:
            b0 = amp * ((amp + 1.0) + (amp - 1.0) * cos_w0 + two_sqrt_a_alpha)
            b1 = -2.0 * amp * ((amp - 1.0) + (amp + 1.0) * cos_w0)
            b2 = amp * ((amp + 1.0) + (amp - 1.0) * cos_w0 - two_sqrt_a_alpha)
            a0 = (amp + 1.0) - (amp - 1.0) * cos_w0 + two_sqrt_a_alpha
            a1 = 2.0 * ((amp - 1.0) - (amp + 1.0) * cos_w0)
            a2 = (amp + 1.0) - (amp - 1.0) * cos_w0 - two_sqrt_a_alpha
    elif ftype == 4:  # LP
        b0 = (1.0 - cos_w0) / 2.0
        b1 = 1.0 - cos_w0
        b2 = (1.0 - cos_w0) / 2.0
        a0 = 1.0 + alpha
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha
    elif ftype == 5:  # HP
        b0 = (1.0 + cos_w0) / 2.0
        b1 = -(1.0 + cos_w0)
        b2 = (1.0 + cos_w0) / 2.0
        a0 = 1.0 + alpha
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha
    else:  # PK
        b0 = 1.0 + alpha * amp
        b1 = -2.0 * cos_w0
        b2 = 1.0 - alpha * amp
        a0 = 1.0 + alpha / amp
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha / amp

    vals = [
        _clamp_i32((b0 / a0) * COEFF_SCALE),
        _clamp_i32((b1 / a0) * COEFF_SCALE),
        _clamp_i32((b2 / a0) * COEFF_SCALE),
        _clamp_i32((-a1 / a0) * COEFF_SCALE),
        _clamp_i32((-a2 / a0) * COEFF_SCALE),
    ]
    return struct.pack("<5i", *vals)


class EchoA:
    """Experimental WalkPlay SchemeNo 11 HID driver for MOONDROP ECHO-A."""

    model_id = "moondrop-echo-a"
    model_name = MODEL_NAME
    experimental = True
    band_count = BAND_COUNT
    supported_types = SUPPORTED_TYPES
    gain_range = GAIN_RANGE
    preamp_range = PREAMP_RANGE
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
        padded = payload[:PAYLOAD_LEN].ljust(PAYLOAD_LEN, b"\x00")
        self.transport.write_report(bytes([REPORT_ID]) + padded)

    def _read_reply(self, cmd: int, index: int | None = None) -> bytes | None:
        deadline = time.monotonic() + self.timeout_ms / 1000.0
        while True:
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                return None
            raw = self.transport.read_report(remaining_ms, size=PAYLOAD_LEN + 1)
            if raw is None or len(raw) < 4 or raw[0] != REPORT_ID:
                continue
            payload = raw[1:]
            if payload[1] != cmd:
                continue
            if index is not None and len(payload) > 4 and payload[4] != index:
                continue
            return payload

    def request(self, cmd: int, payload: bytes, index: int | None = None, *, retries: int = 2) -> bytes:
        for attempt in range(retries + 1):
            self.transport.drain(size=PAYLOAD_LEN + 1)
            self._write_frame(payload)
            reply = self._read_reply(cmd, index=index)
            if reply is not None:
                return reply
            if attempt < retries:
                time.sleep(0.03)
        raise HidError(f"Brak odpowiedzi ECHO-A dla CMD=0x{cmd:02x}.")

    def version(self) -> str:
        reply = self.request(CMD_VERSION, bytes((OP_READ, CMD_VERSION, 0x00)))
        raw = reply[3:11].split(b"\x00", 1)[0]
        return raw.decode("ascii", errors="replace").strip() or "?"

    def slot(self) -> int:
        reply = self.request(CMD_PEQ_VALUES, bytes((OP_READ, CMD_PEQ_VALUES, 0x00, 0x00, 0x00)), index=0)
        return reply[35] if len(reply) > 35 else CUSTOM_SLOT

    def set_slot(self, slot: int, *, legacy: bool = False) -> bytes:
        del legacy
        frame = bytes((OP_WRITE, CMD_FLASH_EQ, 0x01, slot & 0xFF, 0x00))
        self._write_frame(frame)
        time.sleep(DELAY_OP_MS / 1000.0)
        return frame

    def read_band(self, index: int, *, include_coefficients: bool = False) -> dict | None:
        if not 0 <= index < BAND_COUNT:
            raise ValueError(f"ECHO-A ma 8 pasm (0..7), podano {index}.")
        reply = self.request(CMD_PEQ_VALUES, bytes((OP_READ, CMD_PEQ_VALUES, 0x00, 0x00, index)), index=index)
        if len(reply) < 35:
            return None
        freq, q_raw, gain_raw = struct.unpack("<HHh", reply[27:33])
        ftype_code = reply[33]
        if freq == 0xFFFF and q_raw == 0xFFFF and gain_raw == -1:
            band = {"band": index + 1, "freq": 0, "gain": 0.0, "q": 0.0, "type": "PK"}
        else:
            band = {
                "band": index + 1,
                "freq": int(freq),
                "gain": round(gain_raw / 256.0, 2),
                "q": round(q_raw / 256.0, 2),
                "type": CODE_TO_TYPE.get(ftype_code, "PK"),
            }
        if include_coefficients:
            band["coefficients"] = reply[7:27]
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
        reply = self.request(CMD_GLOBAL_GAIN, bytes((OP_READ, CMD_GLOBAL_GAIN, 0x00)))
        if len(reply) < 5:
            return 0.0
        return float(struct.unpack("<b", reply[4:5])[0])

    def global_gain(self) -> int | None:
        return round(self.preamp())

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
        if not 0 <= index < BAND_COUNT:
            raise ValueError(f"ECHO-A ma 8 pasm (0..7), podano {index}.")
        ftype_code = ftype if isinstance(ftype, int) else TYPE_TO_CODE.get(str(ftype), 2)
        freq_u16 = max(20, min(20000, round(float(freq))))
        q_u16 = max(26, min(2560, round(float(q) * 256.0)))
        gain_i16 = max(-2560, min(2560, round(float(gain) * 256.0)))
        target_slot = CUSTOM_SLOT if slot is None else slot
        coeffs = biquad_coefficients(ftype_code, freq_u16, gain_i16 / 256.0, q_u16 / 256.0)
        payload = (
            bytes((OP_WRITE, CMD_PEQ_VALUES, 0x18, 0x00, index, 0x00, 0x00))
            + coeffs
            + struct.pack("<HHhBB", freq_u16, q_u16, gain_i16, ftype_code, 0x00)
            + bytes((target_slot & 0xFF, 0x00))
        )
        self._write_frame(payload)
        time.sleep(DELAY_BAND_MS / 1000.0)
        return payload

    def latch_band(self, index: int) -> bytes:
        del index
        return b""

    def set_preamp(self, db: float, *, legacy: bool = True) -> bytes:
        del legacy
        clamped = max(-30, min(0, round(float(db))))
        payload = bytes((OP_WRITE, CMD_GLOBAL_GAIN, 0x02, 0x00)) + struct.pack("<b", clamped)
        self._write_frame(payload)
        time.sleep(DELAY_OP_MS / 1000.0)
        return payload

    def save(self) -> bytes:
        self._write_frame(bytes((OP_WRITE, CMD_RESET_STEP, 0x00)))
        time.sleep(DELAY_BAND_MS / 1000.0)
        self._write_frame(bytes((OP_WRITE, CMD_COMMIT_PREP, 0x00)))
        time.sleep(DELAY_BAND_MS / 1000.0)
        self._write_frame(bytes((OP_WRITE, CMD_TEMP_WRITE, 0x04, 0x00, 0x00, 0xFF, 0xFF, 0x00)))
        time.sleep(DELAY_OP_MS / 1000.0)
        commit_frame = bytes((OP_WRITE, CMD_FLASH_EQ, 0x01, 0x00))
        self._write_frame(commit_frame)
        time.sleep(DELAY_FLASH_MS / 1000.0)
        return commit_frame

    def _expected_band(self, index: int, band: dict) -> dict:
        ftype_code = TYPE_TO_CODE.get(band["type"], 2)
        freq = max(20, min(20000, round(float(band["freq"]))))
        q_raw = max(26, min(2560, round(float(band["q"]) * 256.0)))
        gain_raw = max(-2560, min(2560, round(float(band["gain"]) * 256.0)))
        return {
            "band": index + 1,
            "freq": freq,
            "gain": round(gain_raw / 256.0, 2),
            "q": round(q_raw / 256.0, 2),
            "type": CODE_TO_TYPE.get(ftype_code, "PK"),
        }

    def verify_profile(self, bands: list[dict], slot: int | None = None, preamp: float | None = None) -> None:
        del slot
        for index, band in enumerate(bands):
            expected = self._expected_band(index, band)
            actual = self.read_band(index)
            if actual != expected:
                raise HidError(f"ECHO-A pasmo {index + 1}: odczytano {actual}, oczekiwano {expected}.")
            time.sleep(DELAY_BAND_MS / 1000.0)
        if preamp is not None:
            expected_preamp = float(max(-30, min(0, round(float(preamp)))))
            actual_preamp = self.preamp()
            if actual_preamp != expected_preamp:
                raise HidError(f"ECHO-A pre-gain: odczytano {actual_preamp}, oczekiwano {expected_preamp}.")

    def apply_preamp(self, db: float) -> bool:
        clamped = float(max(-30, min(0, round(float(db)))))
        initial = self.preamp()
        if initial == clamped:
            return False
        self.set_preamp(clamped)
        return self.preamp() != initial

    def write_profile(
        self,
        bands: list[dict],
        preamp: float | None = None,
        *,
        slot: int | None = None,
        persist: bool = True,
        previous_bands: list[dict] | None = None,
    ) -> float | None:
        if not 1 <= len(bands) <= BAND_COUNT:
            raise HidError(f"ECHO-A obsługuje od 1 do {BAND_COUNT} pasm.")
        for band in bands:
            if (
                band["type"] not in TYPE_TO_CODE
                or not 20 <= band["freq"] <= 20000
                or not 0.1 <= band["q"] <= 10.0
                or not -10.0 <= band["gain"] <= 10.0
            ):
                raise HidError(f"Nieprawidłowe parametry pasma {band.get('band', '?')} dla ECHO-A.")
        target_slot = CUSTOM_SLOT if slot is None else slot
        for index, band in enumerate(bands):
            if (
                previous_bands is not None
                and index < len(previous_bands)
                and self._expected_band(index, band) == self._expected_band(index, previous_bands[index])
            ):
                continue
            self.write_band(index, band["type"], band["freq"], band["gain"], band["q"], slot=target_slot)
        applied_preamp = None
        if preamp is not None:
            applied_preamp = float(max(-30, min(0, round(float(preamp)))))
            self.set_preamp(applied_preamp)
        self.verify_profile(bands, target_slot, applied_preamp)
        if persist:
            self.save()
            self.verify_profile(bands, target_slot, applied_preamp)
        return applied_preamp


ECHO_A_MODEL = DacModel(
    model_id="moondrop-echo-a",
    display_name=MODEL_NAME,
    usb_id=(VENDOR_ID, PRODUCT_ID),
    reports=frozenset(HidReport(REPORT_ID, kind, PAYLOAD_LEN) for kind in ("input", "output")),
    connect=EchoA,
)
