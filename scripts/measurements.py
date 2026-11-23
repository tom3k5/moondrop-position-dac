"""Wczytywanie pomiarów REW i squig.link."""

import math
from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

Curve = Sequence[tuple[float, float]]
FIT_LOW_HZ = 20
FIT_HIGH_HZ = 10000


def curve_level(curve: Curve, hz: float) -> float:
    """Interpolate a sorted curve in log frequency."""
    index = bisect_left(curve, (hz, -math.inf))
    if index == 0:
        return curve[0][1]
    if index == len(curve):
        return curve[-1][1]
    low_hz, low_db = curve[index - 1]
    high_hz, high_db = curve[index]
    weight = math.log(hz / low_hz) / math.log(high_hz / low_hz)
    return low_db + weight * (high_db - low_db)


@dataclass(frozen=True)
class TargetFit:
    low_hz: float
    high_hz: float
    offset_db: float
    rms_db: float
    peak_hz: float
    peak_db: float


def fit_to_target(response: Curve, target: Curve) -> TargetFit | None:
    if not response or not target:
        return None
    low = max(FIT_LOW_HZ, response[0][0], target[0][0])
    high = min(FIT_HIGH_HZ, response[-1][0], target[-1][0])
    if low >= high:
        return None
    # Equal weights on a logarithmic grid of at least 96 steps per octave.
    steps = math.ceil(96 * math.log2(high / low))
    frequencies = [low * (high / low) ** (i / steps) for i in range(steps)] + [high]
    errors = [curve_level(response, hz) - curve_level(target, hz) for hz in frequencies]
    offset = math.fsum(errors) / len(errors)
    residuals = [error - offset for error in errors]
    peak = max(range(len(frequencies)), key=lambda i: abs(residuals[i]))
    rms = math.sqrt(math.fsum(db**2 for db in residuals) / len(residuals))
    return TargetFit(low, high, offset, rms, frequencies[peak], residuals[peak])


def read_squig_txt(path: Path) -> tuple[list[float], list[float]]:
    """Format squig.link / REW: linie '*' to komentarze, dalej freq<TAB>SPL[<TAB>phase]."""
    freq: list[float] = []
    spl: list[float] = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith(("*", "#")):
                continue
            parts = line.replace(",", "\t").split("\t")
            if len(parts) < 2:
                parts = line.split()
            if len(parts) < 2:
                continue
            try:
                f = float(parts[0])
                s = float(parts[1])
            except ValueError:
                continue
            freq.append(f)
            spl.append(s)
    if not freq:
        raise ValueError(f"Nie udało się wczytać danych z {path}")
    return freq, spl
