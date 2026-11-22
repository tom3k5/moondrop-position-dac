#!/usr/bin/env python3
"""Narzędzie do sprawdzania jakości kodu, standardu składni i testów projektu."""

from __future__ import annotations

import argparse
import json
import py_compile
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON_DIRS = ["skrypty", "tests"]


def run_step(title: str, command: list[str]) -> bool:
    """Uruchamia pojedynczy etap kontroli i zwraca True przy sukcesie."""
    print(f"\n==> {title}")
    print(f"    $ {' '.join(command)}")
    result = subprocess.run(command, cwd=ROOT, check=False)
    if result.returncode != 0:
        print(f"[BŁĄD] {title} (kod {result.returncode})")
        return False
    print(f"[OK] {title}")
    return True


def check_python_syntax() -> bool:
    """Kompiluje wszystkie pliki Pythona w skrypty/ i tests/ w celu weryfikacji składni."""
    print("\n==> Składnia Pythona (py_compile)")
    files = sorted(
        path for directory in PYTHON_DIRS if (ROOT / directory).is_dir() for path in (ROOT / directory).rglob("*.py")
    )
    if not files:
        print("[OK] Brak plików Pythona do sprawdzenia.")
        return True
    ok = True
    for path in files:
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            print(f"[BŁĄD] {path.relative_to(ROOT)}: {exc.msg}")
            ok = False
    if ok:
        print(f"[OK] Sprawdzono składnię {len(files)} plików Pythona.")
    return ok


def check_data_configs() -> bool:
    """Waliduje składnię plików JSON oraz XML używanych przez aplikację i Flatpaka."""
    print("\n==> Walidacja JSON i XML")
    json_files = [
        ROOT / "local.moondrop.Position.json",
        ROOT / "dane" / "przyklad-eq.json",
        *sorted((ROOT / "dane" / "profile").glob("*.json")),
        *sorted((ROOT / "dane" / "i18n").glob("*.json")),
    ]
    xml_files = [
        ROOT / "flatpak" / "local.moondrop.Position.metainfo.xml",
        ROOT / "flatpak" / "local.moondrop.Position.svg",
    ]
    ok = True
    checked = 0
    for path in json_files:
        if not path.exists():
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
            checked += 1
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            print(f"[BŁĄD] JSON {path.relative_to(ROOT)}: {exc}")
            ok = False
    for path in xml_files:
        if not path.exists():
            continue
        try:
            ET.parse(path)
            checked += 1
        except (OSError, ET.ParseError) as exc:
            print(f"[BŁĄD] XML {path.relative_to(ROOT)}: {exc}")
            ok = False
    if ok:
        print(f"[OK] Zwalidowano {checked} plików JSON/XML.")
    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Kontrola jakości kodu, składni i testów projektu.")
    parser.add_argument("--fix", action="store_true", help="automatycznie napraw proste błędy lintera i formatowania")
    parser.add_argument("--lint-only", action="store_true", help="pomiń uruchamianie pytest")
    parser.add_argument("--tests-only", action="store_true", help="uruchom wyłącznie pytest")
    args = parser.parse_args(argv)

    results: list[bool] = []
    targets = [directory for directory in PYTHON_DIRS if (ROOT / directory).is_dir()]

    if not args.tests_only:
        results.append(check_python_syntax())
        results.append(check_data_configs())

        ruff = shutil.which("ruff")
        if ruff is None:
            print("\n[BŁĄD] Nie znaleziono narzędzia 'ruff' w PATH.")
            results.append(False)
        else:
            lint_cmd = [ruff, "check", *(["--fix"] if args.fix else []), *targets]
            fmt_cmd = [ruff, "format", *([] if args.fix else ["--check"]), *targets]
            results.append(run_step("Ruff lint (standard kodu i importów)", lint_cmd))
            results.append(run_step("Ruff format (spójność formatowania)", fmt_cmd))

    if not args.lint_only:
        pytest_bin = shutil.which("pytest")
        pytest_cmd = [pytest_bin] if pytest_bin else [sys.executable, "-m", "pytest"]
        results.append(run_step("Pytest (testy jednostkowe i smoke GUI)", pytest_cmd))

    passed = all(results)
    summary = "Wszystkie kontrole zakończone sukcesem." if passed else "Co najmniej jedna kontrola nie powiodła się."
    print(f"\n{summary}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
