#!/usr/bin/env python3
"""eq_fit.py — AutoEq → MOONDROP Position: dopasowanie EQ do targetu i zapis do DSP.

Łączy:
  * bazę pomiarów (squig.link, CSV AutoEq) i targety (AutoEq, squig.link),
  * bibliotekę AutoEq (optymalizator EQ parametrycznego),
  * protokół HID 0x4B (moduł moondrop_position.py) — zapis do urządzenia.

Uruchamianie bez ręcznej aktywacji venv: skrypt sam przełączy się na
.venvs/autoeq/bin/python, jeśli AutoEq nie jest widoczny w bieżącym Pythonie.

Przykłady:
  # sam profil (bez urządzenia)
  skrypty/eq_fit.py -m "dane/pomiary/Moondrop Position (B&K 5128).csv" \
                    -t "dane/targety/Harman in-ear 2019.csv" \
                    -o dane/profil-harman.json --plot dane/profil-harman.png

  # profil + zapis do DAC-a (wymaga reguły udev)
  skrypty/eq_fit.py -m ... -t ... -o dane/profil-harman.json --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(HERE))

# Matplotlib i AutoEq piszą cache do katalogu domowego — w sandboxie bywa
# niezapisywalny, więc używamy zapisywalnego katalogu projektu lub XDG_CACHE_HOME.
from measurements import read_squig_txt as read_rew  # noqa: E402

_cache_base = (
    PROJECT / ".cache"
    if os.access(PROJECT, os.W_OK)
    else Path(os.environ.get("XDG_CACHE_HOME") or tempfile.gettempdir()) / "moondrop-position"
)
os.environ.setdefault("MPLCONFIGDIR", str(_cache_base / "matplotlib"))

DEVICE_FS = 96000  # DSP urządzenia liczy biquady przy stałych 96 kHz
DEVICE_SLOT_CUSTOM = 7


# --------------------------------------------------------------------------
# Auto-reexec w venv z AutoEq
# --------------------------------------------------------------------------


def _ensure_autoeq() -> None:
    try:
        import autoeq  # noqa: F401

        return
    except ImportError as exc:
        venv_python = PROJECT / ".venvs" / "autoeq" / "bin" / "python"
        if venv_python.exists() and Path(sys.executable) != venv_python:
            os.execv(str(venv_python), [str(venv_python), *sys.argv])
        raise SystemExit(
            "Brak biblioteki AutoEq. Utwórz venv w projekcie:\n"
            "  uv venv --python 3.11 .venvs/autoeq\n"
            "  uv pip install --python .venvs/autoeq/bin/python autoeq\n"
            "albo uruchom przez: .venvs/autoeq/bin/python skrypty/eq_fit.py ..."
        ) from exc


# --------------------------------------------------------------------------
# Wczytywanie pomiarów i targetów
# --------------------------------------------------------------------------


def read_squig_txt(path: Path) -> tuple[list[float], list[float]]:
    try:
        return read_rew(path)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def load_curve(path: Path):
    """Zwraca (freq, spl). Dla .csv najpierw próbuje formatu AutoEq."""
    if path.suffix.lower() == ".csv":
        try:
            from autoeq.frequency_response import FrequencyResponse

            fr = FrequencyResponse.read_csv(str(path))
            return list(fr.frequency), list(fr.raw)
        except Exception:
            pass  # np. CSV z REW — spróbuj uniwersalnie
    return read_squig_txt(path)


def load_measurement(left: Path, right: Path | None) -> tuple[list[float], list[float], str]:
    import numpy as np

    fl, sl = load_curve(left)
    if right is None:
        # "Nazwa L.txt" -> spróbuj automatycznie "Nazwa R.txt"
        name = left.name
        if " L." in name:
            guess = left.with_name(name.replace(" L.", " R."))
            if guess.exists():
                right = guess
    if right is not None:
        fr_, sr = load_curve(right)
        freq_l = np.asarray(fl, dtype=float)
        spl_l = np.asarray(sl, dtype=float)
        freq_r = np.asarray(fr_, dtype=float)
        spl_r = np.asarray(sr, dtype=float)
        if len(freq_r) != len(freq_l) or not np.allclose(freq_r, freq_l, atol=0.01):
            # różne siatki — interpolacja R na siatkę L w skali logarytmicznej
            spl_r = np.interp(np.log(freq_l), np.log(freq_r), spl_r)
        raw = (spl_l + spl_r) / 2.0
        return freq_l.tolist(), raw.tolist(), f"{left.name} + {right.name} (średnia L/R)"
    return fl, sl, left.name


# --------------------------------------------------------------------------
# Dopasowanie
# --------------------------------------------------------------------------


def build_peq_config(
    bands: int,
    min_fc: float,
    max_fc: float,
    min_q: float,
    max_q: float,
    min_gain: float,
    max_gain: float,
    min_std: float,
    max_time: float | None,
) -> dict:
    """Konfiguracja optymalizatora dopasowana do limitów MOONDROP Position.

    Urządzenie (wg oficjalnej apki) ma 8 pasm PK/LP/HP, 20–20 kHz, Q 0,1–10,
    gain −18…+12 dB. Do korekcji używamy tylko PK (półki wyłączone w apce).
    """
    filt = {
        "type": "PEAKING",
        "min_fc": min_fc,
        "max_fc": max_fc,
        "min_q": min_q,
        "max_q": max_q,
        "min_gain": min_gain,
        "max_gain": max_gain,
    }
    optimizer: dict = {"min_std": min_std}
    if max_time is not None:
        optimizer["max_time"] = max_time
    return {"optimizer": optimizer, "filters": [dict(filt) for _ in range(bands)]}


def fit_eq(measurement_left: Path, measurement_right: Path | None, target_path: Path, args) -> dict:
    import numpy as np
    from autoeq.frequency_response import FrequencyResponse

    freq, raw, source = load_measurement(measurement_left, measurement_right)
    fr = FrequencyResponse(name=measurement_left.stem, frequency=freq, raw=raw)
    fr.interpolate()
    fr.center()

    target_freq, target_spl = load_curve(target_path)
    target = FrequencyResponse(name=target_path.stem, frequency=target_freq, raw=target_spl)

    fr.compensate(
        target,
        bass_boost_gain=args.bass_boost,
        tilt=args.tilt,
        fs=DEVICE_FS,
    )
    fr.smoothen()
    fr.equalize(max_gain=args.eq_max_gain, concha_interference=args.concha)

    config = build_peq_config(
        bands=args.bands,
        min_fc=args.min_fc,
        max_fc=args.max_fc,
        min_q=args.min_q,
        max_q=args.max_q,
        min_gain=args.cut_max,
        max_gain=args.boost_max,
        min_std=args.min_std,
        max_time=args.max_time,
    )
    peqs = fr.optimize_parametric_eq(config, DEVICE_FS)
    peq = peqs[0]
    peq.sort_filters()

    # Przewidywana odpowiedź: error = raw − target, korekcja dodaje się do raw.
    # peq.fr jest na siatce optymalizatora (krok 1.02), więc interpolujemy na
    # siatkę pomiaru (krok 1.01).
    eq_response = np.interp(np.log(fr.frequency), np.log(peq.f), peq.fr)
    residual = fr.error_smoothed + eq_response
    mask = (fr.frequency >= 20) & (fr.frequency <= 20000)
    rms = float(np.sqrt(np.mean(residual[mask] ** 2)))
    max_abs = float(np.max(np.abs(residual[mask])))
    pre_eq_rms = float(np.sqrt(np.mean(fr.error_smoothed[mask] ** 2)))

    preamp = -(peq.max_gain + 0.1)
    preamp = max(-128.0, min(0.0, preamp))

    bands = []
    for i, filt in enumerate(peq.filters):
        bands.append(
            {
                "band": i + 1,
                "freq": round(float(filt.fc), 1),
                "gain": round(float(filt.gain), 3),
                "q": round(float(filt.q), 3),
                "type": "PK",
            }
        )

    profile = {
        "device": "MOONDROP Position",
        "usb": "35d8:0123",
        "slot": args.slot,
        "preamp": round(preamp, 2),
        "bands": bands,
        "meta": {
            "created": datetime.now().isoformat(timespec="seconds"),
            "measurement": source,
            "target": target_path.name,
            "auto_eq_config": {
                "fs": DEVICE_FS,
                "bands": args.bands,
                "boost_max": args.boost_max,
                "cut_max": args.cut_max,
                "eq_max_gain": args.eq_max_gain,
                "bass_boost": args.bass_boost,
                "tilt": args.tilt,
                "concha_interference": args.concha,
            },
            "predicted_error_rms_db": round(rms, 3),
            "predicted_error_max_db": round(max_abs, 3),
            "pre_eq_error_rms_db": round(pre_eq_rms, 3),
        },
    }
    if args.plot:
        _plot(fr, peq, Path(args.plot))
    return profile


def _plot(fr, peq, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    eq_curve = np.interp(np.log(fr.frequency), np.log(peq.f), peq.fr)
    raw = fr.raw - fr.raw.mean() if hasattr(fr.raw, "mean") else fr.raw
    target = fr.target
    equalized = fr.raw + eq_curve
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.semilogx(fr.frequency, raw, label="pomiar (bez EQ)", color="#888")
    ax.semilogx(fr.frequency, target, label="target", ls="--", color="#1f77b4")
    ax.semilogx(fr.frequency, equalized, label="po EQ (predykcja)", color="#d62728")
    ax.set_xlim(20, 20000)
    ax.set_xlabel("Hz")
    ax.set_ylabel("dB")
    ax.grid(True, which="both", alpha=0.25)
    ax.legend()
    ax.set_title(f"{fr.name} → {path.stem}")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


# --------------------------------------------------------------------------
# Zapis do urządzenia
# --------------------------------------------------------------------------


def apply_profile(profile: dict, device_path: str | None) -> None:
    import moondrop_position as mp

    bands = profile["bands"]
    preamp = float(profile.get("preamp", 0.0))
    slot = int(profile.get("slot", DEVICE_SLOT_CUSTOM))

    with mp.MoondropPosition(mp.pick_device(device_path)) as dev:
        print(f"Urządzenie: {dev.path}  firmware={dev.version()}")
        mp.write_profile(dev, bands, preamp, slot)
    print(f"Zapisano profil; odczyt potwierdził {len(bands)} pasm.")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def fmt_profile(profile: dict) -> str:
    lines = [
        (f"Profil: {profile['device']}  slot={profile['slot']}  preamp={profile['preamp']:+.2f} dB"),
        f"  pomiar: {profile['meta']['measurement']}",
        f"  target: {profile['meta']['target']}",
        (
            f"  błąd RMS: {profile['meta']['pre_eq_error_rms_db']:.2f} dB (przed) → "
            f"{profile['meta']['predicted_error_rms_db']:.2f} dB (po EQ), "
            f"max {profile['meta']['predicted_error_max_db']:.2f} dB"
        ),
    ]
    for band in profile["bands"]:
        lines.append(
            f"  {band['band']:>2}. {band['type']:<3} "
            f"f={band['freq']:>7.1f} Hz  gain={band['gain']:>+6.2f} dB  "
            f"Q={band['q']:>6.3f}"
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dopasuj EQ (AutoEq) do pomiaru i targetu, zapisz profil MOONDROP Position (opcjonalnie do DSP).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Przykład:\n"
        "  skrypty/eq_fit.py -m 'dane/pomiary/Moondrop Position (B&K 5128).csv' \\\n"
        "                    -t 'dane/targety/Harman in-ear 2019.csv' \\\n"
        "                    -o dane/profil-harman.json --plot dane/profil-harman.png --apply\n",
    )
    parser.add_argument(
        "-m", "--measurement", required=True, metavar="PLIK", help="pomiar L (squig .txt lub CSV AutoEq)"
    )
    parser.add_argument(
        "-r", "--right", metavar="PLIK", help="pomiar R (domyślnie szukane automatycznie po nazwie ' L.')"
    )
    parser.add_argument("-t", "--target", required=True, metavar="PLIK", help="target (CSV AutoEq lub .txt squig)")
    parser.add_argument("-o", "--out", required=True, metavar="JSON", help="wyjściowy profil JSON (format write-eq)")
    parser.add_argument("--plot", metavar="PNG", help="zapisz wykres dopasowania")
    parser.add_argument("--apply", action="store_true", help="zapisz profil do urządzenia przez HID (wymaga udev)")
    parser.add_argument("--device", metavar="PATH", help="/dev/hidrawN")
    parser.add_argument("--bands", type=int, default=8, help="liczba pasm (domyślnie 8)")
    parser.add_argument("--slot", type=int, default=DEVICE_SLOT_CUSTOM, help="slot EQ (domyślnie 7 = Custom)")
    parser.add_argument("--boost-max", type=float, default=6.0, help="maks. wzmocnienie pasma w dB (domyślnie +6)")
    parser.add_argument("--cut-max", type=float, default=-12.0, help="maks. tłumienie pasma w dB (domyślnie −12)")
    parser.add_argument("--min-fc", type=float, default=20.0)
    parser.add_argument("--max-fc", type=float, default=20000.0)
    parser.add_argument("--min-q", type=float, default=0.1)
    parser.add_argument("--max-q", type=float, default=10.0)
    parser.add_argument("--eq-max-gain", type=float, default=6.0, help="limit wzmocnienia krzywej EQ (AutoEq equalize)")
    parser.add_argument("--bass-boost", type=float, default=0.0, help="dodatkowy bass boost targetu [dB]")
    parser.add_argument("--tilt", type=float, default=0.0, help="przechył targetu [dB/oct] (ujemny = ciemniej)")
    parser.add_argument("--concha", action="store_true", help="pomiar zawiera rezonans małżowiny (~9 kHz)")
    parser.add_argument("--min-std", type=float, default=0.008, help="parametr zbieżności optymalizatora")
    parser.add_argument("--max-time", type=float, default=None, help="limit czasu optymalizacji [s]")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _ensure_autoeq()

    measurement = Path(args.measurement)
    target = Path(args.target)
    for path in (measurement, target):
        if not path.exists():
            raise SystemExit(f"Nie ma pliku: {path}")

    profile = fit_eq(measurement, Path(args.right) if args.right else None, target, args)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(profile, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print(fmt_profile(profile))
    print(f"\nZapisano profil: {out}")
    if args.plot:
        print(f"Wykres: {args.plot}")
    if args.apply:
        apply_profile(profile, args.device)
    else:
        print(f"\nAby zapisać do DAC-a: moondrop_position.py write-eq --file {out} --yes  (albo dodaj --apply)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
