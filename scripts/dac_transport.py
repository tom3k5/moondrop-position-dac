"""Linux USB HID discovery and raw report transport."""

from __future__ import annotations

import errno
import fcntl
import os
import select
from dataclasses import dataclass
from pathlib import Path


class HidError(RuntimeError):
    pass


class HidPermissionError(HidError):
    pass


class HidDeviceMissing(HidError):
    pass


class HidDeviceChanged(HidError):
    pass


@dataclass(frozen=True)
class HidReport:
    report_id: int
    kind: str
    length: int  # bytes excluding the report ID


def parse_reports(descriptor: bytes) -> frozenset[HidReport]:
    """Read the input, output and feature report lengths from the HID items."""
    main_items = {0x80: "input", 0x90: "output", 0xB0: "feature"}
    report_id = report_size = report_count = 0
    stack: list[tuple[int, int, int]] = []
    bits: dict[tuple[int, str], int] = {}
    offset = 0
    while offset < len(descriptor):
        prefix = descriptor[offset]
        offset += 1
        if prefix == 0xFE:
            if offset + 2 > len(descriptor):
                return frozenset()
            offset += 2 + descriptor[offset]
            if offset > len(descriptor):
                return frozenset()
            continue
        size = (0, 1, 2, 4)[prefix & 3]
        end = offset + size
        if end > len(descriptor):
            return frozenset()
        value = int.from_bytes(descriptor[offset:end], "little")
        offset = end
        tag = prefix & 0xFC
        if tag == 0x74:
            report_size = value
        elif tag == 0x84:
            if not 1 <= value <= 255:
                return frozenset()
            report_id = value
        elif tag == 0x94:
            report_count = value
        elif tag == 0xA4:
            stack.append((report_id, report_size, report_count))
        elif tag == 0xB4:
            if not stack:
                return frozenset()
            report_id, report_size, report_count = stack.pop()
        elif tag in main_items:
            key = (report_id, main_items[tag])
            bits[key] = bits.get(key, 0) + report_size * report_count
    return frozenset(HidReport(report_id, kind, (length + 7) // 8) for (report_id, kind), length in bits.items())


@dataclass(frozen=True)
class HidInterface:
    node: str
    sysfs: Path
    instance: Path
    name: str
    vendor_id: int
    product_id: int
    reports: frozenset[HidReport]

    def is_current(self) -> bool:
        try:
            return self.sysfs.resolve(strict=True) == self.instance
        except OSError:
            return False


def scan_hidraw(sysfs: Path = Path("/sys/class/hidraw"), dev: Path = Path("/dev")) -> list[HidInterface]:
    """Enumerate USB HID interfaces without opening their device nodes."""
    interfaces = []
    for entry in sorted(sysfs.glob("hidraw*")):
        try:
            instance = entry.resolve(strict=True)
            device = instance / "device"
            properties = dict(
                line.split("=", 1) for line in (device / "uevent").read_text().splitlines() if "=" in line
            )
            bus, vendor, product = (int(part, 16) for part in properties.get("HID_ID", "").split(":"))
            if bus != 3:  # BUS_USB
                continue
        except (OSError, ValueError):
            continue
        try:
            reports = parse_reports((device / "report_descriptor").read_bytes())
        except OSError:
            reports = frozenset()
        interface = HidInterface(
            str(dev / entry.name), entry, instance, properties.get("HID_NAME", ""), vendor, product, reports
        )
        if interface.is_current():
            interfaces.append(interface)
    return interfaces


class HidrawTransport:
    def __init__(self, interface: HidInterface):
        self.interface = interface
        if not interface.is_current():
            raise HidDeviceChanged("Urządzenie USB zmieniło się. Odczytaj jego stan ponownie.")
        try:
            self._fd = os.open(interface.node, os.O_RDWR | os.O_NONBLOCK)
        except PermissionError as exc:
            raise HidPermissionError(f"Brak dostępu do {interface.node}. Sprawdź regułę udev na hoście.") from exc
        except FileNotFoundError as exc:
            raise HidDeviceMissing(f"Węzeł {interface.node} jest niedostępny.") from exc
        except OSError as exc:
            raise HidError(f"Nie można otworzyć {interface.node}: {exc.strerror}.") from exc
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if not interface.is_current():
                raise HidDeviceChanged("Urządzenie USB zmieniło się. Odczytaj jego stan ponownie.")
        except BlockingIOError as exc:
            self.close()
            raise HidError("DAC jest zajęty przez inną operację aplikacji.") from exc
        except OSError as exc:
            self.close()
            raise HidError(f"Nie można zablokować interfejsu {interface.node}: {exc.strerror}.") from exc
        except HidError:
            self.close()
            raise

    def close(self) -> None:
        if self._fd is not None:
            fd, self._fd = self._fd, None
            os.close(fd)

    def _descriptor(self) -> int:
        if self._fd is None:
            raise HidDeviceMissing("Połączenie z DAC-em zostało zamknięte.")
        return self._fd

    def write(self, report: bytes) -> None:
        try:
            if os.write(self._descriptor(), report) != len(report):
                raise HidError("Niepełny zapis raportu HID.")
        except OSError as exc:
            raise self._io_error(exc) from exc

    def read(self, size: int, timeout: float | None = None) -> bytes | None:
        fd = self._descriptor()
        try:
            if timeout is not None and not select.select([fd], [], [], timeout)[0]:
                return None
            data = os.read(fd, size)
        except BlockingIOError:
            return None
        except OSError as exc:
            raise self._io_error(exc) from exc
        if not data:
            raise HidDeviceMissing("DAC został odłączony podczas operacji HID.")
        return data

    @staticmethod
    def _io_error(exc: OSError) -> HidError:
        if exc.errno in (errno.ENODEV, errno.ENXIO, errno.ESHUTDOWN):
            return HidDeviceMissing("DAC został odłączony podczas operacji HID.")
        return HidError(f"Błąd komunikacji HID: {exc.strerror}.")
