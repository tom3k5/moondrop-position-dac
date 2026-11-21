"""Wczytywanie pomiarów REW i squig.link."""

from pathlib import Path


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
