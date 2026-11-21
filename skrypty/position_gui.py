#!/usr/bin/env python3
"""Aplikacja MOONDROP Position na Linux i tryb demonstracyjny bez USB."""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import platform
import re
import shutil
import struct
import subprocess
import sys
import time
import webbrowser
from bisect import bisect_left
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote, urlencode
from uuid import uuid4

from PySide6.QtCore import (
    QAbstractListModel,
    QIODevice,
    QLocale,
    QModelIndex,
    QObject,
    QPointF,
    QProcess,
    QRunnable,
    QSaveFile,
    QStandardPaths,
    Qt,
    QThreadPool,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QIcon,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QRadialGradient,
    QShortcut,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStyle,
    QSystemTrayIcon,
    QTabWidget,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import autoeq_catalog as catalog
import i18n
import moondrop_position as dac
from i18n import tr
from measurements import read_squig_txt

DATA_DIR = Path(__file__).resolve().parents[1] / "dane"
BUILTIN_PROFILE = DATA_DIR / "profile/moondrop-position-harman.json"
HARMAN_TARGET = DATA_DIR / "targety/Harman in-ear 2019.csv"
GITHUB_REPO_URL = "https://github.com/tom3k5/moondrop-position-dac"
OFFICIAL_HUB_URL = "https://hub.moondroplab.tech/"
PROFILE_ROLE = Qt.ItemDataRole.UserRole
PATH_ROLE = Qt.ItemDataRole.UserRole + 1
PRIMARY_ACTION_STYLE = (
    "QPushButton:enabled { background: palette(highlight); color: palette(highlighted-text);"
    " border: 1px solid palette(highlight); border-radius: 6px; padding: 6px 14px; font-weight: 600; }"
    "QPushButton:focus { border: 1px solid palette(text); }"
)
APP_STYLE = """
QGroupBox {
    border: 1px solid palette(mid);
    border-radius: 8px;
    margin-top: 10px;
    padding: 14px 12px 10px 12px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}
QPushButton {
    border: 1px solid palette(mid);
    border-radius: 6px;
    padding: 5px 12px;
    background: palette(button);
}
QToolButton {
    border: 1px solid palette(mid);
    border-radius: 6px;
    padding: 5px 10px;
    background: palette(button);
}
QToolButton[popupMode="1"] {
    padding-right: 24px;
}
QToolButton[popupMode="2"] {
    padding-right: 22px;
}
QToolButton::menu-button {
    border-left: 1px solid palette(mid);
    width: 18px;
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
}
QToolButton::menu-indicator {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    right: 6px;
}
QPushButton:hover:enabled, QToolButton:hover:enabled {
    border-color: palette(highlight);
}
QPushButton:disabled, QToolButton:disabled {
    color: palette(placeholder-text);
    border-color: palette(mid);
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    border: 1px solid palette(mid);
    border-radius: 6px;
    padding: 2px 8px;
    min-height: 24px;
    background: palette(base);
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: palette(highlight);
}
QListWidget, QListView {
    border: 1px solid palette(mid);
    border-radius: 8px;
    padding: 4px;
    background: palette(base);
}
QListWidget::item, QListView::item {
    border-radius: 4px;
    padding: 5px 8px;
}
QListWidget::item:selected, QListView::item:selected {
    background: palette(highlight);
    color: palette(highlighted-text);
}
QTabWidget::pane {
    border-top: 1px solid palette(mid);
    margin-top: -1px;
}
QTabBar::tab {
    padding: 7px 16px;
    margin-right: 4px;
    border: 1px solid transparent;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}
QTabBar::tab:selected {
    border-color: palette(mid);
    border-bottom-color: palette(window);
    background: palette(window);
    font-weight: 600;
}
QToolTip {
    border: 1px solid palette(mid);
    border-radius: 6px;
    padding: 6px 9px;
    background: palette(tool-tip-base);
    color: palette(tool-tip-text);
}
"""
SEGMENT_BUTTON_STYLE = (
    "QPushButton { border: 1px solid palette(mid); padding: 5px 10px; background: palette(window); }"
    "QPushButton:checked { border-color: palette(highlight); background: palette(highlight);"
    " color: palette(highlighted-text); font-weight: 600; }"
)
STATUS_PILL_STYLE = "border: 1px solid palette(mid); border-radius: 12px; padding: 4px 12px; background: palette(base);"
FOOTER_BUTTON_STYLE = (
    "QPushButton, QToolButton { border: 1px solid transparent; border-radius: 6px;"
    " padding: 3px 8px; background: transparent; }"
    'QToolButton[popupMode="2"] { padding-right: 20px; }'
    "QPushButton:hover, QToolButton:hover { border-color: palette(highlight); background: palette(base); }"
)


def build_innovibe_palette(dark: bool) -> QPalette:
    """Tworzy paletę Qt dla motywu ciemnego lub jasnego na bazie kolorów innovibe.pl."""
    palette = QPalette()
    if dark:
        colors = {
            QPalette.ColorRole.Window: "#161210",
            QPalette.ColorRole.WindowText: "#fafaf9",
            QPalette.ColorRole.Base: "#1c1714",
            QPalette.ColorRole.AlternateBase: "#221c18",
            QPalette.ColorRole.ToolTipBase: "#221c18",
            QPalette.ColorRole.ToolTipText: "#fafaf9",
            QPalette.ColorRole.Text: "#fafaf9",
            QPalette.ColorRole.Button: "#241d18",
            QPalette.ColorRole.ButtonText: "#fafaf9",
            QPalette.ColorRole.BrightText: "#ffd08a",
            QPalette.ColorRole.PlaceholderText: "#948a80",
            QPalette.ColorRole.Light: "#332922",
            QPalette.ColorRole.Midlight: "#29211b",
            QPalette.ColorRole.Mid: "#3e332a",
            QPalette.ColorRole.Dark: "#120f0d",
            QPalette.ColorRole.Shadow: "#000000",
            QPalette.ColorRole.Highlight: "#ff8a1f",
            QPalette.ColorRole.HighlightedText: "#0c0a09",
            QPalette.ColorRole.Link: "#ffb347",
            QPalette.ColorRole.LinkVisited: "#ffd08a",
        }
        disabled_text = "#8a8076"
    else:
        colors = {
            QPalette.ColorRole.Window: "#faf7f2",
            QPalette.ColorRole.WindowText: "#1c1917",
            QPalette.ColorRole.Base: "#ffffff",
            QPalette.ColorRole.AlternateBase: "#f5efe6",
            QPalette.ColorRole.ToolTipBase: "#1a1613",
            QPalette.ColorRole.ToolTipText: "#fafaf9",
            QPalette.ColorRole.Text: "#1c1917",
            QPalette.ColorRole.Button: "#f3ede4",
            QPalette.ColorRole.ButtonText: "#1c1917",
            QPalette.ColorRole.BrightText: "#ff6a00",
            QPalette.ColorRole.PlaceholderText: "#78716c",
            QPalette.ColorRole.Light: "#ffffff",
            QPalette.ColorRole.Midlight: "#ede5da",
            QPalette.ColorRole.Mid: "#d6cbbe",
            QPalette.ColorRole.Dark: "#a89d91",
            QPalette.ColorRole.Shadow: "#78716c",
            QPalette.ColorRole.Highlight: "#ff6a00",
            QPalette.ColorRole.HighlightedText: "#ffffff",
            QPalette.ColorRole.Link: "#e5470a",
            QPalette.ColorRole.LinkVisited: "#c23b08",
        }
        disabled_text = "#a8a29e"
    for role, hex_color in colors.items():
        palette.setColor(role, QColor(hex_color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(disabled_text))
    return palette


def load_theme_preference(settings_path: Path) -> str:
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        value = data.get("theme", "auto")
        return value if value in ("auto", "dark", "light") else "auto"
    except (OSError, ValueError, TypeError):
        return "auto"


def save_theme_preference(settings_path: Path, theme: str) -> None:
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError, TypeError):
        data = {}
    data["theme"] = theme if theme in ("auto", "dark", "light") else "auto"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def paint_innovibe_backdrop(widget: QWidget) -> None:
    """Maluje subtelne ciepłe poświaty z tła innovibe.pl w trybie ciemnym."""
    if widget.palette().window().color().lightness() >= 128:
        return
    painter = QPainter(widget)
    painter.setPen(Qt.PenStyle.NoPen)
    w, h = widget.width(), widget.height()
    top_right = QRadialGradient(w * 0.9, -h * 0.05, max(w, h) * 0.65)
    top_right.setColorAt(0.0, QColor(255, 106, 0, 28))
    top_right.setColorAt(0.65, QColor(255, 106, 0, 0))
    painter.fillRect(widget.rect(), top_right)
    bottom_left = QRadialGradient(-w * 0.05, h * 0.55, max(w, h) * 0.55)
    bottom_left.setColorAt(0.0, QColor(255, 179, 71, 16))
    bottom_left.setColorAt(0.65, QColor(255, 179, 71, 0))
    painter.fillRect(widget.rect(), bottom_left)


# Firmware 0.5. Klucze to odczytane kody, wartości to sprawdzone żądania.
MIC_GAIN_REQUESTS = {-3072: -3072, -2304: -2304, -1920: -1920, -1536: -1536, -1152: -1024, -384: -512, 0: 0}
UAC2_PLAYBACK_MODES = (
    (1, "S16_LE", "16-bit"),
    (2, "S24_3LE", "24-bit"),
    (3, "S32_LE", "32-bit"),
)
UAC2_SAMPLE_RATES = (44100, 48000, 96000, 192000, 384000)
DEFAULT_EQ_FREQUENCIES = (20, 54, 144, 386, 1036, 2779, 7455, 20000)
DEFAULT_EQ_Q = 182 / 256  # 0.7109375 (~0.711)
# Pasma slotu 0 (Default) odczytane z MOONDROP Position (firmware 0.5).
POSITION_FACTORY_BANDS = (
    {"band": 1, "freq": 2800, "gain": -3.3984375, "q": 1.0, "type": "HSQ"},
    {"band": 2, "freq": 30, "gain": -4.0, "q": 0.30078125, "type": "PK"},
    {"band": 3, "freq": 200, "gain": -2.0, "q": 0.80078125, "type": "PK"},
    {"band": 4, "freq": 1400, "gain": -2.5, "q": 1.0, "type": "PK"},
    {"band": 5, "freq": 6200, "gain": 3.0, "q": 2.0, "type": "PK"},
    {"band": 6, "freq": 9000, "gain": -1.80078125, "q": 3.0, "type": "PK"},
    {"band": 7, "freq": 2000, "gain": 0.0, "q": 0.75, "type": "PK"},
    {"band": 8, "freq": 4000, "gain": 0.0, "q": 0.75, "type": "PK"},
)


def default_custom_bands() -> list[dict]:
    return [
        {"band": index, "type": "PK", "freq": freq, "gain": 0.0, "q": DEFAULT_EQ_Q}
        for index, freq in enumerate(DEFAULT_EQ_FREQUENCIES, 1)
    ]


@dataclass(frozen=True)
class PlaybackQuality:
    altset: int | None
    audio_format: str
    channels: int | None
    rate_hz: int | None
    forced_rate_hz: int | None
    running: bool | None
    pipewire_available: bool
    source: str


def format_rate_khz(rate_hz: int) -> str:
    if rate_hz % 1000 == 0:
        return f"{rate_hz // 1000} kHz"
    return f"{rate_hz / 1000:.1f}".replace(".", ",") + " kHz"


def parse_alsa_stream0(text: str) -> dict:
    """Parsuje sekcję Playback z /proc/asound/card*/stream0 dla MOONDROP Position."""
    altset: int | None = None
    running: bool | None = None
    rate_hz: int | None = None
    alt_formats: dict[int, tuple[str, int | None]] = {}
    in_playback = False
    current_alt: int | None = None
    current_format = ""
    current_channels: int | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("Playback:"):
            in_playback = True
            continue
        if line.startswith("Capture:"):
            if current_alt is not None and current_format:
                alt_formats[current_alt] = (current_format, current_channels)
            break
        if not in_playback:
            continue
        if line.startswith("Status:"):
            running = "Running" in line
        elif line.startswith("Altset ="):
            match = re.search(r"Altset\s*=\s*(\d+)", line)
            if match:
                altset = int(match.group(1))
        elif line.startswith("Momentary freq ="):
            match = re.search(r"Momentary freq\s*=\s*(\d+)\s*Hz", line)
            if match:
                rate_hz = int(match.group(1))
        elif line.startswith("Altset "):
            if current_alt is not None and current_format:
                alt_formats[current_alt] = (current_format, current_channels)
            match = re.search(r"Altset\s+(\d+)", line)
            current_alt = int(match.group(1)) if match else None
            current_format = ""
            current_channels = None
        elif line.startswith("Format:") and current_alt is not None:
            current_format = line.split(":", 1)[1].strip()
        elif line.startswith("Channels:") and current_alt is not None:
            match = re.search(r"Channels:\s*(\d+)", line)
            if match:
                current_channels = int(match.group(1))

    if current_alt is not None and current_format:
        alt_formats[current_alt] = (current_format, current_channels)

    audio_format, channels = alt_formats.get(altset, ("", None)) if altset is not None else ("", None)
    return {
        "altset": altset,
        "audio_format": audio_format,
        "channels": channels,
        "rate_hz": rate_hz,
        "running": running,
    }


def read_pipewire_rates() -> tuple[bool, int | None, int | None]:
    """Odczytuje clock.rate oraz clock.force-rate z pw-metadata -n settings."""
    pw_metadata = shutil.which("pw-metadata")
    if pw_metadata is None:
        return False, None, None
    try:
        result = subprocess.run([pw_metadata, "-n", "settings"], capture_output=True, text=True, timeout=2, check=False)
    except (OSError, subprocess.SubprocessError):
        return False, None, None
    if result.returncode != 0:
        return False, None, None
    clock_rate: int | None = None
    forced_rate: int | None = None
    for line in result.stdout.splitlines():
        if "key:'clock.rate'" in line:
            match = re.search(r"value:'(\d+)'", line)
            if match:
                clock_rate = int(match.group(1))
        elif "key:'clock.force-rate'" in line:
            match = re.search(r"value:'(\d+)'", line)
            if match:
                forced_rate = int(match.group(1))
    return True, clock_rate, forced_rate


def read_playback_quality(*, demo: bool = False, demo_forced_rate: int = 0) -> PlaybackQuality:
    """Odczytuje aktywny format UAC2 (Alt 1–3) i częstotliwość próbkowania."""
    if demo:
        return PlaybackQuality(
            altset=3,
            audio_format="S32_LE",
            channels=2,
            rate_hz=demo_forced_rate or 48000,
            forced_rate_hz=demo_forced_rate,
            running=False,
            pipewire_available=True,
            source="Symulator",
        )

    alsa_info: dict = {}
    asound = Path("/proc/asound")
    if asound.is_dir():
        for stream_file in sorted(asound.glob("card*/stream0")):
            try:
                text = stream_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "MOONDROP" in text or "Position" in text:
                alsa_info = parse_alsa_stream0(text)
                break

    pw_ok, clock_rate, forced_rate = read_pipewire_rates()
    rate_hz = alsa_info.get("rate_hz") or (forced_rate if forced_rate else clock_rate)
    return PlaybackQuality(
        altset=alsa_info.get("altset"),
        audio_format=alsa_info.get("audio_format") or "",
        channels=alsa_info.get("channels"),
        rate_hz=rate_hz,
        forced_rate_hz=forced_rate,
        running=alsa_info.get("running"),
        pipewire_available=pw_ok,
        source="ALSA/PipeWire" if (alsa_info or pw_ok) else "Niedostępne",
    )


def apply_pipewire_sample_rate(rate_hz: int) -> int:
    """Ustawia clock.force-rate w PipeWire (0 = automatyczna) i potwierdza odczytem."""
    if rate_hz != 0 and rate_hz not in UAC2_SAMPLE_RATES:
        raise ValueError(f"Nieobsługiwana częstotliwość próbkowania: {rate_hz} Hz.")
    pw_metadata = shutil.which("pw-metadata")
    if pw_metadata is None:
        raise RuntimeError("Narzędzie pw-metadata (PipeWire) jest niedostępne w tym środowisku.")
    result = subprocess.run(
        [pw_metadata, "-n", "settings", "0", "clock.force-rate", str(rate_hz)],
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"kod {result.returncode}"
        raise RuntimeError(f"Nie udało się ustawić częstotliwości PipeWire: {detail}")
    pw_ok, _clock_rate, forced_rate = read_pipewire_rates()
    if not pw_ok or forced_rate != rate_hz:
        raise RuntimeError("PipeWire nie potwierdził ustawionej częstotliwości próbkowania.")
    return forced_rate


def mic_gain_label(raw: int) -> str:
    if raw == 0:
        return "0 dB"
    return f"≈ {raw * 15 / 32767:+.2f} dB".replace(".", ",").replace("-", "−")


def search_field(placeholder: str, accessible_name: str) -> QLineEdit:
    field = QLineEdit()
    field.setPlaceholderText(placeholder)
    field.setAccessibleName(accessible_name)
    field.setClearButtonEnabled(True)
    palette = field.palette()
    color = palette.color(QPalette.ColorRole.Text)
    color.setAlphaF(0.75)
    palette.setColor(QPalette.ColorRole.PlaceholderText, color)
    field.setPalette(palette)
    return field


@dataclass
class Profile:
    name: str
    slot: int
    bands: list[dict]
    preamp: float | None
    global_gain_db: int | None = None
    mic_gain_raw: int | None = None
    source: str | None = None
    target_name: str | None = None
    target_curve: tuple[tuple[float, float], ...] = ()

    def matches_eq(self, state: DeviceState) -> bool:
        return state.slot == self.slot and (
            self.slot == 0
            or (
                state.bands == [dac.quantized_band(band) for band in self.bands]
                and dac.preamp_matches(state.preamp, self.preamp, allow_half_db=True)
            )
        )

    def matches(self, state: DeviceState) -> bool:
        return (
            self.matches_eq(state)
            and (self.global_gain_db is None or self.global_gain_db == state.global_gain_db)
            and (self.mic_gain_raw is None or self.mic_gain_raw == state.mic_gain_raw)
        )


@dataclass
class DeviceState:
    path: str
    firmware: str
    slot: int
    preamp: float
    bands: list[dict | None]
    global_gain_db: int | None = None
    mic_gain_raw: int | None = None


def load_profile(path: Path, name: str | None = None) -> Profile:
    try:
        bands, meta = dac.load_eq_file(str(path))
    except SystemExit as exc:
        raise ValueError(str(exc)) from exc
    slot = meta.get("slot", dac.CUSTOM_SLOT)
    preamp = meta.get("preamp")
    stored_name = meta.get("name")
    if not isinstance(stored_name, str) or not stored_name.strip():
        stored_name = path.stem
    profile = custom_profile(
        name or stored_name, slot, bands, preamp, meta.get("global_gain_db"), meta.get("mic_gain_raw")
    )
    source = meta.get("source")
    target_name = meta.get("target_name")
    target = valid_curve(meta.get("target_curve", ()))
    if not target and (
        path.resolve() == BUILTIN_PROFILE.resolve()
        or (
            profile.name == "Position → Harman In-Ear 2019"
            and isinstance(source, str)
            and source.startswith("AutoEq · ")
        )
    ):
        try:
            target = read_target_curve(HARMAN_TARGET)
        except (OSError, ValueError):
            pass
        else:
            target_name = "Harman In-Ear 2019"
    return replace(
        profile,
        source=source if isinstance(source, str) else None,
        target_name=target_name if isinstance(target_name, str) else None,
        target_curve=target,
    )


def custom_profile(
    name: str,
    slot: int,
    bands: list[dict],
    preamp: float,
    global_gain_db: int | None = None,
    mic_gain_raw: int | None = None,
) -> Profile:
    dac.validate_profile(bands, slot, preamp)
    if slot != dac.CUSTOM_SLOT or len(bands) != dac.BAND_COUNT or type(preamp) not in (int, float):
        raise ValueError("Profil musi zawierać osiem pasm, pre-gain i dotyczyć slotu Custom.")
    if not -128 <= preamp <= 0 or any(b["type"] not in {"PK", "LP", "HP"} or not -18 <= b["gain"] <= 12 for b in bands):
        raise ValueError("Position obsługuje PK, LP i HP, gain od −18 do +12 dB i pre-gain do 0 dB.")
    if global_gain_db is not None and (type(global_gain_db) is not int or not -18 <= global_gain_db <= 0):
        raise ValueError("Global gain w profilu musi być liczbą całkowitą od −18 do 0 dB.")
    if mic_gain_raw is not None and (type(mic_gain_raw) is not int or mic_gain_raw not in MIC_GAIN_REQUESTS):
        raise ValueError("Profil zawiera niepotwierdzony kod wzmocnienia mikrofonu.")
    return Profile(name, slot, bands, preamp, global_gain_db, mic_gain_raw)


def open_position(expected_path: str | None = None) -> dac.MoondropPosition | None:
    devices = dac.candidate_devices()
    if not devices:
        if expected_path is not None:
            raise dac.HidError("Position został odłączony.")
        return None
    if len(devices) != 1:
        raise dac.HidError("Podłącz jeden MOONDROP Position.")
    path = devices[0]["node"]
    if expected_path is not None and path != expected_path:
        raise dac.HidError("Ścieżka urządzenia zmieniła się. Odczytaj stan ponownie.")
    try:
        return dac.MoondropPosition(path)
    except dac.HidPermissionError as exc:
        raise dac.HidError("Brak dostępu do DAC-a. Sprawdź regułę udev na hoście.") from exc
    except dac.HidDeviceMissing as exc:
        raise dac.HidError(
            f"System widzi DAC, ale {path} jest niedostępny. "
            "Sprawdź dostęp do urządzenia w Flatpaku lub podłącz DAC ponownie."
        ) from exc


def read_state(dev) -> DeviceState:
    slot = dev.slot()
    firmware = dev.version()
    preamp = dev.preamp()
    bands = []
    for index in range(dac.BAND_COUNT):
        bands.append(dev.read_band(index))
        time.sleep(dac.DELAY_BAND_MS / 1000)
    try:
        global_gain_db = dev.global_gain()
    except dac.HidError:
        global_gain_db = None
    mic_gain_raw = None
    if firmware in ("0.5", "demo"):
        with contextlib.suppress(dac.HidError):
            mic_gain_raw = dev.mic_gain_raw()
    if dev.slot() != slot:
        raise dac.HidError("Aktywny slot zmienił się podczas odczytu.")
    return DeviceState(dev.path, firmware, slot, preamp, bands, global_gain_db, mic_gain_raw)


def poll_device(open_device) -> DeviceState | None:
    dev = open_device()
    if dev is None:
        return None
    with dev:
        return read_state(dev)


def diagnose_controls(dev: dac.MoondropPosition) -> dict:
    """Odczyty z referencji rodziny Moondrop do sprawdzenia na Position."""
    probes = (
        ("global_gain_db", dac.CMD_GLOBAL_GAIN, (0,), 4, "<b"),
        ("dac_filter", dac.CMD_DAC_FILTER, (0,), 3, "<B"),
        ("dac_gain", dac.CMD_DAC_GAIN, (0,), 3, "<B"),
        ("dac_mode", dac.CMD_DAC_MODE, (0,), 3, "<B"),
        ("led", dac.CMD_LED, (0,), 3, "<B"),
        ("balance_channel_0_raw", dac.CMD_BALANCE, (0, 0), 5, "<B"),
        ("balance_channel_1_raw", dac.CMD_BALANCE, (0, 1), 5, "<B"),
        ("mic_gain_raw", dac.CMD_MIC_GAIN, (0,), 2, "<h"),
    )
    report = {"firmware": dev.version(), "slot": dev.slot(), "controls": {}}
    for name, cmd, args, offset, value_format in probes:
        try:
            reply = dev.request(cmd, bytes((dac.OP_READ, cmd, *args)), retries=1)
            value = struct.unpack_from(value_format, reply, offset)[0]
            if cmd == dac.CMD_BALANCE:
                value = {"value": value, "reply_byte_3": reply[3]}
            if cmd == dac.CMD_MIC_GAIN:
                value = {
                    "reply_prefix_hex": reply[:8].hex(" "),
                    "raw_offset_2": value,
                    "raw_offset_3": struct.unpack_from("<h", reply, 3)[0] if len(reply) >= 5 else None,
                }
        except (dac.HidError, struct.error) as exc:
            report["controls"][name] = {"error": str(exc)}
        else:
            report["controls"][name] = value
        time.sleep(dac.DELAY_OP_MS / 1000)
    return report


def test_global_gain(dev: dac.MoondropPosition) -> dict:
    initial = dev.global_gain()
    if not -18 < initial <= 0:
        raise dac.HidError(f"Global gain {initial} dB nie pozwala zmniejszyć go o 1 dB.")
    print(f"Global gain przed testem: {initial} dB", file=sys.stderr, flush=True)
    target = initial - 1
    try:
        dev.set_global_gain_volatile(target)
        time.sleep(dac.DELAY_OP_MS / 1000)
        observed = dev.global_gain()
        if observed != target:
            raise dac.HidError(f"Oczekiwano {target} dB, odczytano {observed} dB.")
    finally:
        try:
            dev.set_global_gain_volatile(initial)
            time.sleep(dac.DELAY_OP_MS / 1000)
            restored = dev.global_gain()
            if restored != initial:
                raise dac.HidError(f"Odczytano {restored} dB.")
        except dac.HidError as exc:
            raise dac.HidError(f"Nie potwierdzono powrotu do {initial} dB: {exc}") from exc
    return {"initial_db": initial, "test_db": observed, "restored_db": restored}


def test_mic_gain(dev: dac.MoondropPosition) -> dict:
    firmware = dev.version()
    if firmware != "0.5":
        raise dac.HidError(f"Próba wzmocnienia mikrofonu wymaga firmware 0.5. Odczytano {firmware}.")
    initial = dev.mic_gain_raw()
    if initial != 0:
        raise dac.HidError(f"Próba wymaga potwierdzonego punktu przywrócenia 0. Odczytano {initial}.")
    samples = []
    print(f"Kod wzmocnienia mikrofonu przed testem: {initial}", file=sys.stderr, flush=True)
    try:
        for target in (-512, -1024, -1536, -1920, -2048, -2080, -2184, -2304, -3072, -2048):
            dev.set_mic_gain_raw(target)
            time.sleep(dac.DELAY_OP_MS / 1000)
            observed = dev.mic_gain_raw()
            samples.append({"requested_raw": target, "observed_raw": observed})
    finally:
        try:
            dev.set_mic_gain_raw(initial)
            time.sleep(dac.DELAY_OP_MS / 1000)
            restored = dev.mic_gain_raw()
            if restored != initial:
                raise dac.HidError(f"Odczytano kod {restored}.")
        except dac.HidError as exc:
            raise dac.HidError(f"Nie potwierdzono przywrócenia kodu {initial}: {exc}") from exc
    return {"firmware": firmware, "initial_raw": initial, "samples": samples, "restored_raw": restored}


def apply_global_gain(dev, target: int) -> None:
    if dev.global_gain() == target:
        return
    dev.set_global_gain_volatile(target)
    time.sleep(dac.DELAY_OP_MS / 1000)
    actual = dev.global_gain()
    if actual != target:
        raise dac.HidError(f"Global gain: oczekiwano {target} dB, odczytano {actual} dB.")


def update_global_gain(open_device, path: str, target: int) -> DeviceState:
    with open_device(path) as dev:
        apply_global_gain(dev, target)
        state = read_state(dev)
        if state.global_gain_db != target:
            raise dac.HidError("Nie potwierdzono global gainu w końcowym odczycie.")
        return state


def apply_mic_gain(dev, target: int) -> None:
    if dev.mic_gain_raw() == target:
        return
    dev.set_mic_gain_raw(MIC_GAIN_REQUESTS[target])
    time.sleep(dac.DELAY_OP_MS / 1000)
    observed = dev.mic_gain_raw()
    if observed != target:
        raise dac.HidError(f"Mikrofon: oczekiwano kodu {target}, odczytano {observed}.")


def update_mic_gain(open_device, path: str, target: int) -> DeviceState:
    with open_device(path) as dev:
        if dev.version() not in ("0.5", "demo"):
            raise dac.HidError("Brak potwierdzonego sterowania mikrofonem dla tego firmware.")
        apply_mic_gain(dev, target)
        state = read_state(dev)
        if state.mic_gain_raw != target:
            raise dac.HidError("Końcowy odczyt nie potwierdził wzmocnienia mikrofonu.")
        return state


def apply_profile(open_device, path: str, profile: Profile) -> DeviceState:
    with open_device(path) as dev:
        state = read_state(dev)
        if profile.matches(state):
            return state
        if profile.global_gain_db is not None and state.global_gain_db is None:
            raise dac.HidError("Brak odczytu global gainu wymaganego przez profil.")
        if profile.mic_gain_raw is not None and state.mic_gain_raw is None:
            raise dac.HidError("Brak odczytu wzmocnienia mikrofonu wymaganego przez profil.")
        if not profile.matches_eq(state):
            if profile.slot == 0:
                dac.activate_slot(dev, 0)
                dev.save()
                time.sleep(dac.DELAY_FLASH_MS / 1000)
            else:
                dac.write_profile(dev, profile.bands, profile.preamp, allow_half_db=True)
        if profile.global_gain_db is not None:
            apply_global_gain(dev, profile.global_gain_db)
        if profile.mic_gain_raw is not None:
            apply_mic_gain(dev, profile.mic_gain_raw)
        state = read_state(dev)
        if not profile.matches(state):
            raise dac.HidError("DAC nie potwierdził zastosowania profilu.")
        return state


@dataclass
class LiveEqSnapshot:
    path: str
    slot: int
    preamp: float
    custom: Profile


def begin_live_eq(open_device, path: str) -> LiveEqSnapshot:
    with open_device(path) as dev:
        original_slot = dev.slot()
        original_preamp = dev.preamp()
        if original_slot not in (0, dac.CUSTOM_SLOT):
            raise dac.HidError(f"Odsłuch nie obsługuje slotu {original_slot}.")
        try:
            if original_slot != dac.CUSTOM_SLOT:
                dac.activate_slot(dev, dac.CUSTOM_SLOT)
            bands = dev.read_eq(dac.BAND_COUNT)
            if len(bands) != dac.BAND_COUNT:
                raise dac.HidError("Brak kompletnego EQ w slocie Custom. Wgraj najpierw pełny profil.")
            custom = Profile("EQ przed odsłuchem", dac.CUSTOM_SLOT, bands, dev.preamp())
            dac.validate_profile(custom.bands, custom.slot, custom.preamp)
        except (OSError, ValueError, dac.HidError):
            if original_slot != dac.CUSTOM_SLOT:
                dac.activate_slot(dev, original_slot)
                dac.apply_preamp(dev, original_preamp)
            raise
        return LiveEqSnapshot(path, original_slot, original_preamp, custom)


def listen_live_eq(
    open_device, snapshot: LiveEqSnapshot, profile: Profile, previous: Profile, previous_preamp: float
) -> float:
    with open_device(snapshot.path) as dev:
        if dev.slot() != dac.CUSTOM_SLOT:
            raise dac.HidError("Aktywny slot zmienił się podczas odsłuchu.")
        preamp_changed = profile.preamp != previous.preamp
        return dac.write_profile(
            dev,
            profile.bands,
            profile.preamp if preamp_changed else previous_preamp,
            persist=False,
            previous_bands=previous.bands,
            allow_half_db=preamp_changed,
        )


def end_live_eq(open_device, snapshot: LiveEqSnapshot, previous: Profile | None) -> None:
    with open_device(snapshot.path) as dev:
        try:
            dac.write_profile(
                dev,
                snapshot.custom.bands,
                snapshot.custom.preamp,
                persist=False,
                previous_bands=previous.bands if previous is not None else None,
            )
        finally:
            if snapshot.slot != dac.CUSTOM_SLOT:
                dac.activate_slot(dev, snapshot.slot)
                dac.apply_preamp(dev, snapshot.preamp)


def restore_defaults(open_device, path: str) -> DeviceState:
    with open_device(path) as dev:
        state = read_state(dev)
        if state.global_gain_db is None:
            raise dac.HidError("Przywracanie wymaga odczytu global gainu.")
        reset_mic = state.mic_gain_raw is not None
        slot_changed = state.slot != 0
        if slot_changed:
            dac.activate_slot(dev, 0)
        preamp_changed = dac.apply_preamp(dev, 0)
        dac.verify_profile(dev, [], 0, 0)
        if slot_changed or preamp_changed:
            dev.save()
            time.sleep(dac.DELAY_FLASH_MS / 1000)
            dac.verify_profile(dev, [], 0, 0)
        apply_global_gain(dev, 0)
        if reset_mic:
            apply_mic_gain(dev, 0)
        state = read_state(dev)
        if state.slot != 0 or state.preamp != 0 or state.global_gain_db != 0 or (reset_mic and state.mic_gain_raw != 0):
            raise dac.HidError("Końcowy odczyt nie potwierdził ustawień domyślnych.")
        return state


def read_custom_backup(open_device, path: str) -> Profile:
    with open_device(path) as dev:
        state = read_state(dev)
        if state.slot != dac.CUSTOM_SLOT or any(band is None for band in state.bands):
            raise dac.HidError("Kopia wymaga aktywnego slotu Custom i ośmiu odczytanych pasm.")
        bands = [band for band in state.bands if band is not None]
        name = "position-custom-demo" if path == "demo" else "position-custom"
        mic_gain_raw = state.mic_gain_raw if state.mic_gain_raw in MIC_GAIN_REQUESTS else None
        profile = custom_profile(name, state.slot, bands, state.preamp, state.global_gain_db, mic_gain_raw)
        dac.verify_profile(dev, profile.bands, profile.slot, profile.preamp)
        if profile.global_gain_db is not None and dev.global_gain() != profile.global_gain_db:
            raise dac.HidError("Global gain zmienił się podczas tworzenia kopii.")
        if mic_gain_raw is not None and dev.mic_gain_raw() != mic_gain_raw:
            raise dac.HidError("Wzmocnienie mikrofonu zmieniło się podczas tworzenia kopii.")
        return profile


def save_profile(path: str, profile: Profile) -> None:
    data = {
        "name": profile.name,
        "slot": profile.slot,
        "bands": profile.bands,
        "preamp": profile.preamp,
    }
    if profile.source:
        data["source"] = profile.source
    if profile.target_curve:
        data["target_name"] = profile.target_name
        data["target_curve"] = profile.target_curve
    if profile.global_gain_db is not None:
        data["global_gain_db"] = profile.global_gain_db
    if profile.mic_gain_raw is not None:
        data["mic_gain_raw"] = profile.mic_gain_raw
    payload = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    file = QSaveFile(path)
    if not file.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(file.errorString())
    if file.write(payload) != len(payload):
        file.cancelWriting()
        raise OSError(file.errorString())
    if not file.commit():
        raise OSError(file.errorString())


class DemoDevice:
    path = "demo"

    def __init__(self):
        self.active_slot = 0
        self.custom_bands = default_custom_bands()
        self.custom_preamp = 0.0
        self.default_preamp = 0.0
        self.output_gain = 0
        self.microphone_gain = 0

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        pass

    def version(self):
        return "demo"

    def slot(self):
        return self.active_slot

    def set_slot(self, slot, *, legacy=False):
        self.active_slot = slot

    def preamp(self):
        return self.default_preamp if self.active_slot == 0 else self.custom_preamp

    def set_preamp(self, db, *, legacy=True):
        if self.active_slot == 0:
            self.default_preamp = round(db * 256) / 256
        else:
            self.custom_preamp = round(db * 256) / 256

    def global_gain(self):
        return self.output_gain

    def set_global_gain_volatile(self, db):
        self.output_gain = db

    def mic_gain_raw(self):
        return self.microphone_gain

    def set_mic_gain_raw(self, value):
        self.microphone_gain = {requested: observed for observed, requested in MIC_GAIN_REQUESTS.items()}[value]

    def read_band(self, index):
        return None if self.active_slot == 0 else self.custom_bands[index]

    def read_eq(self, bands):
        return self.custom_bands[:bands] if self.active_slot == dac.CUSTOM_SLOT else []

    def write_band(self, index, freq, gain, q, ftype, _slot):
        self.custom_bands[index] = dac.quantized_band(
            {
                "band": index + 1,
                "freq": freq,
                "gain": gain,
                "q": q,
                "type": ftype,
            }
        )

    def latch_band(self, _index):
        pass

    def save(self):
        pass


class JobSignals(QObject):
    finished = Signal(object, str)


class Job(QRunnable):
    def __init__(self, operation):
        super().__init__()
        self.operation = operation
        self.signals = JobSignals()

    def run(self):
        try:
            result = self.operation()
        except Exception as exc:
            self.signals.finished.emit(None, str(exc))
        else:
            self.signals.finished.emit(result, "")


@lru_cache(maxsize=1)
def measured_position() -> list[tuple[float, float]]:
    path = DATA_DIR / "pomiary" / "Moondrop Position (B&K 5128).csv"
    try:
        freqs, dbs = read_squig_txt(path)
    except (OSError, ValueError):
        return []
    return [(hz, db) for hz, db in zip(freqs, dbs, strict=False) if 20 <= hz <= 20000 and math.isfinite(db)]


def valid_curve(points) -> tuple[tuple[float, float], ...]:
    if not isinstance(points, (tuple, list)):
        return ()
    values = {}
    for pair in points:
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            continue
        hz, db = pair
        if type(hz) in (int, float) and type(db) in (int, float) and 20 <= hz <= 20000 and -10000 < db < 10000:
            values[hz] = db
    result = tuple(sorted(values.items()))
    return result if result and result[0][0] < 1000 < result[-1][0] else ()


def read_target_curve(path: Path) -> tuple[tuple[float, float], ...]:
    frequencies, levels = read_squig_txt(path)
    curve = valid_curve(list(zip(frequencies, levels, strict=False)))
    if not curve:
        raise ValueError("Krzywa docelowa musi obejmować częstotliwość 1 kHz.")
    return curve


def response_points(profile: Profile, frequencies) -> list[tuple[float, float]]:
    if profile.preamp is None:
        return []
    bands = [dac.quantized_band(band) for band in profile.bands]
    coefficients = [
        struct.unpack(
            "<5i", dac.biquad_coefficients(dac.TYPE_TO_CODE[band["type"]], band["freq"], band["gain"], band["q"])
        )
        for band in bands
    ]
    points = []
    for frequency in frequencies:
        angle = -2 * math.pi * frequency / dac.COEFF_FS
        z = complex(math.cos(angle), math.sin(angle))
        z2 = z * z
        level = round(profile.preamp * 256) / 256
        for b0, b1, b2, neg_a1, neg_a2 in coefficients:
            numerator = abs(b0 + b1 * z + b2 * z2)
            denominator = abs(dac.COEFF_SCALE - neg_a1 * z - neg_a2 * z2)
            level += 20 * math.log10(max(numerator, 1e-12) / max(denominator, 1e-12))
        points.append((frequency, level))
    return points


def profile_from_readback(state: DeviceState) -> Profile | None:
    if state.path == "demo" and state.slot == 0:
        return Profile("Odczyt z DAC-a", 0, [], state.preamp)
    if len(state.bands) != dac.BAND_COUNT or any(
        band is None or band["type"] not in dac.TYPE_TO_CODE for band in state.bands
    ):
        return None
    return Profile("Odczyt z DAC-a", state.slot, list(state.bands), state.preamp)


class ResponsePlot(QWidget):
    SERIES_LABELS = ("Wybrany profil", "Aktualny EQ DAC-a", "Pomiar odniesienia", "Cel AutoEq przy 1 kHz")
    curves_changed = Signal()

    def __init__(self, *, correction: bool = False, include_preamp: bool = True):
        super().__init__()
        self.correction = correction
        self.include_preamp = include_preamp
        self.points = []
        self.reference_points = []
        self.target_points = []
        self.factory_points = [] if correction else measured_position()
        self.factory_filter = None
        self.frequencies = [hz for hz, _ in self.factory_points]
        self.factory_offsets = [0.0] * len(self.frequencies)
        self.setMinimumHeight(95 if correction else 135)
        self.setAccessibleName(
            "Korekcja EQ w dB" if correction else "Charakterystyka słuchawek MOONDROP Position w dB SPL"
        )

    def set_primary_points(self, points: list[tuple[float, float]]) -> None:
        self.points = points
        self.curves_changed.emit()
        self.update()

    def acoustic_points(self, profile: Profile | None) -> list[tuple[float, float]]:
        if profile is None:
            return []
        if profile.slot == 0 and profile.preamp is None:
            return self.factory_points
        source = profile if self.include_preamp or profile.preamp is None else replace(profile, preamp=0.0)
        correction = response_points(source, self.frequencies)
        return [
            (hz, measured + adjustment - factory)
            for (hz, measured), (_, adjustment), factory in zip(
                self.factory_points, correction, self.factory_offsets, strict=False
            )
        ]

    def set_profile(self, profile: Profile | None) -> None:
        self.set_primary_points(self.acoustic_points(profile))

    def set_reference(self, profile: Profile | None) -> None:
        self.set_reference_points(self.acoustic_points(profile))

    def set_reference_points(self, points: list[tuple[float, float]]) -> None:
        self.reference_points = points
        self.curves_changed.emit()
        self.update()

    def set_target_points(self, points: list[tuple[float, float]]) -> None:
        self.target_points = points
        self.curves_changed.emit()
        self.update()

    def set_factory(self, profile: Profile | None) -> None:
        if profile != self.factory_filter:
            self.factory_filter = profile
            self.factory_offsets = (
                [db for _, db in response_points(profile, self.frequencies)]
                if profile
                else [0.0] * len(self.frequencies)
            )

    @staticmethod
    def same_response(first: list[tuple[float, float]], second: list[tuple[float, float]]) -> bool:
        tolerance = 1e-6
        if len(first) == len(second) and all(
            hz == other_hz and abs(db - other_db) < tolerance
            for (hz, db), (other_hz, other_db) in zip(first, second, strict=False)
        ):
            return True
        baseline = first[0][1]
        return all(abs(db - baseline) < tolerance for _, db in first + second)

    def series(self):
        groups = []
        for role, points in enumerate((self.points, self.reference_points, self.factory_points, self.target_points)):
            if not points:
                continue
            for roles, existing in groups:
                if self.same_response(existing, points):
                    roles.append(role)
                    break
            else:
                groups.append(([role], points))
        return groups

    def series_pen(self, role: int) -> QPen:
        dark_bg = self.palette().base().color().lightness() < 128
        colors = (
            ("#ff8a1f", "#38bdf8", "#c9bfb4", "#34d399") if dark_bg else ("#e55d00", "#0284c7", "#57534e", "#059669")
        )
        # Role: 0 = wybrany/edytowany, 1 = referencja/DAC, 2 = pomiar Position, 3 = cel AutoEq
        palette_hex = (colors[0], colors[2], colors[1], colors[3])
        styles = (Qt.PenStyle.SolidLine, Qt.PenStyle.DashLine, Qt.PenStyle.DotLine, Qt.PenStyle.DashDotLine)
        return QPen(QColor(palette_hex[role]), (2.2, 1.6, 2.0, 1.9)[role], styles[role])

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        text = palette.color(QPalette.ColorRole.Text)
        card_rect = self.rect().adjusted(0, 0, -1, -1)
        painter.setBrush(palette.base())
        painter.setPen(QPen(palette.color(QPalette.ColorRole.Mid), 1))
        painter.drawRoundedRect(card_rect, 8, 8)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        groups = self.series()
        all_points = [point for _, points in groups for point in points]
        if not all_points:
            painter.setPen(text)
            painter.drawText(
                self.rect().adjusted(10, 0, -10, 0),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                tr("plot.empty_eq") if self.correction else tr("plot.empty_fr"),
            )
            return
        plot = self.rect().adjusted(50, 14, -18, -26)
        lowest = min(db for _, db in all_points)
        highest = max(db for _, db in all_points)
        if self.correction:
            step = max(3, math.ceil((max(0, highest) - min(0, lowest)) / 12) * 3)
            low = min(-step, math.floor(lowest / step) * step)
            high = max(step, math.ceil(highest / step) * step)
        else:
            step = max(10, math.ceil((highest - lowest) / 60) * 10)
            low = math.floor(lowest / step) * step
            high = max(low + step, math.ceil(highest / step) * step)

        def x(hz: float) -> float:
            return plot.left() + plot.width() * math.log10(hz / 20) / 3

        def y(db: float) -> float:
            return plot.top() + plot.height() * (high - db) / (high - low)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        grid_color = palette.color(QPalette.ColorRole.Text)
        grid_color.setAlpha(45)
        zero_color = palette.color(QPalette.ColorRole.Text)
        zero_color.setAlpha(95)
        for db in range(low, high + 1, step):
            yy = round(y(db))
            grid_pen = QPen(
                zero_color if self.correction and db == 0 else grid_color, 1.4 if self.correction and db == 0 else 1
            )
            painter.setPen(grid_pen)
            painter.drawLine(plot.left(), yy, plot.right(), yy)
            painter.setPen(text)
            painter.drawText(6, yy + 5, f"{db} dB")
        for hz, label in ((20, "20 Hz"), (100, "100"), (1000, "1k"), (10000, "10k"), (20000, "20k")):
            xx = round(x(hz))
            painter.setPen(grid_color)
            painter.drawLine(xx, plot.top(), xx, plot.bottom())
            painter.setPen(text)
            painter.drawText(xx - painter.fontMetrics().horizontalAdvance(label) // 2, plot.bottom() + 18, label)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for roles, points in reversed(groups):
            curve = QPainterPath(QPointF(x(points[0][0]), y(points[0][1])))
            for hz, db in points[1:]:
                curve.lineTo(QPointF(x(hz), y(db)))
            if self.correction and roles[0] == 0:
                fill_path = QPainterPath(curve)
                baseline_y = y(0.0)
                fill_path.lineTo(QPointF(x(points[-1][0]), baseline_y))
                fill_path.lineTo(QPointF(x(points[0][0]), baseline_y))
                fill_path.closeSubpath()
                fill_color = self.series_pen(0).color()
                fill_color.setAlpha(38)
                painter.fillPath(fill_path, fill_color)
            painter.setPen(self.series_pen(roles[0]))
            painter.drawPath(curve)


class CurveSwatch(QWidget):
    def __init__(self, plot: ResponsePlot, role: int):
        super().__init__()
        self.plot = plot
        self.role = role
        self.setFixedSize(30, max(14, self.fontMetrics().lineSpacing()))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(self.plot.series_pen(self.role))
        y = self.height() / 2
        painter.drawLine(QPointF(2, y), QPointF(self.width() - 2, y))


class PlotKey(QWidget):
    def __init__(self, plot: ResponsePlot, labels: tuple[str, ...]):
        super().__init__()
        self.plot = plot
        self.labels = labels
        self.rows = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        for role in range(len(labels)):
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            line.addWidget(CurveSwatch(plot, role), 0, Qt.AlignmentFlag.AlignTop)
            label = QLabel()
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            line.addWidget(label, 1)
            layout.addWidget(row)
            self.rows.append((row, label))
        layout.addStretch(1)
        plot.curves_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        groups = {roles[0]: roles for roles, _ in self.plot.series()}
        for role, (row, label) in enumerate(self.rows):
            roles = groups.get(role, [])
            row.setVisible(bool(roles))
            if roles:
                label.setText(" = ".join(self.labels[index] for index in roles))


class AboutHelpDialog(QDialog):
    """Okno wyjaśniające cel wersji Linux, podpowiedzi oraz odnośniki do InnoVibe, wsparcia i GitHuba."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setWindowTitle(tr("help.title"))
        self.setStyleSheet(APP_STYLE)
        self.setMinimumSize(580, 440)
        self.resize(640, 500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        heading = QLabel(tr("app.title"))
        font = heading.font()
        font.setPointSizeF(font.pointSizeF() * 1.35)
        font.setBold(True)
        heading.setFont(font)
        subtitle = QLabel(tr("help.subtitle"))
        subtitle.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(subtitle)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(tr("help.body_html"))
        browser.setStyleSheet("QTextBrowser { border: 1px solid palette(mid); border-radius: 8px; padding: 8px; }")
        layout.addWidget(browser, 1)

        buttons = QHBoxLayout()
        author_btn = QPushButton(tr("footer.author_label"))
        author_btn.setToolTip(tr("footer.author_tooltip"))
        author_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(tr("footer.author_url"))))
        coffee_btn = QPushButton(tr("footer.coffee"))
        coffee_btn.setToolTip(tr("footer.coffee_tooltip"))
        coffee_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(tr("footer.coffee_url"))))
        hub_btn = QPushButton(tr("help.open_hub"))
        hub_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(OFFICIAL_HUB_URL)))
        close_btn = QPushButton(tr("help.close"))
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(author_btn)
        buttons.addWidget(coffee_btn)
        buttons.addWidget(hub_btn)
        buttons.addStretch()
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)


class EqualizerDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        source: Profile | None,
        current: Profile | None,
        factory: Profile | None = None,
        *,
        device_path: str | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(tr("editor.title"))
        self.setStyleSheet(APP_STYLE)
        self.setMinimumSize(780, 720)
        self.resize(860, 800)
        self.result_profile = None
        self.result_apply = False
        self.device_window = parent
        self.device_path = device_path
        self.live_initialized = False
        self.live_snapshot = None
        self.live_previous = None
        self.live_preamp = None
        self.live_busy = False
        self.pending_exit = None
        self.live_error = ""
        self.rows = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        top_bar = QHBoxLayout()
        top_bar.setSpacing(10)
        self.name = QLineEdit()
        self.name.setAccessibleName(tr("editor.profile_label"))
        self.name.setPlaceholderText(tr("editor.profile_placeholder"))
        self.name.setToolTip(tr("tooltip.editor_name"))
        top_bar.addWidget(QLabel(tr("editor.profile_label")))
        top_bar.addWidget(self.name, 1)
        self.preamp = self.decimal(-128, 0, 0.1)
        self.preamp.setSuffix(" dB")
        self.preamp.setFixedWidth(120)
        self.preamp.setAccessibleName(tr("editor.preamp_label"))
        self.preamp.setToolTip(tr("tooltip.editor_preamp"))
        top_bar.addWidget(QLabel(tr("editor.preamp_label")))
        top_bar.addWidget(self.preamp)
        if current is not None:
            copy = QPushButton(tr("editor.load_dac"))
            copy.setToolTip(tr("tooltip.editor_load_dac"))
            copy.clicked.connect(lambda: self.set_profile(current))
            top_bar.addWidget(copy)
        self.live = QCheckBox(tr("editor.live"))
        self.live.setEnabled(device_path is not None)
        self.live.setToolTip(
            "Regulacja EQ i pre-gainu w DAC-u podczas edycji."
            if device_path is not None
            else "Podłącz DAC, aby włączyć odsłuch."
        )
        self.live.toggled.connect(self.toggle_live)
        top_bar.addWidget(self.live)
        layout.addLayout(top_bar)
        gain_panel = QWidget()
        gain_form = QFormLayout(gain_panel)
        gain_form.setContentsMargins(0, 0, 0, 0)
        global_row = QHBoxLayout()
        self.include_global_gain = QCheckBox(tr("editor.include_gain"))
        self.global_gain = QSpinBox()
        self.global_gain.setAccessibleName(tr("editor.output_gain"))
        self.global_gain.setRange(-18, 0)
        self.global_gain.setSuffix(" dB")
        self.include_global_gain.toggled.connect(self.global_gain.setEnabled)
        global_row.addWidget(self.include_global_gain)
        global_row.addWidget(self.global_gain)
        gain_form.addRow(tr("editor.output_gain"), global_row)
        mic_row = QHBoxLayout()
        self.include_mic_gain = QCheckBox(tr("editor.include_gain"))
        self.mic_gain = QComboBox()
        self.mic_gain.setAccessibleName(tr("editor.mic_gain"))
        for raw in MIC_GAIN_REQUESTS:
            self.mic_gain.addItem(mic_gain_label(raw), raw)
        self.include_mic_gain.toggled.connect(self.mic_gain.setEnabled)
        mic_row.addWidget(self.include_mic_gain)
        mic_row.addWidget(self.mic_gain)
        gain_form.addRow(tr("editor.mic_gain"), mic_row)

        self.plot = ResponsePlot()
        self.plot.setMinimumHeight(180)
        self.plot.set_factory(factory)
        plot_header = QHBoxLayout()
        plot_header.addWidget(QLabel(tr("plot.fr_title")))
        plot_header.addStretch()
        self.compare = QCheckBox(tr("editor.compare"))
        self.compare.setToolTip(tr("tooltip.editor_compare"))
        self.compare.toggled.connect(self.update_reference)
        plot_header.addWidget(self.compare)
        layout.addLayout(plot_header)
        layout.addWidget(self.plot, 1)
        layout.addWidget(PlotKey(self.plot, ("Edytowany profil", "Profil wyjściowy", tr("plot.key.measured"))))
        measurement_note = QLabel(tr("plot.measurement_note"))
        measurement_note.setWordWrap(True)
        if factory is None:
            measurement_note.setText(measurement_note.text() + " · podgląd zakłada neutralne EQ fabryczne")
        layout.addWidget(measurement_note)
        self.plot_timer = QTimer(self, singleShot=True, interval=0)
        self.plot_timer.timeout.connect(self.update_draft)
        self.live_timer = QTimer(self, singleShot=True, interval=140)
        self.live_timer.timeout.connect(self.send_live)
        self.preamp.valueChanged.connect(lambda: self.plot_timer.start())
        grid = QGridLayout()
        grid.setVerticalSpacing(6)
        grid.setHorizontalSpacing(8)
        for column, title in enumerate(
            (
                tr("editor.col_band"),
                tr("editor.col_type"),
                tr("editor.col_freq"),
                tr("editor.col_gain"),
                "",
                tr("editor.col_q"),
            )
        ):
            grid.addWidget(QLabel(title), 0, column)
        grid.setColumnStretch(3, 1)
        for number in range(1, dac.BAND_COUNT + 1):
            kind = QComboBox()
            for label, code in (
                (tr("editor.type_pk"), "PK"),
                (tr("editor.type_lp"), "LP"),
                (tr("editor.type_hp"), "HP"),
            ):
                kind.addItem(label, code)
            frequency = QSpinBox()
            frequency.setRange(20, 20000)
            frequency.setMinimumWidth(88)
            gain = self.decimal(-18, 12, 0.1)
            gain.setMinimumWidth(78)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(-180, 120)
            slider.setPageStep(10)
            slider.setMinimumWidth(105)
            slider.valueChanged.connect(lambda value, box=gain: box.setValue(value / 10))
            gain.valueChanged.connect(lambda value, control=slider: self.sync_gain_slider(control, value))
            q = self.decimal(26 / 256, 10, 0.01)
            q.setMinimumWidth(78)
            for control in (kind, frequency, gain, q):
                control.setMinimumHeight(28)
            grid.addWidget(QLabel(str(number)), number, 0)
            for column, label, widget in (
                (1, "Typ filtra", kind),
                (2, "Częstotliwość", frequency),
                (3, "Suwak gainu", slider),
                (4, "Gain", gain),
                (5, "Q", q),
            ):
                widget.setAccessibleName(f"{label}, pasmo {number}")
                grid.addWidget(widget, number, column)
            self.rows.append((kind, frequency, gain, q))
            kind.currentIndexChanged.connect(
                lambda _index, box=kind, control=slider, value=gain: self.filter_type_changed(box, control, value)
            )
            for control in (frequency, gain, q):
                control.valueChanged.connect(lambda: self.plot_timer.start())
        layout.addLayout(grid)
        self.gain_options = QToolButton()
        self.gain_options.setText(tr("editor.gain_options"))
        self.gain_options.setToolTip(tr("tooltip.editor_gain_options"))
        self.gain_options.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.gain_options.setArrowType(Qt.ArrowType.RightArrow)
        self.gain_options.setCheckable(True)
        self.gain_options.toggled.connect(gain_panel.setVisible)
        self.gain_options.toggled.connect(
            lambda opened: self.gain_options.setArrowType(Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow)
        )
        layout.addWidget(self.gain_options, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(gain_panel)
        gain_panel.hide()

        self.live_status = QLabel()
        self.live_status.setTextFormat(Qt.TextFormat.PlainText)
        self.live_status.setWordWrap(True)
        self.live_status.hide()
        layout.addWidget(self.live_status)
        self.message = QLabel()
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        buttons = QDialogButtonBox()
        buttons.addButton(tr("editor.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        pick = buttons.addButton(tr("editor.save_profile"), QDialogButtonBox.ButtonRole.AcceptRole)
        pick.setToolTip(tr("tooltip.editor_save"))
        save = buttons.addButton(tr("editor.export_json"), QDialogButtonBox.ButtonRole.ActionRole)
        save.setToolTip(tr("tooltip.editor_export"))
        self.upload = buttons.addButton(tr("editor.upload_dac"), QDialogButtonBox.ButtonRole.ApplyRole)
        self.upload.setToolTip(tr("tooltip.editor_upload"))
        self.upload.setEnabled(device_path is not None)
        if device_path is not None:
            self.upload.setStyleSheet(PRIMARY_ACTION_STYLE)
        self.upload.clicked.connect(self.apply_draft)
        buttons.rejected.connect(self.reject)
        pick.clicked.connect(self.select_draft)
        save.clicked.connect(self.save_draft)
        layout.addWidget(buttons)

        if source is None:
            source = Profile("Własny EQ", dac.CUSTOM_SLOT, default_custom_bands(), 0)
        self.set_profile(source)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.device_path is not None and not self.live_initialized:
            self.live_initialized = True
            self.live.setChecked(True)

    @staticmethod
    def sync_gain_slider(slider: QSlider, value: float) -> None:
        blocked = slider.blockSignals(True)
        slider.setValue(round(value * 10))
        slider.blockSignals(blocked)

    def filter_type_changed(self, kind: QComboBox, slider: QSlider, gain: QDoubleSpinBox) -> None:
        enabled = kind.currentData() == "PK"
        slider.setEnabled(enabled)
        gain.setEnabled(enabled)
        self.plot_timer.start()

    @staticmethod
    def decimal(minimum: float, maximum: float, step: float) -> QDoubleSpinBox:
        widget = QDoubleSpinBox()
        widget.setDecimals(2)
        widget.setRange(minimum, maximum)
        widget.setSingleStep(step)
        return widget

    def set_profile(self, profile: Profile) -> None:
        self.reference = profile
        self.name.setText(profile.name)
        self.preamp.setValue(profile.preamp)
        included = profile.global_gain_db is not None
        self.include_global_gain.setChecked(included)
        self.global_gain.setEnabled(included)
        self.global_gain.setValue(profile.global_gain_db if included else 0)
        include_mic = profile.mic_gain_raw is not None
        if included or include_mic:
            self.gain_options.setChecked(True)
        self.include_mic_gain.setChecked(include_mic)
        self.mic_gain.setEnabled(include_mic)
        self.mic_gain.setCurrentIndex(self.mic_gain.findData(profile.mic_gain_raw if include_mic else 0))
        for band, (kind, frequency, gain, q) in zip(profile.bands, self.rows, strict=False):
            band = dac.quantized_band(band)
            kind.setCurrentIndex(kind.findData(band["type"]))
            frequency.setValue(band["freq"])
            gain.setValue(band["gain"])
            q.setValue(band["q"])
        self.plot_timer.start()
        self.update_reference()
        self.message.clear()

    def update_reference(self) -> None:
        self.plot.set_reference(self.reference if self.compare.isChecked() else None)

    def draft(self) -> Profile:
        bands = [
            dac.quantized_band(
                {
                    "band": index,
                    "type": kind.currentData(),
                    "freq": frequency.value(),
                    "gain": gain.value(),
                    "q": q.value(),
                }
            )
            for index, (kind, frequency, gain, q) in enumerate(self.rows, 1)
        ]
        preamp = dac.clamp_i16(self.preamp.value() * 256) / 256
        global_gain_db = self.global_gain.value() if self.include_global_gain.isChecked() else None
        mic_gain_raw = self.mic_gain.currentData() if self.include_mic_gain.isChecked() else None
        profile = custom_profile(
            self.name.text().strip() or "Własny EQ", dac.CUSTOM_SLOT, bands, preamp, global_gain_db, mic_gain_raw
        )
        return replace(
            profile,
            source=self.reference.source,
            target_name=self.reference.target_name,
            target_curve=self.reference.target_curve,
        )

    def select_draft(self) -> None:
        self.result_profile = self.draft()
        self.result_apply = False
        self.accept()

    def apply_draft(self) -> None:
        self.result_profile = self.draft()
        self.result_apply = True
        self.accept()

    def update_draft(self) -> None:
        profile = self.draft()
        if self.live.isChecked() and self.live_previous is not None and profile.preamp == self.live_previous.preamp:
            profile = replace(profile, preamp=self.live_preamp)
        self.plot.set_profile(profile)
        if self.live.isChecked() and not self.live_timer.isActive():
            self.live_timer.start()

    def run_live(self, operation, finished) -> None:
        self.live_busy = True
        self.device_window.start(operation, finished)

    def show_live_status(self, message: str) -> None:
        self.live_status.setText(message)
        self.live_status.setVisible(bool(message))

    def toggle_live(self, enabled: bool) -> None:
        if not enabled:
            self.live_timer.stop()
            self.plot.set_profile(self.draft())
            self.settle_live()
            return
        if self.live_busy:
            return
        self.live_error = ""
        self.live.setEnabled(False)
        self.show_live_status("Odczytuję ustawienia DAC-a przed odsłuchem…")
        self.run_live(
            lambda: begin_live_eq(self.device_window.open_device, self.device_path),
            self.live_started,
        )

    def live_started(self, snapshot, error: str) -> None:
        self.live_busy = False
        if error:
            self.fail_live("Nie udało się uruchomić odsłuchu.", error)
            self.settle_live()
            return
        self.live_snapshot = snapshot
        self.live_previous = snapshot.custom
        self.live_preamp = snapshot.custom.preamp
        self.live.setEnabled(self.pending_exit is None)
        if self.live.isChecked():
            self.send_live()
        else:
            self.settle_live()

    def send_live(self) -> None:
        if not self.live.isChecked() or self.live_busy or self.live_snapshot is None:
            return
        profile = self.draft()
        previous = self.live_previous
        if (profile.bands, profile.preamp) == (previous.bands, previous.preamp):
            self.plot.set_profile(replace(profile, preamp=self.live_preamp))
            if dac.preamp_matches(self.live_preamp, profile.preamp):
                self.show_live_status("Odsłuch aktywny. Zmieniaj suwaki i ustawienia pasm.")
            else:
                self.show_live_status(
                    f"Odsłuch aktywny · pre-gain DAC-a {self.live_preamp:+.2f} dB (profil {profile.preamp:+.2f} dB)."
                )
            return
        snapshot = self.live_snapshot
        actual_preamp = self.live_preamp
        self.run_live(
            lambda: listen_live_eq(self.device_window.open_device, snapshot, profile, previous, actual_preamp),
            lambda preamp, error: self.live_written(profile, preamp, error),
        )

    def live_written(self, profile: Profile, preamp: float | None, error: str) -> None:
        self.live_busy = False
        if error:
            self.fail_live("Odsłuch przerwany.", error)
        else:
            self.live_previous = profile
            self.live_preamp = preamp
        self.settle_live()

    def fail_live(self, message: str, error: str) -> None:
        self.live_error = f"{message} {error}"
        was_blocked = self.live.blockSignals(True)
        self.live.setChecked(False)
        self.live.blockSignals(was_blocked)

    def settle_live(self) -> None:
        if self.live_busy:
            return
        if self.live.isChecked():
            if not self.live_timer.isActive():
                self.send_live()
            return
        if self.live_snapshot is not None:
            snapshot = self.live_snapshot
            previous = self.live_previous if not self.live_error else None
            self.live.setEnabled(False)
            self.show_live_status("Przywracam EQ sprzed odsłuchu…")
            self.run_live(lambda: end_live_eq(self.device_window.open_device, snapshot, previous), self.live_restored)
            return
        if self.pending_exit is not None:
            if self.live_error:
                self.device_window.feedback.setText(self.live_error)
            super().done(self.pending_exit)
        else:
            self.live.setEnabled(self.device_path is not None)
            self.show_live_status(self.live_error)

    def live_restored(self, _result, error: str) -> None:
        self.live_busy = False
        self.live_snapshot = None
        self.live_previous = None
        self.live_preamp = None
        if error:
            self.fail_live("Przywrócenie EQ sprzed odsłuchu niepotwierdzone.", error)
            self.upload.setEnabled(False)
            if self.pending_exit is not None and self.result_apply:
                self.pending_exit = QDialog.DialogCode.Rejected
        self.settle_live()

    def done(self, result: int) -> None:
        self.pending_exit = result
        self.setEnabled(False)
        self.live_timer.stop()
        if self.live.isChecked():
            self.live.setChecked(False)
        else:
            self.settle_live()

    def save_draft(self) -> None:
        profile = self.draft()
        filename = profile.name.replace("/", "_") + ".json"
        path, _selected_filter = QFileDialog.getSaveFileName(
            self, "Zapisz profil EQ", filename, "Profile JSON (*.json)"
        )
        if not path:
            return
        try:
            save_profile(path, profile)
        except OSError as exc:
            self.message.setText(f"Błąd zapisu profilu. {exc}")
            return
        self.message.setText("Profil zapisany.")


class CatalogListModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries: list[catalog.Entry] = []

    def set_entries(self, entries: list[catalog.Entry]) -> None:
        self.beginResetModel()
        self.entries = entries
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        return 0 if (parent is not None and parent.isValid()) else len(self.entries)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.entries):
            return None
        entry = self.entries[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return f"{entry.name}\n{entry.source}"
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{entry.name} · {entry.source}"
        if role == PROFILE_ROLE:
            return entry
        return None


class AutoEqPanel(QWidget):
    preview_changed = Signal()

    def __init__(self, parent, cache_directory: Path):
        super().__init__(parent)
        self.window = parent
        self.cache_directory = cache_directory
        self.index_path = cache_directory / "catalog.json"
        self.local_index_path = cache_directory / "local-catalog.json"
        self.entries = [catalog.Entry("Harman In-Ear 2019", "Krzywa referencyjna", "target", str(HARMAN_TARGET), True)]
        self.result = None
        self.result_entry = None
        self.result_details = ""
        self.job = None
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.process = QProcess(self)
        self.process.finished.connect(self.fit_finished)
        self.process.errorOccurred.connect(self.fit_error)
        self.fit_timer = QTimer(self, singleShot=True, interval=90000)
        self.fit_timer.timeout.connect(self.fit_timeout)
        self.temporary = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self.mode = QComboBox()
        self.mode.addItem(tr("autoeq.mode.all"), "all")
        self.mode.addItem(tr("autoeq.mode.in_ear"), "in-ear")
        self.mode.addItem(tr("autoeq.mode.over_ear"), "over-ear")
        self.mode.addItem(tr("autoeq.mode.target"), "target")
        self.mode.setAccessibleName(tr("autoeq.mode_a11y"))
        self.source_filter = QComboBox()
        self.source_filter.setAccessibleName(tr("autoeq.source_a11y"))
        self.source_filter.addItem(tr("autoeq.source_all"), "")
        filter_row.addWidget(self.mode, 1)
        filter_row.addWidget(self.source_filter, 1)
        layout.addLayout(filter_row)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.search = search_field(tr("search.autoeq_placeholder"), tr("search.autoeq_a11y"))
        self.catalog_menu = QMenu(self)
        self.refresh_action = QAction(tr("autoeq.download_catalog"), self)
        self.refresh_action.triggered.connect(self.download_catalog)
        self.folder_action = self.catalog_menu.addAction(tr("autoeq.open_local"), self.open_catalog)
        self.file_action = self.catalog_menu.addAction(tr("autoeq.open_custom"), self.open_target)
        self.catalog_button = QToolButton()
        self.catalog_button.setDefaultAction(self.refresh_action)
        self.catalog_button.setMenu(self.catalog_menu)
        self.catalog_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.catalog_button.setMinimumWidth(148)
        search_row.addWidget(self.search, 1)
        search_row.addWidget(self.catalog_button)
        layout.addLayout(search_row)

        self.target_model = CatalogListModel(self)
        self.targets = QListView()
        self.targets.setModel(self.target_model)
        self.targets.setUniformItemSizes(True)
        self.targets.setAccessibleName("Cele dopasowania AutoEq")
        self.targets.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.targets.setTextElideMode(Qt.TextElideMode.ElideRight)
        layout.addWidget(self.targets, 1)

        self.status = self.text_label()
        layout.addWidget(self.status)
        self.generate = QPushButton(tr("autoeq.compute"))
        self.cancel = QPushButton(tr("autoeq.cancel"))
        self.cancel.hide()
        self.apply_tooltips()

        self.mode.currentIndexChanged.connect(self.update_results)
        self.source_filter.currentIndexChanged.connect(self.update_results)
        self.search.textChanged.connect(self.update_results)
        self.targets.selectionModel().currentChanged.connect(self.target_changed)
        self.generate.clicked.connect(self.generate_profile)
        self.cancel.clicked.connect(self.cancel_fit)
        for path in (self.index_path, self.local_index_path):
            try:
                cached = json.loads(path.read_text())
                self.entries.extend([catalog.Entry(**entry) for entry in cached])
            except (OSError, ValueError, TypeError):
                pass
        self.update_results()

    def refresh_source_filter(self) -> None:
        mode = self.mode.currentData()
        kind = "target" if mode == "target" else "model"
        sources = sorted(
            {
                catalog.measurement_source(entry)
                for entry in self.entries
                if entry.kind == kind
                and (mode not in ("in-ear", "over-ear") or catalog.headphone_form(entry) == mode)
                and catalog.measurement_source(entry)
            },
            key=str.casefold,
        )
        selected = self.source_filter.currentData() or ""
        blocked = self.source_filter.blockSignals(True)
        self.source_filter.clear()
        self.source_filter.addItem(tr("autoeq.source_all"), "")
        for name in sources:
            self.source_filter.addItem(name, name)
        index = self.source_filter.findData(selected)
        self.source_filter.setCurrentIndex(index if index >= 0 else 0)
        self.source_filter.blockSignals(blocked)

    @staticmethod
    def text_label() -> QLabel:
        label = QLabel()
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        return label

    def current_entry(self) -> catalog.Entry | None:
        index = self.targets.currentIndex()
        if not index.isValid() or not 0 <= index.row() < len(self.target_model.entries):
            return None
        return self.target_model.entries[index.row()]

    def update_results(self) -> None:
        self.refresh_source_filter()
        previous = self.current_entry()
        query = self.search.text().casefold().split()
        mode = self.mode.currentData()
        kind = "target" if mode == "target" else "model"
        selected_source = self.source_filter.currentData() or ""
        matching = sorted(
            {
                entry
                for entry in self.entries
                if entry.kind == kind
                and (mode not in ("in-ear", "over-ear") or catalog.headphone_form(entry) == mode)
                and (not selected_source or catalog.measurement_source(entry) == selected_source)
                and all(term in f"{entry.name} {entry.source}".casefold() for term in query)
            },
            key=lambda entry: (entry.name.casefold(), not entry.local, entry.source.casefold(), entry.path),
        )
        selection_model = self.targets.selectionModel()
        selection_model.blockSignals(True)
        self.target_model.set_entries(matching)
        if matching:
            row = matching.index(previous) if previous in matching else 0
            self.targets.setCurrentIndex(self.target_model.index(row, 0))
        else:
            self.targets.setCurrentIndex(QModelIndex())
        selection_model.blockSignals(False)
        self.target_changed()
        if not matching:
            if any(entry.kind == kind for entry in self.entries):
                message = tr("autoeq.no_matches")
            else:
                message = tr("autoeq.no_catalog")
        else:
            message = tr("autoeq.results_count", count=len(matching))
        self.status.setText(message)

    def apply_tooltips(self) -> None:
        self.mode.setToolTip(tr("tooltip.autoeq_mode"))
        self.source_filter.setToolTip(tr("tooltip.autoeq_source"))
        self.search.setToolTip(tr("tooltip.autoeq_search"))
        self.catalog_button.setToolTip(tr("tooltip.autoeq_catalog_btn"))
        self.generate.setToolTip(tr("tooltip.autoeq_compute"))

    def retranslate_ui(self) -> None:
        for index, key in enumerate(
            (
                "autoeq.mode.all",
                "autoeq.mode.in_ear",
                "autoeq.mode.over_ear",
                "autoeq.mode.target",
            )
        ):
            self.mode.setItemText(index, tr(key))
        self.mode.setAccessibleName(tr("autoeq.mode_a11y"))
        self.search.setPlaceholderText(tr("search.autoeq_placeholder"))
        self.search.setAccessibleName(tr("search.autoeq_a11y"))
        self.refresh_action.setText(tr("autoeq.download_catalog"))
        self.folder_action.setText(tr("autoeq.open_local"))
        self.file_action.setText(tr("autoeq.open_custom"))
        self.source_filter.setAccessibleName(tr("autoeq.source_a11y"))
        self.generate.setText(tr("autoeq.compute"))
        self.cancel.setText(tr("autoeq.cancel"))
        self.apply_tooltips()
        self.update_results()

    def target_changed(self, *_args) -> None:
        entry = self.current_entry()
        if entry is None or entry != self.result_entry:
            self.result = None
            self.result_details = ""
        self.update_actions()
        self.preview_changed.emit()

    def update_actions(self) -> None:
        busy = self.job is not None or self.temporary is not None
        self.generate.setEnabled(not busy and self.current_entry() is not None)
        self.generate.setStyleSheet(PRIMARY_ACTION_STYLE if self.result is None else "")
        self.targets.setEnabled(not busy)
        self.search.setEnabled(not busy)
        self.mode.setEnabled(not busy)
        for action in (self.refresh_action, self.folder_action, self.file_action):
            action.setEnabled(not busy)
        self.preview_changed.emit()

    def start_job(self, operation, handler) -> None:
        if self.job is not None:
            return
        self.job_handler = handler
        self.job = Job(operation)
        self.job.signals.finished.connect(self.job_done)
        self.pool.start(self.job)
        self.update_actions()
        self.preview_changed.emit()

    def job_done(self, result, error: str) -> None:
        self.job = None
        self.job_handler(result, error)
        self.update_actions()
        self.preview_changed.emit()

    def download_catalog(self) -> None:
        self.status.setText("Pobieram indeks pomiarów AutoEq…")
        self.start_job(lambda: catalog.download_index(self.index_path), self.catalog_downloaded)

    def catalog_downloaded(self, entries, error: str) -> None:
        if error:
            self.status.setText(f"Nie udało się pobrać katalogu. {error}")
            return
        self.entries = [entry for entry in self.entries if entry.local] + entries
        self.update_results()

    def open_catalog(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Wybierz folder repozytorium AutoEq")
        if path:
            self.status.setText("Indeksuję lokalne pomiary…")
            self.start_job(lambda: self.index_local_catalog(Path(path)), self.catalog_opened)

    def index_local_catalog(self, root: Path) -> list[catalog.Entry]:
        entries = catalog.scan_checkout(root)
        catalog.save_index(self.local_index_path, entries)
        return entries

    def catalog_opened(self, entries, error: str) -> None:
        if error:
            self.status.setText(error)
            return
        self.entries = [
            entry
            for entry in self.entries
            if not entry.local or entry.source in ("Krzywa referencyjna", "Plik lokalny")
        ] + entries
        self.update_results()

    def open_target(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Wybierz krzywą docelową", "", "Pomiary (*.csv *.txt)")
        if path:
            entry = catalog.Entry(Path(path).stem, "Plik lokalny", "target", path, True)
            self.entries = list(dict.fromkeys([*self.entries, entry]))
            self.mode.setCurrentIndex(self.mode.findData("target"))
            self.search.clear()
            self.update_results()
            if entry in self.target_model.entries:
                row = self.target_model.entries.index(entry)
                self.targets.setCurrentIndex(self.target_model.index(row, 0))

    def generate_profile(self) -> None:
        entry = self.current_entry()
        if entry is None:
            return
        self.result = None
        self.result_entry = entry
        self.result_details = ""
        self.status.setText("Odczytuję pomiar docelowy…")
        self.start_job(lambda: catalog.resolve_curve(entry, self.cache_directory / "curves"), self.start_fit)

    def start_fit(self, target, error: str) -> None:
        if self.result_entry is None:
            return
        if error:
            self.status.setText(f"Nie udało się odczytać celu. {error}")
            return
        try:
            self.target_curve = read_target_curve(target)
        except (OSError, ValueError) as exc:
            self.status.setText(f"Nieprawidłowa krzywa docelowa. {exc}")
            return
        self.fit_factory = self.window.factory_profile
        measurement = DATA_DIR / "pomiary" / "Moondrop Position (B&K 5128).csv"
        if not measurement.exists():
            self.status.setText(tr("autoeq.missing_measurement"))
            self.finish_fit()
            return
        try:
            self.temporary = TemporaryDirectory(prefix="position-autoeq-")
            work = Path(self.temporary.name)
            if self.fit_factory is not None:
                measured = measured_position()
                offsets = response_points(self.fit_factory, [hz for hz, _ in measured])
                if measured and len(offsets) == len(measured):
                    measurement = work / "position bez korekty fabrycznej.csv"
                    measurement.write_text(
                        "frequency,raw\n"
                        + "".join(
                            f"{hz},{db - offset}\n" for (hz, db), (_, offset) in zip(measured, offsets, strict=False)
                        )
                    )
        except OSError as exc:
            self.status.setText(f"Nie udało się przygotować danych dla AutoEq. {exc}")
            self.finish_fit()
            return
        self.output = work / "profile.json"
        self.status.setText("AutoEq oblicza osiem pasm dla MOONDROP Position…")
        self.cancel.show()
        self.preview_changed.emit()
        self.fit_cancelled = False
        self.fit_timer.start()
        python = DATA_DIR.parent / ".venvs/autoeq/bin/python"
        self.process.start(
            str(python if python.is_file() else Path(sys.executable)),
            [
                str(Path(__file__).with_name("eq_fit.py")),
                "-m",
                str(measurement),
                "-t",
                str(target),
                "-o",
                str(self.output),
                "--min-q",
                str(26 / 256),
            ],
        )
        self.update_actions()
        self.preview_changed.emit()

    def fit_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self.status.setText(f"Nie udało się uruchomić AutoEq. {self.process.errorString()}")
            self.finish_fit()

    def fit_timeout(self) -> None:
        self.fit_cancelled = True
        self.status.setText("AutoEq przekroczył limit czasu.")
        self.process.kill()

    def cancel_fit(self) -> None:
        self.fit_cancelled = True
        self.status.setText("Obliczenia przerwane.")
        self.process.kill()

    def fit_finished(self, code: int, _exit_status) -> None:
        stderr = bytes(self.process.readAllStandardError()).decode(errors="replace")
        self.process.readAllStandardOutput()
        if self.fit_cancelled:
            pass
        elif code != 0:
            message = next((line for line in reversed(stderr.splitlines()) if line.strip()), "")
            self.status.setText(f"AutoEq nie obliczył profilu. {message}")
        else:
            try:
                name = f"Position → {self.result_entry.name}"
                self.result = replace(
                    load_profile(self.output, name),
                    source=f"AutoEq · {self.result_entry.source}",
                    target_name=self.result_entry.name,
                    target_curve=self.target_curve,
                )
                meta = json.loads(self.output.read_text()).get("meta", {})
            except (OSError, ValueError, dac.HidError) as exc:
                self.status.setText(f"Nie udało się wczytać wyniku AutoEq. {exc}")
            else:
                baseline = meta.get("pre_eq_error_rms_db")
                error = meta.get("predicted_error_rms_db")
                if baseline is not None and error is not None:
                    self.result_details = f"Błąd RMS: {baseline:.2f} → {error:.2f} dB"
                if self.fit_factory is None:
                    self.result_details += "\nDopasowanie zakłada neutralne EQ fabryczne."
                self.status.setText("Profil gotowy do wgrania lub zapisania na później.")
        self.finish_fit()

    @staticmethod
    def level_at_1khz(curve: list[tuple[float, float]]) -> float:
        index = bisect_left(curve, (1000, float("-inf")))
        low_hz, low_db = curve[index - 1]
        high_hz, high_db = curve[index]
        weight = math.log(1000 / low_hz) / math.log(high_hz / low_hz)
        return low_db + weight * (high_db - low_db)

    def finish_fit(self) -> None:
        self.fit_timer.stop()
        self.cancel.hide()
        if self.temporary is not None:
            self.temporary.cleanup()
            self.temporary = None
        self.update_actions()
        self.preview_changed.emit()

    def reset_preview(self) -> None:
        self.result_entry = None
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.cancel_fit()
        self.targets.setCurrentIndex(QModelIndex())
        self.target_changed()
        self.status.setText("Fabryczny EQ jest aktywny. Wybierz cel, aby obliczyć nowy profil.")

    def shutdown(self) -> None:
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.cancel_fit()
            self.process.waitForFinished(1000)


class ProfilesWindow(QWidget):
    def __init__(self, demo: bool, library_directory: Path | None = None):
        super().__init__()
        self.setWindowTitle("MOONDROP Position")
        self.setStyleSheet(APP_STYLE)
        self.setMinimumSize(820, 640)
        self.resize(1040, 760)
        app_data = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        self.library_directory = library_directory or Path(app_data) / ("profiles-demo" if demo else "profiles")
        self.settings_path = self.library_directory.parent / "settings.json"
        lang_pref = i18n.load_language_preference(self.settings_path)
        i18n.set_language(lang_pref, locale_name=QLocale.system().name())
        self.theme_pref = load_theme_preference(self.settings_path)
        app_instance = QApplication.instance()
        self.system_dark = (
            app_instance.styleHints().colorScheme() == Qt.ColorScheme.Dark if app_instance is not None else False
        )
        self.apply_theme(self.theme_pref)
        if app_instance is not None:
            app_instance.styleHints().colorSchemeChanged.connect(self.on_system_scheme_changed)

        self.demo = demo
        self.demo_forced_rate = 0
        demo_device = DemoDevice() if demo else None
        self.open_device = (lambda _path=None: demo_device) if demo else open_position
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.job = None
        self.command_active = False
        self.editor_active = False
        self.pending_command = None
        self.state = None
        self.last_applied_profile = None
        self.readback_profile = None
        self.factory_profile = Profile("Fabryczny EQ", 0, list(POSITION_FACTORY_BANDS), 0.0)
        self.preview_sources = None
        self.tray = None
        self.allow_quit = False
        self.tray_notice_shown = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 14)
        layout.setSpacing(15)
        heading = QLabel("MOONDROP Position")
        font = heading.font()
        font.setPointSizeF(font.pointSizeF() * 1.55)
        font.setBold(True)
        heading.setFont(font)
        self.connection = QLabel(tr("status.demo") if demo else tr("status.searching"))
        self.connection.setTextFormat(Qt.TextFormat.PlainText)
        self.connection.setStyleSheet(STATUS_PILL_STYLE)
        self.help_button = QPushButton(tr("header.help"))
        self.help_button.setAccessibleName(tr("header.help"))
        self.help_button.clicked.connect(self.open_help_dialog)
        header = QHBoxLayout()
        header.addWidget(heading)
        header.addStretch()
        header.addWidget(self.connection)
        header.addWidget(self.help_button)
        layout.addLayout(header)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        layout.addWidget(self.tabs, 1)

        device_page = QWidget()
        device_layout = QVBoxLayout(device_page)
        device_layout.setContentsMargins(18, 16, 18, 16)
        device_layout.setSpacing(10)
        self.device_box = QGroupBox(tr("device.read_settings"))
        details = QGridLayout(self.device_box)
        details.setColumnStretch(1, 1)
        details.setColumnStretch(3, 1)
        self.active_slot = QLabel("—")
        self.active_profile = QLabel("—")
        self.preamp = QLabel("—")
        self.firmware = QLabel("—")
        self.global_gain = QLabel("—")
        self.mic_gain = QLabel("—")
        self.detail_labels: dict[str, QLabel] = {}
        for row, column, key, value in (
            (0, 0, "device.active_slot", self.active_slot),
            (0, 2, "device.firmware", self.firmware),
            (1, 0, "device.profile", self.active_profile),
            (1, 2, "device.preamp", self.preamp),
        ):
            value.setTextFormat(Qt.TextFormat.PlainText)
            lbl = QLabel(tr(key))
            self.detail_labels[key] = lbl
            details.addWidget(lbl, row, column)
            details.addWidget(value, row, column + 1)
        self.gains_box = QGroupBox(tr("device.gain_group"))
        gains_form = QFormLayout(self.gains_box)
        global_row = QHBoxLayout()
        global_row.addWidget(self.global_gain)
        self.global_gain_button = QPushButton(tr("device.adjust"))
        self.global_gain_button.setAccessibleName(tr("device.output_gain"))
        self.global_gain_button.setEnabled(False)
        global_row.addWidget(self.global_gain_button)
        global_row.addStretch()
        self.output_gain_label = QLabel(tr("device.output_gain"))
        gains_form.addRow(self.output_gain_label, global_row)
        microphone_row = QHBoxLayout()
        microphone_row.addWidget(self.mic_gain)
        self.mic_gain_button = QPushButton(tr("device.adjust"))
        self.mic_gain_button.setAccessibleName(tr("device.microphone"))
        self.mic_gain_button.setEnabled(False)
        microphone_row.addWidget(self.mic_gain_button)
        microphone_row.addStretch()
        self.mic_gain_label = QLabel(tr("device.microphone"))
        gains_form.addRow(self.mic_gain_label, microphone_row)
        self.backup_button = QPushButton(tr("device.export_dac"))
        self.backup_button.setEnabled(False)
        self.defaults_button = QPushButton(tr("device.factory_reset"))
        self.defaults_button.setEnabled(False)
        self.maintenance_box = QGroupBox(tr("device.backup_group"))
        device_actions = QHBoxLayout(self.maintenance_box)
        device_actions.addWidget(self.backup_button)
        device_actions.addWidget(self.defaults_button)
        device_actions.addStretch()

        self.playback_box = QGroupBox(tr("device.playback_group"))
        playback_form = QFormLayout(self.playback_box)
        self.playback_format = QLabel("—")
        self.playback_format.setTextFormat(Qt.TextFormat.PlainText)
        self.playback_rate = QLabel("—")
        self.playback_rate.setTextFormat(Qt.TextFormat.PlainText)
        self.playback_stream_label = QLabel(tr("device.active_stream"))
        self.playback_rate_label = QLabel(tr("device.sample_rate"))
        self.playback_force_label = QLabel(tr("device.force_rate"))
        playback_form.addRow(self.playback_stream_label, self.playback_format)
        playback_form.addRow(self.playback_rate_label, self.playback_rate)

        rate_row = QHBoxLayout()
        self.sample_rate_combo = QComboBox()
        self.sample_rate_combo.setAccessibleName(tr("device.force_rate"))
        self.sample_rate_combo.addItem(tr("device.rate_auto"), 0)
        for rate in UAC2_SAMPLE_RATES:
            self.sample_rate_combo.addItem(format_rate_khz(rate), rate)
        self.apply_rate_button = QPushButton(tr("device.apply"))
        self.apply_rate_button.setAccessibleName(tr("device.apply"))
        self.refresh_rate_button = QPushButton(tr("device.refresh"))
        self.refresh_rate_button.setAccessibleName(tr("device.refresh"))
        rate_row.addWidget(self.sample_rate_combo)
        rate_row.addWidget(self.apply_rate_button)
        rate_row.addWidget(self.refresh_rate_button)
        rate_row.addStretch()
        playback_form.addRow(self.playback_force_label, rate_row)

        modes_text = " · ".join(f"Alt {alt}: {fmt} ({bits})" for alt, fmt, bits in UAC2_PLAYBACK_MODES)
        self.playback_hint = QLabel(tr("device.playback_hint", modes=modes_text))
        self.playback_hint.setWordWrap(True)
        self.playback_hint.setTextFormat(Qt.TextFormat.PlainText)
        playback_form.addRow(self.playback_hint)

        self.language_box = QGroupBox(tr("device.language_group"))
        lang_form = QFormLayout(self.language_box)
        self.theme_label = QLabel(tr("device.theme_label"))
        self.theme_combo = QComboBox()
        self.theme_combo.setAccessibleName(tr("device.theme_label"))
        self.theme_combo.addItem(tr("device.theme_auto"), "auto")
        self.theme_combo.addItem(tr("device.theme_dark"), "dark")
        self.theme_combo.addItem(tr("device.theme_light"), "light")
        theme_idx = self.theme_combo.findData(self.theme_pref)
        if theme_idx >= 0:
            self.theme_combo.setCurrentIndex(theme_idx)
        self.theme_combo.currentIndexChanged.connect(self.change_theme)
        lang_form.addRow(self.theme_label, self.theme_combo)
        self.language_label = QLabel(tr("device.language_label"))
        self.language_combo = QComboBox()
        self.language_combo.setAccessibleName(tr("device.language_group"))
        self.language_combo.addItem(tr("device.language_auto"), "auto")
        for code, name in i18n.available_languages():
            self.language_combo.addItem(f"{name} ({code.upper()})", code)
        lang_idx = self.language_combo.findData(lang_pref)
        if lang_idx >= 0:
            self.language_combo.setCurrentIndex(lang_idx)
        self.language_combo.currentIndexChanged.connect(self.change_language)
        lang_form.addRow(self.language_label, self.language_combo)

        device_layout.addWidget(self.device_box)
        device_layout.addWidget(self.gains_box)
        device_layout.addWidget(self.playback_box)
        device_layout.addWidget(self.language_box)
        device_layout.addWidget(self.maintenance_box)
        device_layout.addStretch()

        device_scroll = QScrollArea()
        device_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        device_scroll.setWidgetResizable(True)
        device_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        device_scroll.setWidget(device_page)

        self.profile_page = QWidget()
        profile_layout = QVBoxLayout(self.profile_page)
        profile_layout.setContentsMargins(18, 16, 18, 16)
        profile_layout.setSpacing(12)
        library_split = QSplitter(Qt.Orientation.Horizontal)
        library_split.setChildrenCollapsible(False)
        source_panel = QWidget()
        source_layout = QVBoxLayout(source_panel)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.setSpacing(8)
        source_buttons = QHBoxLayout()
        source_buttons.setSpacing(0)
        self.source_group = QButtonGroup(self)
        for index, key in enumerate(("source.my_profiles", "source.autoeq_catalog")):
            button = QPushButton(tr(key))
            button.setCheckable(True)
            radius = (
                "border-top-right-radius: 0; border-bottom-right-radius: 0; border-right: none;"
                if index == 0
                else "border-top-left-radius: 0; border-bottom-left-radius: 0;"
            )
            button.setStyleSheet(f"{SEGMENT_BUTTON_STYLE} QPushButton {{ {radius} }}")
            button.setMinimumHeight(30)
            self.source_group.addButton(button, index)
            source_buttons.addWidget(button)
        self.source_group.button(0).setChecked(True)
        source_layout.addLayout(source_buttons)
        self.sources = QStackedWidget()
        source_layout.addWidget(self.sources, 1)

        library = QWidget()
        library_layout = QVBoxLayout(library)
        library_layout.setContentsMargins(0, 0, 0, 0)
        self.profile_search = search_field(tr("search.profiles_placeholder"), tr("search.profiles_a11y"))
        library_layout.addWidget(self.profile_search)
        self.profiles = QListWidget()
        self.profiles.setAccessibleName("Biblioteka profili EQ")
        self.profiles.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.profiles.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.profiles.setMinimumWidth(205)
        self.profiles.setMinimumHeight(162)
        self.user_heading = None
        self.add_library_heading("Wbudowane")
        self.factory_item = self.add_profile(Profile("Fabryczny EQ", 0, [], None))
        self.flat_item = self.add_profile(
            Profile(tr("profile.flat_bypass"), dac.CUSTOM_SLOT, default_custom_bands(), 0.0)
        )
        initial_profile = self.add_profile(load_profile(BUILTIN_PROFILE, "Harman In-Ear 2019"))
        library_layout.addWidget(self.profiles, 1)
        self.sources.addWidget(library)
        self.autoeq_panel = AutoEqPanel(self, self.library_directory.parent / "autoeq")
        self.sources.addWidget(self.autoeq_panel)
        library_split.addWidget(source_panel)
        preview_panel = QWidget()
        preview = QVBoxLayout(preview_panel)
        preview.setContentsMargins(12, 0, 4, 0)
        preview.setSpacing(6)
        self.preview_title = QLabel()
        self.preview_title.setTextFormat(Qt.TextFormat.PlainText)
        self.preview_title.setWordWrap(True)
        title_font = self.preview_title.font()
        title_font.setPointSizeF(title_font.pointSizeF() * 1.2)
        title_font.setBold(True)
        self.preview_title.setFont(title_font)
        preview.addWidget(self.preview_title)
        self.profile_info = QLabel()
        self.profile_info.setTextFormat(Qt.TextFormat.PlainText)
        self.profile_info.setWordWrap(True)
        self.profile_info.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        preview.addWidget(self.profile_info)
        self.fr_title_label = QLabel(tr("plot.fr_title"))
        preview.addWidget(self.fr_title_label)
        self.preview_plot = ResponsePlot(include_preamp=False)
        preview.addWidget(self.preview_plot, 2)
        self.preview_key = PlotKey(
            self.preview_plot,
            (
                tr("plot.key.selected"),
                "",
                tr("plot.key.measured"),
                tr("plot.key.target_default"),
            ),
        )
        self.preview_key.setFixedHeight(self.preview_key.fontMetrics().lineSpacing() * 3 + 10)
        preview.addWidget(self.preview_key)
        self.correction_title = QLabel("Korekcja EQ · dB")
        preview.addWidget(self.correction_title)
        self.correction_plot = ResponsePlot(correction=True)
        preview.addWidget(self.correction_plot, 1)
        self.plot_legend = QLabel()
        self.plot_legend.setTextFormat(Qt.TextFormat.PlainText)
        self.plot_legend.setWordWrap(True)
        self.plot_legend.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.plot_legend.setFixedHeight(self.plot_legend.fontMetrics().lineSpacing() * 3 + 8)
        preview.addWidget(self.plot_legend)
        preview_scroll = QScrollArea()
        preview_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        preview_scroll.setWidgetResizable(True)
        preview_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        preview_scroll.setWidget(preview_panel)
        library_split.addWidget(preview_scroll)
        source_panel.setMinimumWidth(315)
        library_split.setStretchFactor(0, 2)
        library_split.setStretchFactor(1, 4)
        library_split.setSizes([360, 640])
        profile_layout.addWidget(library_split, 1)
        divider = QWidget()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background: palette(mid);")
        profile_layout.addWidget(divider)
        actions = QHBoxLayout()
        self.library_actions = QWidget()
        library_actions = QHBoxLayout(self.library_actions)
        library_actions.setContentsMargins(0, 0, 0, 0)
        self.add_button = QToolButton()
        self.add_button.setText(tr("actions.add_profile"))
        self.add_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        add_menu = QMenu(self.add_button)
        self.new_profile_action = add_menu.addAction(tr("actions.new_empty"), lambda: self.edit_profile(new=True))
        self.import_profile_action = add_menu.addAction(tr("actions.import_profile"), self.import_profile)
        self.add_button.setMenu(add_menu)
        self.more_button = QToolButton()
        self.more_button.setText(tr("actions.more"))
        self.more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more_menu = QMenu(self.more_button)
        self.duplicate_action = more_menu.addAction(tr("actions.duplicate"), lambda: self.edit_profile(duplicate=True))
        self.export_action = more_menu.addAction(tr("actions.export_selected"), self.export_selected)
        more_menu.addSeparator()
        self.delete_action = more_menu.addAction(tr("actions.delete_profile"), self.delete_selected)
        self.more_button.setMenu(more_menu)
        self.edit_button = QPushButton(tr("actions.edit_eq"))
        self.apply_button = QPushButton(tr("actions.apply_dac"))
        self.apply_button.setStyleSheet(PRIMARY_ACTION_STYLE)
        self.apply_button.setMinimumWidth(125)
        self.apply_button.setMinimumHeight(32)
        self.apply_button.setEnabled(False)
        library_actions.addWidget(self.add_button)
        library_actions.addWidget(self.more_button)
        actions.addWidget(self.library_actions)
        actions.addWidget(self.autoeq_panel.generate)
        actions.addWidget(self.autoeq_panel.cancel)
        actions.addWidget(self.edit_button)
        actions.addStretch()
        self.save_fit_button = QPushButton(tr("actions.save_later"))
        actions.addWidget(self.save_fit_button)
        actions.addWidget(self.apply_button)
        profile_layout.addLayout(actions)
        self.tabs.addTab(self.profile_page, tr("tab.tuning"))
        self.tabs.addTab(device_scroll, tr("tab.device"))
        self.search_shortcut = QShortcut(QKeySequence.StandardKey.Find, self)
        self.search_shortcut.activated.connect(self.focus_search)
        self.import_shortcut = QShortcut(QKeySequence.StandardKey.Open, self)
        self.import_shortcut.activated.connect(self.import_profile)
        self.quit_shortcut = QShortcut(QKeySequence.StandardKey.Quit, self)
        self.quit_shortcut.activated.connect(self.quit_from_tray)
        self.feedback = QLabel("")
        self.feedback.setTextFormat(Qt.TextFormat.PlainText)
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)

        footer_widget = QWidget()
        footer_widget.setStyleSheet(FOOTER_BUTTON_STYLE)
        footer = QHBoxLayout(footer_widget)
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(6)
        self.author_button = QPushButton(tr("footer.author_label"))
        self.author_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.author_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(tr("footer.author_url"))))
        self.coffee_button = QPushButton(tr("footer.coffee"))
        self.coffee_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.coffee_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(tr("footer.coffee_url"))))
        self.report_button = QToolButton()
        self.report_button.setText(tr("footer.report"))
        self.report_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.report_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.report_menu = QMenu(self.report_button)
        self.report_bug_action = self.report_menu.addAction(
            tr("footer.report_bug"), lambda: self.open_github_issue("bug_report.yml")
        )
        self.report_feature_action = self.report_menu.addAction(
            tr("footer.report_feature"), lambda: self.open_github_issue("feature_request.yml")
        )
        self.report_menu.addSeparator()
        self.copy_diag_action = self.report_menu.addAction(tr("footer.copy_diag"), self.copy_diagnostic_info)
        self.report_button.setMenu(self.report_menu)
        footer.addWidget(self.author_button)
        footer.addStretch()
        footer.addWidget(self.coffee_button)
        footer.addWidget(self.report_button)
        layout.addWidget(footer_widget)
        self.apply_tooltips()

        self.load_library()
        self.profiles.currentItemChanged.connect(self.update_selection)
        self.profile_search.textChanged.connect(self.filter_profiles)
        self.source_group.idClicked.connect(self.switch_source)
        self.sources.currentChanged.connect(self.update_selection)
        self.autoeq_panel.preview_changed.connect(self.update_selection)
        self.save_fit_button.clicked.connect(self.save_fit)
        self.profiles.setCurrentItem(initial_profile)
        self.edit_button.clicked.connect(self.edit_profile)
        self.apply_button.clicked.connect(self.apply_selected)
        self.backup_button.clicked.connect(self.backup_custom)
        self.global_gain_button.clicked.connect(self.edit_global_gain)
        self.mic_gain_button.clicked.connect(self.edit_mic_gain)
        self.defaults_button.clicked.connect(self.confirm_defaults)
        self.apply_rate_button.clicked.connect(self.apply_playback_rate)
        self.refresh_rate_button.clicked.connect(self.refresh_playback_quality)
        self.refresh_playback_quality()
        self.timer = QTimer(self)
        self.timer.setInterval(2500)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.setup_tray()
        QTimer.singleShot(0, self.refresh)

    def switch_source(self, index: int) -> None:
        self.source_group.button(index).setChecked(True)
        self.sources.setCurrentIndex(index)

    def focus_search(self) -> None:
        self.tabs.setCurrentWidget(self.profile_page)
        search = self.autoeq_panel.search if self.catalog_selected() else self.profile_search
        search.setFocus()

    def catalog_selected(self) -> bool:
        return self.sources.currentWidget() is self.autoeq_panel

    def candidate_profile(self) -> Profile | None:
        return self.autoeq_panel.result if self.catalog_selected() else self.selected_profile()

    def filter_profiles(self, query: str) -> None:
        words = query.casefold().split()
        visible = []
        heading = None
        for index in range(self.profiles.count()):
            item = self.profiles.item(index)
            profile = item.data(PROFILE_ROLE)
            if profile is None:
                heading = item
                heading.setHidden(True)
                continue
            matches = all(word in profile.name.casefold() for word in words)
            item.setHidden(not matches)
            if matches and heading is not None:
                heading.setHidden(False)
                visible.append(item)
        current = self.profiles.currentItem()
        if current is None or current.isHidden():
            self.profiles.setCurrentItem(visible[0] if visible else None)
        self.update_selection()

    def change_language(self) -> None:
        code = self.language_combo.currentData() or "auto"
        i18n.save_language_preference(self.settings_path, code)
        i18n.set_language(code, locale_name=QLocale.system().name())
        self.retranslate_ui()

    def apply_theme(self, theme_pref: str) -> None:
        dark = self.system_dark if theme_pref == "auto" else (theme_pref == "dark")
        app_instance = QApplication.instance()
        if app_instance is not None:
            app_instance.setPalette(build_innovibe_palette(dark))
        self.setStyleSheet(APP_STYLE)
        if hasattr(self, "preview_plot"):
            self.preview_plot.update()
            self.correction_plot.update()
            self.preview_key.update()

    def change_theme(self) -> None:
        self.theme_pref = self.theme_combo.currentData() or "auto"
        save_theme_preference(self.settings_path, self.theme_pref)
        self.apply_theme(self.theme_pref)

    def on_system_scheme_changed(self, scheme: Qt.ColorScheme) -> None:
        self.system_dark = scheme == Qt.ColorScheme.Dark
        if self.theme_pref == "auto":
            self.apply_theme("auto")

    def apply_tooltips(self) -> None:
        self.connection.setToolTip(tr("tooltip.connection"))
        self.help_button.setToolTip(tr("header.help_tooltip"))
        self.source_group.button(0).setToolTip(tr("tooltip.source_my_profiles"))
        self.source_group.button(1).setToolTip(tr("tooltip.source_autoeq"))
        self.profile_search.setToolTip(tr("tooltip.profile_search"))
        self.profiles.setToolTip(tr("tooltip.profiles_list"))
        self.preview_plot.setToolTip(tr("tooltip.preview_plot"))
        self.correction_plot.setToolTip(tr("tooltip.correction_plot"))
        self.add_button.setToolTip(tr("tooltip.add_profile"))
        self.more_button.setToolTip(tr("tooltip.more_actions"))
        self.edit_button.setToolTip(tr("tooltip.edit_eq"))
        self.save_fit_button.setToolTip(tr("tooltip.save_later"))
        self.apply_button.setToolTip(tr("tooltip.apply_dac"))
        self.detail_labels["device.active_slot"].setToolTip(tr("tooltip.device_slot"))
        self.detail_labels["device.firmware"].setToolTip(tr("tooltip.device_firmware"))
        self.detail_labels["device.preamp"].setToolTip(tr("tooltip.device_preamp"))
        self.global_gain_button.setToolTip(tr("tooltip.output_gain"))
        self.mic_gain_button.setToolTip(tr("tooltip.mic_gain"))
        self.sample_rate_combo.setToolTip(tr("tooltip.sample_rate"))
        self.apply_rate_button.setToolTip(tr("tooltip.apply_rate"))
        self.refresh_rate_button.setToolTip(tr("tooltip.refresh_rate"))
        self.theme_combo.setToolTip(tr("tooltip.theme"))
        self.language_combo.setToolTip(tr("tooltip.language"))
        self.backup_button.setToolTip(tr("tooltip.export_dac"))
        self.defaults_button.setToolTip(tr("tooltip.factory_reset"))
        self.author_button.setToolTip(tr("footer.author_tooltip"))
        self.coffee_button.setToolTip(tr("footer.coffee_tooltip"))
        self.report_button.setToolTip(tr("footer.report_tooltip"))

    def open_help_dialog(self) -> None:
        AboutHelpDialog(self).exec()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        paint_innovibe_backdrop(self)

    def diagnostic_summary(self) -> str:
        lines = [
            f"OS: {platform.platform()}",
            f"Python: {platform.python_version()}",
            f"Mode: {'demo' if self.demo else 'hardware'}",
            f"Connection: {self.connection.text()}",
        ]
        if self.state is not None:
            slot_label = dac.SLOT_NAMES.get(self.state.slot, str(self.state.slot))
            lines.extend(
                [
                    f"Firmware: {self.state.firmware}",
                    f"Active slot: {self.state.slot} ({slot_label})",
                    f"Pre-gain: {self.state.preamp:+.2f} dB",
                    f"Global gain: {self.state.global_gain_db} dB",
                ]
            )
        if self.playback_format.text() != "—":
            lines.append(f"UAC2 stream: {self.playback_format.text()} @ {self.playback_rate.text()}")
        return "\n".join(lines)

    def copy_diagnostic_info(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.diagnostic_summary())
        self.feedback.setText(tr("footer.diag_copied"))

    def open_external_url(self, url: str) -> bool:
        opened = QDesktopServices.openUrl(QUrl(url))
        if not opened:
            opened = webbrowser.open(url)
        if opened:
            self.feedback.setText(tr("footer.opened_browser"))
        else:
            clipboard = QApplication.clipboard()
            if clipboard is not None:
                clipboard.setText(url)
            self.feedback.setText(tr("footer.open_failed", url=url))
        return opened

    def open_github_issue(self, template: str) -> None:
        params = {
            "template": template,
            "os": platform.platform(),
        }
        if template == "bug_report.yml":
            params["diagnostics"] = self.diagnostic_summary()
        url = f"{GITHUB_REPO_URL}/issues/new?{urlencode(params, quote_via=quote)}"
        self.open_external_url(url)

    def retranslate_ui(self) -> None:
        self.setWindowTitle(tr("app.title"))
        self.help_button.setText(tr("header.help"))
        self.help_button.setAccessibleName(tr("header.help"))
        self.author_button.setText(tr("footer.author_label"))
        self.coffee_button.setText(tr("footer.coffee"))
        self.report_button.setText(tr("footer.report"))
        self.report_bug_action.setText(tr("footer.report_bug"))
        self.report_feature_action.setText(tr("footer.report_feature"))
        self.copy_diag_action.setText(tr("footer.copy_diag"))
        self.tabs.setTabText(0, tr("tab.tuning"))
        self.tabs.setTabText(1, tr("tab.device"))
        self.device_box.setTitle(tr("device.read_settings"))
        for key, lbl in self.detail_labels.items():
            lbl.setText(tr(key))
        self.gains_box.setTitle(tr("device.gain_group"))
        self.output_gain_label.setText(tr("device.output_gain"))
        self.mic_gain_label.setText(tr("device.microphone"))
        self.global_gain_button.setText(tr("device.adjust"))
        self.mic_gain_button.setText(tr("device.adjust"))
        self.playback_box.setTitle(tr("device.playback_group"))
        self.playback_stream_label.setText(tr("device.active_stream"))
        self.playback_rate_label.setText(tr("device.sample_rate"))
        self.playback_force_label.setText(tr("device.force_rate"))
        self.sample_rate_combo.setItemText(0, tr("device.rate_auto"))
        self.apply_rate_button.setText(tr("device.apply"))
        self.refresh_rate_button.setText(tr("device.refresh"))
        modes_text = " · ".join(f"Alt {alt}: {fmt} ({bits})" for alt, fmt, bits in UAC2_PLAYBACK_MODES)
        self.playback_hint.setText(tr("device.playback_hint", modes=modes_text))
        self.language_box.setTitle(tr("device.language_group"))
        self.theme_label.setText(tr("device.theme_label"))
        self.theme_combo.setAccessibleName(tr("device.theme_label"))
        self.theme_combo.setItemText(0, tr("device.theme_auto"))
        self.theme_combo.setItemText(1, tr("device.theme_dark"))
        self.theme_combo.setItemText(2, tr("device.theme_light"))
        self.language_label.setText(tr("device.language_label"))
        self.language_combo.setItemText(0, tr("device.language_auto"))
        self.maintenance_box.setTitle(tr("device.backup_group"))
        self.backup_button.setText(tr("device.export_dac"))
        self.defaults_button.setText(tr("device.factory_reset"))
        for index, key in enumerate(("source.my_profiles", "source.autoeq_catalog")):
            self.source_group.button(index).setText(tr(key))
        self.profile_search.setPlaceholderText(tr("search.profiles_placeholder"))
        self.profile_search.setAccessibleName(tr("search.profiles_a11y"))
        self.fr_title_label.setText(tr("plot.fr_title"))
        self.add_button.setText(tr("actions.add_profile"))
        self.new_profile_action.setText(tr("actions.new_empty"))
        self.import_profile_action.setText(tr("actions.import_profile"))
        self.more_button.setText(tr("actions.more"))
        self.duplicate_action.setText(tr("actions.duplicate"))
        self.export_action.setText(tr("actions.export_selected"))
        self.delete_action.setText(tr("actions.delete_profile"))
        self.edit_button.setText(tr("actions.edit_eq"))
        self.apply_button.setText(tr("actions.apply_dac"))
        self.autoeq_panel.retranslate_ui()
        self.apply_tooltips()
        flat_profile = self.flat_item.data(PROFILE_ROLE)
        if flat_profile is not None:
            self.flat_item.setData(PROFILE_ROLE, replace(flat_profile, name=tr("profile.flat_bypass")))
            self.flat_item.setText(tr("profile.flat_bypass"))
            self.flat_item.setToolTip(tr("profile.flat_bypass"))
        self.preview_sources = None
        self.update_selection()
        self.render_state()
        self.refresh_playback_quality()

    def setup_tray(self) -> None:
        icon_file = Path(__file__).resolve().parents[1] / "flatpak/local.moondrop.Position.svg"
        fallback = QIcon(str(icon_file))
        if fallback.isNull():
            fallback = self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume)
        self.tray = QSystemTrayIcon(QIcon.fromTheme("local.moondrop.Position", fallback), self)
        self.tray_menu = QMenu(self)
        self.tray_menu.aboutToShow.connect(self.populate_tray)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(self.tray_activated)
        self.tray.setToolTip("MOONDROP Position")
        self.tray.show()

    def open_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.open_window()

    def populate_tray(self) -> None:
        menu = self.tray_menu
        menu.clear()
        status = self.active_profile.text() if self.state else self.connection.text()
        menu.addAction(status).setEnabled(False)
        if self.isVisible():
            menu.addAction(tr("tray.hide"), self.hide)
        else:
            menu.addAction(tr("tray.show"), self.open_window)
        profiles_menu = menu.addMenu(tr("tray.apply_menu"))
        profiles_menu.setEnabled(self.state is not None and not self.command_active and not self.editor_active)
        for item in self.profile_items():
            profile = item.data(PROFILE_ROLE)
            action = profiles_menu.addAction(profile.name)
            action.setEnabled(self.state is not None and not profile.matches(self.state))
            action.triggered.connect(lambda _checked, item=item: self.apply_from_tray(item))
        reset = menu.addAction(tr("device.factory_reset"), self.confirm_defaults)
        reset.setEnabled(self.defaults_button.isEnabled())
        menu.addSeparator()
        menu.addAction(tr("tray.quit"), self.quit_from_tray).setEnabled(not self.editor_active)

    def quit_from_tray(self) -> None:
        if self.editor_active:
            return
        self.allow_quit = True
        self.close()
        QApplication.quit()

    def apply_from_tray(self, item: QListWidgetItem) -> None:
        self.profiles.setCurrentItem(item)
        self.apply_candidate(item.data(PROFILE_ROLE))

    def add_library_heading(self, title: str) -> QListWidgetItem:
        item = QListWidgetItem(title)
        font = self.profiles.font()
        font.setBold(True)
        item.setFont(font)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.profiles.addItem(item)
        return item

    def add_profile(self, profile: Profile, path: Path | None = None) -> QListWidgetItem:
        if path is not None and self.user_heading is None:
            self.user_heading = self.add_library_heading("Moje profile")
        item = QListWidgetItem(profile.name)
        item.setToolTip(profile.name)
        size = item.sizeHint()
        size.setHeight(max(28, self.profiles.fontMetrics().height() + 12))
        item.setSizeHint(size)
        item.setData(PROFILE_ROLE, profile)
        if path is not None:
            item.setData(PATH_ROLE, str(path))
        self.profiles.addItem(item)
        return item

    def load_library(self) -> None:
        failures = []
        saved = []
        for path in self.library_directory.glob("*.json"):
            try:
                saved.append((load_profile(path), path))
            except (OSError, ValueError, dac.HidError):
                failures.append(path.name)
        for profile, path in sorted(saved, key=lambda entry: entry[0].name.casefold()):
            self.add_profile(profile, path)
        if failures:
            self.feedback.setText(f"Nie udało się otworzyć {len(failures)} zapisanych profili.")

    def persist_profile(self, profile: Profile, item: QListWidgetItem | None = None) -> bool:
        path = item.data(PATH_ROLE) if item else None
        try:
            self.library_directory.mkdir(parents=True, exist_ok=True)
            destination = Path(path) if path else self.library_directory / f"{uuid4().hex}.json"
            save_profile(str(destination), profile)
        except OSError as exc:
            self.feedback.setText(f"Nie udało się zapisać profilu. {exc}")
            return False
        if path:
            item.setData(PROFILE_ROLE, profile)
        else:
            item = self.add_profile(profile, destination)
        if self.profile_search.text():
            self.profile_search.clear()
        self.profiles.setCurrentItem(item)
        self.update_selection()
        self.render_state()
        return True

    def selected_profile(self) -> Profile | None:
        item = self.profiles.currentItem()
        return item.data(PROFILE_ROLE) if item else None

    def profile_items(self) -> list[QListWidgetItem]:
        return [
            item
            for index in range(self.profiles.count())
            if (item := self.profiles.item(index)).data(PROFILE_ROLE) is not None
        ]

    def update_selection(self) -> None:
        using_catalog = self.catalog_selected()
        profile = self.candidate_profile()
        busy_fit = (
            self.autoeq_panel.job is not None or self.autoeq_panel.process.state() != QProcess.ProcessState.NotRunning
        )
        self.library_actions.setVisible(not using_catalog)
        self.autoeq_panel.generate.setVisible(using_catalog and not busy_fit)
        self.autoeq_panel.cancel.setVisible(using_catalog and busy_fit)
        self.edit_button.setVisible(not using_catalog or profile is not None)
        self.save_fit_button.setVisible(using_catalog and profile is not None)
        if using_catalog and profile is None:
            entry = self.autoeq_panel.current_entry()
            self.preview_title.setText(entry.name if entry else "Wybierz cel AutoEq")
            self.profile_info.setText(entry.source if entry else "")
        else:
            self.preview_title.setText(profile.name if profile else "Brak profili pasujących do wyszukiwania")
        if profile is not None and profile.slot == dac.CUSTOM_SLOT:
            context = f"{len(profile.bands)} pasm · pre-gain {profile.preamp:+.2f} dB"
            if profile.source:
                context += f" · {profile.source}"
            self.profile_info.setText(context)
        elif not using_catalog:
            self.profile_info.setText("Wybrano fabryczny EQ" if profile else "")
        self.update_comparison()
        self.refresh_buttons()

    def update_comparison(self) -> None:
        selected = self.candidate_profile()
        details = self.autoeq_panel.result_details if self.catalog_selected() else ""
        sources = (selected, self.readback_profile, self.factory_profile, self.state, details)
        if sources == self.preview_sources:
            return
        self.preview_sources = sources
        measured = self.preview_plot.factory_points
        target_points = []
        if selected and selected.target_curve and measured:
            level_at_1khz = self.autoeq_panel.level_at_1khz
            shift = level_at_1khz(measured) - level_at_1khz(selected.target_curve)
            target_points = [(hz, db + shift) for hz, db in selected.target_curve]
        target_label = selected.target_name if selected and selected.target_name else tr("plot.key.target_default")
        self.preview_key.labels = (
            selected.name if selected else tr("plot.key.selected"),
            "",
            tr("plot.key.measured"),
            tr("plot.key.target", name=target_label),
        )
        self.preview_plot.set_factory(self.factory_profile)
        self.preview_plot.set_profile(selected)
        self.preview_plot.set_target_points(target_points)

        waiting_for_fit = self.catalog_selected() and selected is None
        from_device = (
            (not waiting_for_fit)
            and self.readback_profile is not None
            and (selected is None or (self.state is not None and selected.matches_eq(self.state)))
        )
        correction = None if waiting_for_fit else (self.readback_profile if from_device else selected)
        self.correction_title.setText(
            tr("plot.eq_waiting") if waiting_for_fit else tr("plot.eq_dac") if from_device else tr("plot.eq_preview")
        )
        frequencies = self.preview_plot.frequencies
        correction_points = []
        if correction is not None:
            if correction.slot == 0 and not from_device:
                correction_points = [(hz, 0.0) for hz in frequencies]
            else:
                correction_points = response_points(correction, frequencies)
                if self.factory_profile is not None:
                    factory = response_points(self.factory_profile, frequencies)
                    correction_points = [
                        (hz, db - baseline) for (hz, db), (_, baseline) in zip(correction_points, factory, strict=False)
                    ]
        self.correction_plot.set_primary_points(correction_points)

        notes = []
        if details:
            notes.extend(details.splitlines())
        if selected and selected.slot == dac.CUSTOM_SLOT and not selected.target_curve:
            notes.append("Ten profil nie zawiera krzywej docelowej.")
        if self.factory_profile is None and correction is not None and correction.slot != 0:
            notes.append("Podgląd korekcji zakłada neutralne EQ slotu fabrycznego.")
        if measured:
            notes.append(tr("plot.measurement_note"))
        self.plot_legend.setText("\n".join(notes))
        plot_description = list(self.preview_key.labels[2 : 4 if target_points else 3])
        self.preview_plot.setAccessibleDescription("\n".join(plot_description + notes))

    def render_state(self, error: str = "") -> None:
        state = self.state
        items = self.profile_items()
        matches = [item for item in items if state is not None and item.data(PROFILE_ROLE).matches(state)]

        def match_priority(item: QListWidgetItem) -> int:
            profile = item.data(PROFILE_ROLE)
            return sum(value is not None for value in (profile.global_gain_db, profile.mic_gain_raw))

        preferred = self.last_applied_profile
        if state is not None and preferred is not None and preferred.matches(state):
            active = next((item for item in matches if item.data(PROFILE_ROLE) == preferred), None)
            active_name = preferred.name
        else:
            active = max(matches, key=match_priority, default=None)
            active_name = active.data(PROFILE_ROLE).name if active else "Własne ustawienia"
        for item in items:
            name = item.data(PROFILE_ROLE).name
            label = f"{name} · aktywny" if item is active else name
            if item.text() != label:
                item.setText(label)
        if state is None:
            self.connection.setText(error.split("\n\n", 1)[0] if error else "Podłącz MOONDROP Position.")
            if self.tray:
                self.tray.setToolTip(f"MOONDROP Position · {self.connection.text()}")
            for label in (
                self.active_slot,
                self.active_profile,
                self.preamp,
                self.firmware,
                self.global_gain,
                self.mic_gain,
            ):
                label.setText("—")
            return
        self.connection.setText(tr("status.demo") if state.path == "demo" else tr("status.connected"))
        slot_name = {0: "Fabryczny EQ", dac.CUSTOM_SLOT: "Własny EQ"}.get(state.slot)
        self.active_slot.setText(f"{state.slot} · {slot_name}" if slot_name else str(state.slot))
        self.active_profile.setText(active_name)
        if self.tray:
            self.tray.setToolTip(f"MOONDROP Position · {self.active_profile.text()}")
        self.preamp.setText(f"{state.preamp:+.2f} dB")
        self.global_gain.setText("—" if state.global_gain_db is None else f"{state.global_gain_db} dB")
        self.mic_gain.setText("—" if state.mic_gain_raw is None else mic_gain_label(state.mic_gain_raw))
        self.firmware.setText(state.firmware)

    def refresh_buttons(self) -> None:
        profile = self.candidate_profile()
        self.apply_button.setEnabled(
            not self.command_active
            and self.state is not None
            and profile is not None
            and not profile.matches(self.state)
        )
        custom_selected = profile is not None and profile.slot == dac.CUSTOM_SLOT
        saved = (
            self.catalog_selected()
            and profile is not None
            and any(item.data(PATH_ROLE) and item.data(PROFILE_ROLE) == profile for item in self.profile_items())
        )
        self.save_fit_button.setText(tr("actions.saved") if saved else tr("actions.save_later"))
        self.save_fit_button.setEnabled(self.catalog_selected() and profile is not None and not saved)
        self.edit_button.setEnabled(profile is not None and not self.command_active)
        self.duplicate_action.setEnabled(custom_selected)
        self.export_action.setEnabled(custom_selected)
        item = self.profiles.currentItem()
        self.delete_action.setEnabled(
            not self.catalog_selected() and item is not None and not item.isHidden() and bool(item.data(PATH_ROLE))
        )
        self.backup_button.setEnabled(
            not self.command_active and self.state is not None and self.state.slot == dac.CUSTOM_SLOT
        )
        self.global_gain_button.setEnabled(
            not self.command_active
            and self.state is not None
            and self.state.global_gain_db is not None
            and -18 <= self.state.global_gain_db <= 0
        )
        self.mic_gain_button.setEnabled(
            not self.command_active and self.state is not None and self.state.mic_gain_raw is not None
        )
        self.defaults_button.setEnabled(
            not self.command_active
            and self.state is not None
            and self.state.global_gain_db is not None
            and (
                self.state.slot != 0
                or self.state.preamp != 0
                or self.state.global_gain_db != 0
                or self.state.mic_gain_raw not in (None, 0)
            )
        )

    def start(self, operation, finished, *, background: bool = False) -> None:
        if self.command_active or (background and self.job is not None):
            return
        if not background:
            self.command_active = True
            self.refresh_buttons()
        if self.job is not None:
            self.pending_command = (operation, finished)
            return
        self.launch(operation, finished, background=background)

    def launch(self, operation, finished, *, background: bool) -> None:
        self.job_finished = finished
        self.job_is_background = background
        self.job = Job(operation)
        self.job.signals.finished.connect(self.job_done)
        self.pool.start(self.job)

    def job_done(self, result, error: str) -> None:
        finished = self.job_finished
        self.job = None
        if not self.job_is_background:
            self.command_active = False
        finished(result, error)
        if self.pending_command is not None:
            operation, finished = self.pending_command
            self.pending_command = None
            self.launch(operation, finished, background=False)

    def refresh(self) -> None:
        self.start(lambda: poll_device(self.open_device), self.refresh_done, background=True)

    def refresh_done(self, state, error: str) -> None:
        if (
            self.state is None
            or state is None
            or (self.state.path, self.state.firmware) != (state.path, state.firmware)
        ):
            self.factory_profile = Profile("Fabryczny EQ", 0, list(POSITION_FACTORY_BANDS), 0.0)
            self.last_applied_profile = None
        self.state = state
        self.readback_profile = profile_from_readback(state) if state is not None else None
        if self.readback_profile is not None and state.slot == 0:
            self.factory_profile = replace(self.readback_profile, preamp=0)
        self.update_comparison()
        self.render_state(error)
        self.refresh_buttons()
        self.refresh_playback_quality()

    def refresh_playback_quality(self) -> None:
        quality = read_playback_quality(demo=self.demo, demo_forced_rate=self.demo_forced_rate)
        if quality.altset is not None and quality.audio_format:
            ch = f"{quality.channels} ch (FL, FR)" if quality.channels == 2 else f"{quality.channels or 2} ch"
            status = tr("device.stream_running") if quality.running else tr("device.stream_ready")
            self.playback_format.setText(f"Alt {quality.altset} · {quality.audio_format} · {ch} ({status})")
        else:
            missing = tr("device.stream_missing") if not quality.pipewire_available else tr("device.stream_waiting")
            self.playback_format.setText(missing)

        if quality.rate_hz:
            mode = "wymuszone" if quality.forced_rate_hz else "Auto PipeWire"
            self.playback_rate.setText(f"{format_rate_khz(quality.rate_hz)} ({mode}, {quality.source})")
        else:
            self.playback_rate.setText("—")

        target_rate = quality.forced_rate_hz if quality.forced_rate_hz is not None else 0
        index = self.sample_rate_combo.findData(target_rate)
        if index >= 0 and self.sample_rate_combo.currentIndex() != index:
            self.sample_rate_combo.setCurrentIndex(index)
        self.apply_rate_button.setEnabled(quality.pipewire_available)

    def apply_playback_rate(self) -> None:
        rate_hz = self.sample_rate_combo.currentData()
        if rate_hz is None:
            return
        if self.demo:
            self.demo_forced_rate = int(rate_hz)
            self.refresh_playback_quality()
            label = "Automatyczna (PipeWire)" if rate_hz == 0 else format_rate_khz(rate_hz)
            self.feedback.setText(f"[Symulator] Ustawiono częstotliwość próbkowania: {label}.")
            return
        try:
            confirmed = apply_pipewire_sample_rate(int(rate_hz))
        except (ValueError, RuntimeError) as exc:
            self.feedback.setText(f"Nie zmieniono częstotliwości próbkowania. {exc}")
            return
        self.refresh_playback_quality()
        label = "Automatyczna (PipeWire)" if confirmed == 0 else format_rate_khz(confirmed)
        self.feedback.setText(f"PipeWire potwierdził częstotliwość próbkowania: {label}.")

    def import_profile(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self, "Importuj profil EQ", "", "Profile EQ (*.json *.txt);;JSON (*.json);;Equalizer APO (*.txt)"
        )
        if not path:
            return
        try:
            source = Path(path)
            if source.suffix.casefold() == ".txt":
                bands, preamp = dac.parse_eqapo(path)
                for index in range(len(bands), dac.BAND_COUNT):
                    bands.append({"band": index + 1, "type": "PK", "freq": 1000, "q": 1, "gain": 0})
                profile = custom_profile(source.stem, dac.CUSTOM_SLOT, bands, 0 if preamp is None else preamp)
            else:
                profile = load_profile(source)
        except (OSError, ValueError, dac.HidError, SystemExit) as exc:
            self.feedback.setText(f"Błąd profilu. {exc}")
            return
        if self.persist_profile(profile):
            self.tabs.setCurrentWidget(self.profile_page)
            self.switch_source(0)
            self.feedback.setText("Profil został dodany do biblioteki.")

    def save_fit(self) -> None:
        profile = self.autoeq_panel.result
        if self.save_fit_button.isEnabled() and profile is not None and self.persist_profile(profile):
            self.feedback.setText("Profil zapisany w Moich profilach.")

    def export_selected(self) -> None:
        profile = self.selected_profile()
        if profile is None or profile.slot != dac.CUSTOM_SLOT:
            return
        filename = profile.name.replace("/", "_") + ".json"
        path, _ = QFileDialog.getSaveFileName(self, "Eksportuj profil", filename, "Profile JSON (*.json)")
        if path:
            try:
                save_profile(path, profile)
            except OSError as exc:
                self.feedback.setText(f"Błąd eksportu profilu. {exc}")
            else:
                self.feedback.setText("Profil zapisany do pliku JSON.")

    def delete_selected(self) -> None:
        item = self.profiles.currentItem()
        if item is None or item.isHidden() or self.catalog_selected() or not item.data(PATH_ROLE):
            return
        path = Path(item.data(PATH_ROLE))
        profile = item.data(PROFILE_ROLE)
        box = QMessageBox(self)
        box.setWindowTitle("Usuń profil")
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(f"Usunąć „{profile.name}” z Moich profili?")
        remove = box.addButton("Usuń profil", QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton("Anuluj", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.setEscapeButton(cancel)
        box.exec()
        if box.clickedButton() is not remove:
            return
        try:
            if path.parent.resolve() != self.library_directory.resolve():
                raise OSError("Plik znajduje się poza katalogiem Moje profile.")
            path.unlink(missing_ok=True)
        except OSError as exc:
            self.feedback.setText(f"Nie udało się usunąć profilu. {exc}")
            return
        active = self.state is not None and profile.matches(self.state)
        self.profiles.takeItem(self.profiles.row(item))
        if self.user_heading is not None and not any(entry.data(PATH_ROLE) for entry in self.profile_items()):
            self.profiles.takeItem(self.profiles.row(self.user_heading))
            self.user_heading = None
        self.render_state()
        self.update_selection()
        self.feedback.setText("Profil usunięty. EQ pozostaje aktywny w DAC-u." if active else "Profil usunięty.")

    def edit_profile(self, *, duplicate: bool = False, new: bool = False) -> None:
        if self.command_active or self.editor_active:
            return
        selected = None if new else self.candidate_profile()
        item = None if new or self.catalog_selected() else self.profiles.currentItem()
        source = selected if selected is not None and selected.slot == dac.CUSTOM_SLOT else None
        if source is not None and (duplicate or (item is not None and not item.data(PATH_ROLE))):
            source = replace(source, name=f"{source.name} – kopia")
        current = None
        state = self.state
        if state is not None and state.slot == dac.CUSTOM_SLOT and all(state.bands):
            with contextlib.suppress(dac.HidError, ValueError):
                current = custom_profile(
                    "Aktualny Custom",
                    state.slot,
                    state.bands,
                    state.preamp,
                    state.global_gain_db,
                    state.mic_gain_raw if state.mic_gain_raw in MIC_GAIN_REQUESTS else None,
                )
        editor = EqualizerDialog(
            self, source, current, self.factory_profile, device_path=state.path if state is not None else None
        )
        self.editor_active = True
        self.timer.stop()
        try:
            result = editor.exec()
        finally:
            self.editor_active = False
            self.timer.start()
        if result == QDialog.DialogCode.Accepted and editor.result_profile is not None:
            if editor.result_apply:
                self.apply_candidate(editor.result_profile)
            elif self.persist_profile(editor.result_profile, None if duplicate else item):
                self.feedback.setText("Profil zapisany w bibliotece.")
        editor.deleteLater()
        self.refresh()

    def apply_selected(self) -> None:
        self.apply_candidate(self.candidate_profile())

    def apply_candidate(self, profile: Profile | None) -> None:
        if self.state is None or self.command_active or self.editor_active or profile is None:
            return
        path = self.state.path
        self.requested_profile = profile
        self.feedback.setText("Stosuję profil i sprawdzam odczyt…")
        self.start(lambda: apply_profile(self.open_device, path, profile), self.apply_done)

    def edit_global_gain(self) -> None:
        state = self.state
        if state is None or state.global_gain_db is None or self.command_active:
            return
        self.timer.stop()
        try:
            target, accepted = QInputDialog.getInt(
                self,
                "Global gain",
                "Global gain (dB), zastosowanie tymczasowe",
                state.global_gain_db,
                -18,
                0,
                1,
            )
        finally:
            self.timer.start()
        if accepted and target != state.global_gain_db:
            self.feedback.setText("Ustawiam global gain…")
            self.start(lambda: update_global_gain(self.open_device, state.path, target), self.global_gain_done)

    def global_gain_done(self, state, error: str) -> None:
        self.refresh_done(state, error)
        self.feedback.setText(
            f"Zmiana global gainu niepotwierdzona. {error}"
            if error
            else f"Global gain potwierdzony odczytem: {state.global_gain_db} dB."
        )

    def edit_mic_gain(self) -> None:
        if not self.mic_gain_button.isEnabled():
            return
        state = self.state
        values = tuple(MIC_GAIN_REQUESTS)
        dialog = QDialog(self)
        dialog.setWindowTitle("Wzmocnienie mikrofonu")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"Bieżący odczyt: {mic_gain_label(state.mic_gain_raw)}"))
        slider = QSlider(Qt.Orientation.Horizontal, dialog)
        slider.setAccessibleName("Wzmocnienie mikrofonu")
        slider.setRange(0, len(values) - 1)
        slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        slider.setTickInterval(1)
        slider.setMinimumWidth(265)
        slider.setValue(min(range(len(values)), key=lambda index: abs(values[index] - state.mic_gain_raw)))
        layout.addWidget(slider)
        endpoints = QHBoxLayout()
        endpoints.addWidget(QLabel(mic_gain_label(values[0])))
        endpoints.addStretch()
        endpoints.addWidget(QLabel(mic_gain_label(values[-1])))
        layout.addLayout(endpoints)
        target_label = QLabel()
        slider.valueChanged.connect(lambda index: target_label.setText(f"Ustaw: {mic_gain_label(values[index])}"))
        target_label.setText(f"Ustaw: {mic_gain_label(values[slider.value()])}")
        layout.addWidget(target_label)
        buttons = QDialogButtonBox()
        buttons.addButton("Ustaw", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Anuluj", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            target = values[slider.value()]
            self.feedback.setText("Ustawiam wzmocnienie mikrofonu…")
            self.start(lambda: update_mic_gain(self.open_device, state.path, target), self.mic_gain_done)

    def mic_gain_done(self, state, error: str) -> None:
        self.refresh_done(state, error)
        self.feedback.setText(
            f"Zmiana mikrofonu niepotwierdzona. {error}"
            if error
            else f"Wzmocnienie mikrofonu potwierdzone: {mic_gain_label(state.mic_gain_raw)}."
        )

    def backup_custom(self) -> None:
        if self.state is None or self.command_active or self.state.slot != dac.CUSTOM_SLOT:
            return
        path = self.state.path
        self.feedback.setText("Odczytuję i sprawdzam ustawienia EQ na DAC-u…")
        self.start(lambda: read_custom_backup(self.open_device, path), self.backup_done)

    def backup_done(self, profile: Profile | None, error: str) -> None:
        self.refresh_buttons()
        if profile is None:
            self.feedback.setText(f"Nie udało się odczytać kopii. {error}")
            return
        path, _selected_filter = QFileDialog.getSaveFileName(
            self, "Eksportuj EQ z DAC-a", f"{profile.name}.json", "Profile JSON (*.json)"
        )
        if not path:
            self.feedback.clear()
            return
        try:
            save_profile(path, profile)
        except OSError as exc:
            self.feedback.setText(f"Błąd zapisu kopii. {exc}")
            return
        self.feedback.setText("EQ zapisany do pliku JSON. Aby użyć go ponownie, wybierz „Importuj JSON…”.")

    def apply_done(self, state, error: str) -> None:
        if not error:
            self.last_applied_profile = self.requested_profile
        self.refresh_done(state, error)
        if error:
            self.feedback.setText(f"Zapis niepotwierdzony. {error}")
        else:
            message = f"DAC potwierdził wgranie: {self.active_profile.text()}."
            requested_preamp = self.requested_profile.preamp
            if requested_preamp is not None and not dac.preamp_matches(state.preamp, requested_preamp):
                message += f" Pre-gain DAC-a {state.preamp:+.2f} dB (profil {requested_preamp:+.2f} dB)."
            self.feedback.setText(message)

    def confirm_defaults(self) -> None:
        if self.editor_active or not self.defaults_button.isEnabled():
            return
        path = self.state.path
        self.open_window()
        box = QMessageBox(self)
        box.setWindowTitle("Ustawienia fabryczne")
        box.setText("Przełączyć na fabryczny EQ i ustawić wzmocnienia na 0 dB?")
        gains = "pre-gain, global gain"
        if self.state.mic_gain_raw is not None:
            gains += " i wzmocnienie mikrofonu"
        box.setInformativeText(f"Zakres potwierdzony na Position: fabryczny EQ, {gains}.")
        restore = box.addButton("Przywróć", QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton("Anuluj", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        if box.clickedButton() is restore:
            self.feedback.setText("Przywracam ustawienia domyślne…")
            self.start(lambda: restore_defaults(self.open_device, path), self.defaults_done)

    def defaults_done(self, state, error: str) -> None:
        self.refresh_done(state, error)
        if error:
            self.feedback.setText(f"Nie potwierdzono ustawień domyślnych. {error}")
            return
        self.last_applied_profile = self.factory_item.data(PROFILE_ROLE)
        self.profile_search.clear()
        self.profiles.setCurrentItem(self.factory_item)
        self.autoeq_panel.reset_preview()
        self.switch_source(0)
        self.feedback.setText("DAC potwierdził fabryczny EQ i wzmocnienia 0 dB.")

    def closeEvent(self, event) -> None:
        if self.editor_active:
            event.ignore()
            return
        if not self.allow_quit and self.tray is not None and self.tray.isVisible():
            event.ignore()
            self.hide()
            if not self.tray_notice_shown and self.tray.supportsMessages():
                self.tray_notice_shown = True
                self.tray.showMessage(
                    "MOONDROP Position",
                    "Okno zostało ukryte. Aplikacja nadal działa w zasobniku systemowym.",
                    QSystemTrayIcon.MessageIcon.Information,
                    2500,
                )
            return
        self.timer.stop()
        self.autoeq_panel.shutdown()
        self.pending_command = None
        if self.tray:
            self.tray.hide()
        self.pool.waitForDone()
        super().closeEvent(event)
        if self.allow_quit or self.tray is None:
            QApplication.quit()


def activate_existing_instance(server_name: str) -> bool:
    """Łączy się z działającą instancją aplikacji i prosi o pokazanie okna."""
    socket = QLocalSocket()
    socket.connectToServer(server_name)
    if not socket.waitForConnected(250):
        return False
    socket.write(b"show\n")
    socket.waitForBytesWritten(250)
    socket.disconnectFromServer()
    return True


def start_instance_server(server_name: str, on_activate) -> QLocalServer | None:
    """Uruchamia serwer pojedynczej instancji na gnieździe lokalnym Qt."""
    QLocalServer.removeServer(server_name)
    server = QLocalServer()
    if not server.listen(server_name):
        return None

    def handle_connection() -> None:
        while server.hasPendingConnections():
            conn = server.nextPendingConnection()
            if conn is not None:
                conn.waitForReadyRead(100)
                conn.close()
                conn.deleteLater()
        on_activate()

    server.newConnection.connect(handle_connection)
    return server


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--demo", action="store_true", help="uruchom GUI z symulowanym DAC-em")
    mode.add_argument("--diagnose", action="store_true", help="odczytaj stan USB bez uruchamiania GUI")
    mode.add_argument("--diagnose-controls", action="store_true", help="sprawdź odczyt dodatkowych ustawień bez zapisu")
    mode.add_argument(
        "--test-global-gain",
        action="store_true",
        help="zmniejsz global gain o 1 dB, sprawdź i przywróć bez komendy zapisu flash",
    )
    mode.add_argument(
        "--test-mic-gain",
        action="store_true",
        help="sprawdź odwracalną zmianę wzmocnienia mikrofonu bez komendy zapisu flash",
    )
    args = parser.parse_args()
    if args.diagnose or args.diagnose_controls or args.test_global_gain or args.test_mic_gain:
        try:
            dev = open_position()
            if dev is None:
                raise dac.HidError("Nie znaleziono MOONDROP Position w sysfs.")
            with dev:
                if args.test_global_gain:
                    report = test_global_gain(dev)
                elif args.test_mic_gain:
                    report = test_mic_gain(dev)
                elif args.diagnose_controls:
                    report = diagnose_controls(dev)
                else:
                    report = vars(read_state(dev))
        except dac.HidError as exc:
            print(exc, file=sys.stderr)
            return 1
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    app = QApplication([sys.argv[0]])
    app.setApplicationName("MOONDROP Position")
    server_name = f"moondrop-position-{'demo' if args.demo else 'live'}"
    if activate_existing_instance(server_name):
        return 0
    app.setQuitOnLastWindowClosed(not QSystemTrayIcon.isSystemTrayAvailable())
    desktop_id = "local.moondrop.Position"
    if QStandardPaths.locate(QStandardPaths.StandardLocation.GenericDataLocation, f"applications/{desktop_id}.desktop"):
        app.setDesktopFileName(desktop_id)
    window = ProfilesWindow(args.demo)
    instance_server = start_instance_server(server_name, window.open_window)
    if instance_server is not None:
        app.aboutToQuit.connect(instance_server.close)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
