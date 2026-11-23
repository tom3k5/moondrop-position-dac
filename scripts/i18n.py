"""Moduł internacjonalizacji (i18n) oparty na katalogach JSON w data/i18n/."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

I18N_DIR = Path(__file__).resolve().parents[1] / "data" / "i18n"
DEFAULT_LANGUAGE = "pl"
FALLBACK_LANGUAGE = "en"

_active_language = DEFAULT_LANGUAGE


def available_languages(directory: Path | None = None) -> list[tuple[str, str]]:
    """Zwraca listę dostępnych języków jako pary (kod, nazwa własna)."""
    root = directory or I18N_DIR
    found: dict[str, str] = {}
    if root.is_dir():
        for path in sorted(root.glob("*.json")):
            code = path.stem.casefold()
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            meta = data.get("_meta", {}) if isinstance(data, dict) else {}
            name = str(meta.get("name") or code.upper())
            found[code] = name
    ordered: list[tuple[str, str]] = []
    for preferred in ("pl", "en"):
        if preferred in found:
            ordered.append((preferred, found.pop(preferred)))
    for code in sorted(found):
        ordered.append((code, found[code]))
    return ordered or [(DEFAULT_LANGUAGE, "Polski")]


@lru_cache(maxsize=16)
def load_catalog(code: str, directory: Path | None = None) -> dict[str, str]:
    """Wczytuje słownik tłumaczeń dla podanego kodu języka."""
    root = directory or I18N_DIR
    path = root / f"{code.casefold()}.json"
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: str(v) for k, v in raw.items() if k != "_meta" and isinstance(v, str)}


def detect_system_language(locale_name: str | None = None, directory: Path | None = None) -> str:
    """Dobiera język na podstawie ustawień systemu (fallback: en, potem pl)."""
    codes = {code for code, _name in available_languages(directory)}
    raw = locale_name or os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or ""
    short = raw.split(".", 1)[0].split("_", 1)[0].split("-", 1)[0].casefold()
    if short in codes:
        return short
    if FALLBACK_LANGUAGE in codes:
        return FALLBACK_LANGUAGE
    if DEFAULT_LANGUAGE in codes:
        return DEFAULT_LANGUAGE
    return next(iter(codes), DEFAULT_LANGUAGE)


def set_language(code: str, *, locale_name: str | None = None, directory: Path | None = None) -> str:
    """Ustawia aktywny język aplikacji ('auto' wykrywa język systemowy)."""
    global _active_language
    resolved = detect_system_language(locale_name, directory) if code == "auto" else code.casefold()
    codes = {item_code for item_code, _name in available_languages(directory)}
    if resolved not in codes:
        resolved = detect_system_language(locale_name, directory)
    _active_language = resolved
    return _active_language


def current_language() -> str:
    """Zwraca kod aktualnie aktywnego języka."""
    return _active_language


def tr(key: str, **kwargs) -> str:
    """Tłumaczy klucz na aktywny język z bezpiecznym fallbackiem i formatowaniem."""
    text = (
        load_catalog(_active_language).get(key)
        or load_catalog(FALLBACK_LANGUAGE).get(key)
        or load_catalog(DEFAULT_LANGUAGE).get(key)
        or key
    )
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError):
            return text
    return text


def load_language_preference(config_path: Path) -> str:
    """Odczytuje zapisany wybór języka ('auto' lub kod języka)."""
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        value = str(data.get("language", "auto")).casefold()
        return value or "auto"
    except (OSError, json.JSONDecodeError, AttributeError):
        return "auto"


def save_language_preference(config_path: Path, code: str) -> None:
    """Zapisuje wybrany język do pliku konfiguracji JSON."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    try:
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            existing = loaded
    except (OSError, json.JSONDecodeError):
        existing = {}
    existing["language"] = code
    config_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
