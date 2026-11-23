"""Model registry and session selection shared by the GUI and CLI."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

from dac_transport import HidDeviceChanged, HidError, HidInterface, HidrawTransport, HidReport, scan_hidraw

Driver = TypeVar("Driver")
DeviceTarget = HidInterface | str


class AmbiguousDac(HidError):
    pass


@dataclass(frozen=True)
class DacModel(Generic[Driver]):
    model_id: str
    display_name: str
    usb_id: tuple[int, int]
    reports: frozenset[HidReport]
    connect: Callable[[HidrawTransport, int], Driver]

    def matches(self, interface: HidInterface) -> bool:
        return (interface.vendor_id, interface.product_id) == self.usb_id and self.reports <= interface.reports


@dataclass(frozen=True)
class DetectedDac(Generic[Driver]):
    model: DacModel[Driver]
    interface: HidInterface


class DacRegistry(Generic[Driver]):
    def __init__(self, models: tuple[DacModel[Driver], ...], scan: Callable[[], list[HidInterface]] = scan_hidraw):
        self.models = models
        self.scan = scan

    def detect(self) -> list[DetectedDac[Driver]]:
        detected = []
        for interface in self.scan():
            matches = [model for model in self.models if model.matches(interface)]
            if len(matches) == 1:
                detected.append(DetectedDac(matches[0], interface))
        return detected

    def select(self, target: DeviceTarget | None = None) -> DetectedDac[Driver] | None:
        devices = self.detect()
        if isinstance(target, HidInterface):
            devices = [device for device in devices if device.interface == target]
            if not devices:
                raise HidDeviceChanged("DAC został odłączony lub zmienił się jego interfejs. Odczytaj stan ponownie.")
        elif target is not None:
            path = str(Path(target).resolve())
            devices = [device for device in devices if device.interface.node == path]
            if not devices:
                raise HidDeviceChanged(f"{target} nie wskazuje obsługiwanego interfejsu DSP.")
        if len(devices) > 1:
            raise AmbiguousDac("Wykryto kilka DAC-ów. Wskaż docelowe urządzenie.")
        return devices[0] if devices else None

    def open(self, selected: DetectedDac[Driver], timeout_ms: int) -> Driver:
        transport = HidrawTransport(selected.interface)
        try:
            return selected.model.connect(transport, timeout_ms)
        except BaseException:
            transport.close()
            raise
