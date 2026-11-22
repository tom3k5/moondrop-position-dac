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
    QRect,
    QRectF,
    QRunnable,
    QSaveFile,
    QSize,
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
    QPixmap,
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
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLayout,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStyle,
    QSystemTrayIcon,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import autoeq_catalog as catalog
import i18n
import moondrop_position as dac
from i18n import tr
from measurements import FIT_HIGH_HZ, curve_level, fit_to_target, read_squig_txt

DATA_DIR = Path(__file__).resolve().parents[1] / "dane"
BUILTIN_PROFILE = DATA_DIR / "profile/moondrop-position-harman.json"
HARMAN_TARGET = DATA_DIR / "targety/Harman in-ear 2019.csv"
INNOVIBE_ICON = DATA_DIR / "innovibe.svg"
GITHUB_REPO_URL = "https://github.com/tom3k5/moondrop-position-dac"
OFFICIAL_HUB_URL = "https://hub.moondroplab.tech/"
PROFILE_ROLE = Qt.ItemDataRole.UserRole
PATH_ROLE = Qt.ItemDataRole.UserRole + 1
PRIMARY_ACTION_STYLE = (
    "QPushButton:enabled { background: palette(highlight); color: palette(highlighted-text);"
    " border: 1px solid palette(highlight); border-radius: 6px; padding: 7px 18px; font-weight: 600; }"
    "QPushButton:focus { border: 1px solid palette(text); }"
)
SECONDARY_ACCENT_STYLE = (
    "QPushButton:enabled { background: palette(button); color: palette(link);"
    " border: 1px solid palette(highlight); border-radius: 6px; padding: 6px 14px; font-weight: 600; }"
    "QPushButton:enabled:hover { background: palette(alternate-base); border-color: palette(link); }"
    "QPushButton:focus { border: 1px solid palette(text); }"
)


def build_eq_sliders_icon(accent_hex: str) -> QIcon:
    """Rysuje wektorową ikonę suwaków korektora EQ w kolorze akcentu motywu."""
    size = 32
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor(accent_hex)
    painter.setPen(QPen(color, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.setBrush(color)
    for x, knob_y in ((7.5, 11.0), (16.0, 21.0), (24.5, 14.0)):
        painter.drawLine(QPointF(x, 5.5), QPointF(x, 26.5))
        painter.drawEllipse(QPointF(x, knob_y), 3.1, 3.1)
    painter.end()
    pixmap.setDevicePixelRatio(2.0)
    return QIcon(pixmap)


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
    color: palette(link);
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
    background: palette(alternate-base);
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
QLineEdit:hover:enabled, QComboBox:hover:enabled, QSpinBox:hover:enabled, QDoubleSpinBox:hover:enabled {
    border-color: palette(highlight);
    background: palette(alternate-base);
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: palette(highlight);
}
QCheckBox::indicator:hover:enabled {
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
QListWidget::item:hover:!selected, QListView::item:hover:!selected {
    background: palette(alternate-base);
}
QListWidget::item:selected, QListView::item:selected {
    background: palette(highlight);
    color: palette(highlighted-text);
}
QSplitter::handle {
    background: transparent;
    border: none;
}
QFrame#sourceCard, QFrame#previewCard {
    border: 1px solid palette(mid);
    border-radius: 8px;
    background: palette(base);
}
QFrame#sourceCard QListWidget, QFrame#sourceCard QListView {
    border: none;
    border-radius: 6px;
    padding: 2px;
    background: transparent;
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
QTabBar::tab:hover:!selected {
    background: palette(alternate-base);
    border-color: palette(mid);
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
    background-color: palette(base);
    color: palette(text);
}
"""
SEGMENT_BUTTON_STYLE = (
    "QPushButton { border: 1px solid palette(mid); padding: 5px 10px; background: palette(window); }"
    "QPushButton:hover:!checked { border-color: palette(highlight); background: palette(alternate-base); }"
    "QPushButton:checked { border-color: palette(highlight); background: palette(highlight);"
    " color: palette(highlighted-text); font-weight: 600; }"
)
STATUS_PILL_STYLE = "border: 1px solid palette(mid); border-radius: 12px; padding: 4px 12px; background: palette(base);"
FOOTER_BUTTON_STYLE = (
    "QPushButton, QToolButton { border: 1px solid transparent; border-radius: 6px;"
    " padding: 4px 10px; background: transparent; }"
    'QToolButton[popupMode="2"] { padding-right: 22px; }'
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
EQ_PLOT_FREQUENCIES = tuple(20 * 10 ** (index / 320) for index in range(961))
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
    coefficients: tuple[bytes, ...] = ()

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
    coefficients: tuple[bytes, ...] = ()


def load_profile(path: Path, name: str | None = None, *, pad_bands: bool = False) -> Profile:
    try:
        bands, meta = dac.load_eq_file(str(path))
    except SystemExit as exc:
        raise ValueError(str(exc)) from exc
    slot = meta.get("slot", dac.CUSTOM_SLOT)
    preamp = meta.get("preamp")
    if pad_bands:
        neutral = default_custom_bands()
        bands.extend(neutral[len(bands) :])
    stored_name = meta.get("name")
    if not isinstance(stored_name, str) or not stored_name.strip():
        stored_name = path.stem
    profile = custom_profile(
        name or stored_name, slot, bands, preamp, meta.get("global_gain_db"), meta.get("mic_gain_raw")
    )
    source = meta.get("source")
    target_name = meta.get("target_name")
    target = valid_curve(meta.get("target_curve", ()))
    fit_meta = meta.get("meta")
    if not target and (
        path.resolve() == BUILTIN_PROFILE.resolve()
        or (isinstance(fit_meta, dict) and fit_meta.get("target") == HARMAN_TARGET.name)
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
    if not -128 <= preamp <= 0 or any(
        b["type"] not in {"PK", "LSQ", "HSQ", "LP", "HP"} or not -18 <= b["gain"] <= 12 for b in bands
    ):
        raise ValueError("Position obsługuje PK, LSQ, HSQ, LP i HP, gain od −18 do +12 dB i pre-gain do 0 dB.")
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
        raise dac.HidError("Podłącz jeden MOONDROP:Gravity Position.")
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
    coefficients = []
    for index in range(dac.BAND_COUNT):
        band = dev.read_band(index, include_coefficients=True)
        if band is not None:
            coefficients.append(band.pop("coefficients"))
        bands.append(band)
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
    return DeviceState(dev.path, firmware, slot, preamp, bands, global_gain_db, mic_gain_raw, tuple(coefficients))


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
        self.custom_coefficients = [coefficients_for_band(band) for band in self.custom_bands]
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

    def read_band(self, index, *, include_coefficients=False):
        if self.active_slot == 0:
            band = POSITION_FACTORY_BANDS[index]
            coefficients = coefficients_for_band(band)
        else:
            band = self.custom_bands[index]
            coefficients = self.custom_coefficients[index]
        return {**band, "coefficients": coefficients} if include_coefficients else dict(band)

    def read_eq(self, bands):
        return [self.read_band(index) for index in range(bands)]

    def write_band(self, index, freq, gain, q, ftype, _slot):
        self.custom_coefficients[index] = dac.biquad_coefficients(dac.TYPE_TO_CODE[ftype], freq, gain, q)
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


def coefficients_for_band(band: dict) -> bytes:
    return dac.biquad_coefficients(dac.TYPE_TO_CODE[band["type"]], band["freq"], band["gain"], band["q"])


def response_points(profile: Profile, frequencies) -> list[tuple[float, float]]:
    bank = profile.coefficients or [coefficients_for_band(band) for band in profile.bands]
    coefficients = [struct.unpack("<5i", payload) for payload in bank]
    points = []
    for frequency in frequencies:
        angle = -2 * math.pi * frequency / dac.COEFF_FS
        z = complex(math.cos(angle), math.sin(angle))
        z2 = z * z
        level = 0.0
        for b0, b1, b2, neg_a1, neg_a2 in coefficients:
            numerator = abs(b0 + b1 * z + b2 * z2)
            denominator = abs(dac.COEFF_SCALE - neg_a1 * z - neg_a2 * z2)
            level += 20 * math.log10(max(numerator, 1e-12) / max(denominator, 1e-12))
        points.append((frequency, level))
    return points


def profile_from_readback(state: DeviceState) -> Profile | None:
    if (
        len(state.coefficients) != dac.BAND_COUNT
        or len(state.bands) != dac.BAND_COUNT
        or any(band is None or band["type"] not in dac.TYPE_TO_CODE for band in state.bands)
    ):
        return None
    return Profile("Odczyt z DAC-a", state.slot, list(state.bands), state.preamp, coefficients=state.coefficients)


def export_profile_dialog(parent: QWidget, title: str, profile: Profile) -> str | None:
    """Eksportuje profil EQ do JSON lub Equalizer APO (.txt); zwraca komunikat lub None."""
    base_name = profile.name.replace("/", "_") or "moondrop-position-eq"
    path, selected_filter = QFileDialog.getSaveFileName(parent, title, f"{base_name}.txt", tr("export.filter"))
    if not path:
        return None
    target = Path(path)
    use_apo = target.suffix.casefold() == ".txt" or (not target.suffix and "APO" in (selected_filter or ""))
    if use_apo:
        if target.suffix.casefold() != ".txt":
            target = target.with_suffix(".txt")
        target.write_text(dac.format_eqapo(profile.bands, profile.preamp), encoding="utf-8")
        return tr("export.saved_apo")
    if target.suffix.casefold() != ".json":
        target = target.with_suffix(".json")
    save_profile(target, profile)
    return "Profil zapisany do pliku JSON."


class ResponsePlot(QWidget):
    curves_changed = Signal()
    band_changed = Signal(int, float, float)
    band_q_changed = Signal(int, float)

    def __init__(self, *, correction: bool = False, interactive: bool = False):
        super().__init__()
        self.correction = correction
        self.interactive = interactive
        self.points = []
        self.reference_points = []
        self.target_points = []
        self.factory_points = [] if correction else measured_position()
        self.factory_filter = None
        self.frequencies = [hz for hz, _ in self.factory_points]
        self.factory_offsets = [0.0] * len(self.frequencies)
        self.active_bands: list[dict] = []
        self.band_handles: list[tuple[int, float, float]] = []
        self.plot_bounds = None
        self.drag_index: int | None = None
        self.hover_index: int | None = None
        self.drag_start_y = 0.0
        self.drag_start_gain = 0.0
        self.hidden_roles: set[int] = set()
        self.solo_role: int | None = None
        self.hover_hz: float | None = None
        self.setMouseTracking(True)
        self.setMinimumHeight(95 if correction else 135)
        self.setAccessibleName(
            "Korekcja EQ w dB" if correction else "Charakterystyka słuchawek MOONDROP:Gravity Position w dB SPL"
        )

    def set_primary_points(self, points: list[tuple[float, float]]) -> None:
        self.points = points
        self.curves_changed.emit()
        self.update()

    def acoustic_points(self, profile: Profile | None) -> list[tuple[float, float]]:
        if profile is None:
            return []
        if profile.slot == 0:
            return self.factory_points
        correction = response_points(profile, self.frequencies)
        return [
            (hz, measured + adjustment - factory)
            for (hz, measured), (_, adjustment), factory in zip(
                self.factory_points, correction, self.factory_offsets, strict=False
            )
        ]

    def set_profile(self, profile: Profile | None) -> None:
        self.active_bands = list(profile.bands) if (self.interactive and profile is not None) else []
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

    def toggle_role(self, role: int) -> None:
        self.toggle_roles([role])

    def toggle_roles(self, roles: list[int]) -> None:
        hidden = self.is_role_hidden(roles)
        for role in roles:
            if hidden:
                self.hidden_roles.discard(role)
            else:
                self.hidden_roles.add(role)
        if not hidden and self.solo_role in roles:
            self.solo_role = None
        self.curves_changed.emit()
        self.update()

    def set_roles_hidden(self, roles: list[int], hidden: bool) -> None:
        for role in roles:
            if hidden:
                self.hidden_roles.add(role)
            else:
                self.hidden_roles.discard(role)
        self.curves_changed.emit()
        self.update()

    def set_solo_role(self, role: int | None) -> None:
        if self.solo_role != role:
            self.solo_role = role
            self.update()

    def is_role_hidden(self, roles: list[int]) -> bool:
        return bool(roles) and all(role in self.hidden_roles for role in roles)

    def set_factory(self, profile: Profile | None) -> None:
        if profile != self.factory_filter:
            self.factory_filter = profile
            self.factory_offsets = (
                [db for _, db in response_points(profile, self.frequencies)]
                if profile
                else [0.0] * len(self.frequencies)
            )

    def series(self):
        return [
            ([role], points)
            for role, points in enumerate((self.points, self.reference_points, self.factory_points, self.target_points))
            if points
        ]

    def series_pen(self, role: int) -> QPen:
        dark_bg = self.palette().base().color().lightness() < 128
        # Role: 0 = wybrany/edytowany, 1 = obecnie w DSP / referencja, 2 = pomiar Position, 3 = cel AutoEq
        palette_hex = (
            ("#ff9524", "#e879f9", "#22d3ee", "#4ade80") if dark_bg else ("#e55300", "#a21caf", "#0284c7", "#15803d")
        )
        styles = (Qt.PenStyle.SolidLine, Qt.PenStyle.DashLine, Qt.PenStyle.DotLine, Qt.PenStyle.DashDotLine)
        return QPen(QColor(palette_hex[role]), (2.5, 2.0, 2.2, 2.2)[role], styles[role])

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

        if not self.correction:
            cutoff = x(FIT_HIGH_HZ)
            treble = palette.color(QPalette.ColorRole.Text)
            treble.setAlpha(20)
            painter.fillRect(QRectF(cutoff, plot.top(), plot.right() - cutoff, plot.height()), treble)

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
            if self.is_role_hidden(roles):
                continue
            curve = QPainterPath(QPointF(x(points[0][0]), y(points[0][1])))
            for hz, db in points[1:]:
                curve.lineTo(QPointF(x(hz), y(db)))
            pen = self.series_pen(roles[0])
            dimmed = self.solo_role is not None and self.solo_role not in roles
            if dimmed:
                c = pen.color()
                c.setAlpha(48)
                pen.setColor(c)
            elif self.solo_role is not None:
                pen.setWidthF(pen.widthF() + 0.6)
            if self.correction and roles[0] == 0:
                fill_path = QPainterPath(curve)
                baseline_y = y(0.0)
                fill_path.lineTo(QPointF(x(points[-1][0]), baseline_y))
                fill_path.lineTo(QPointF(x(points[0][0]), baseline_y))
                fill_path.closeSubpath()
                fill_color = pen.color()
                fill_color.setAlpha(14 if dimmed else 38)
                painter.fillPath(fill_path, fill_color)
            painter.setPen(pen)
            painter.drawPath(curve)
        self.plot_bounds = (plot, low, high)
        if self.hover_hz is not None and self.drag_index is None and plot.width() > 0:
            hx = x(self.hover_hz)
            if plot.left() <= hx <= plot.right():
                hair_color = QColor(text)
                hair_color.setAlpha(105)
                painter.setPen(QPen(hair_color, 1.0, Qt.PenStyle.DashLine))
                painter.drawLine(QPointF(hx, plot.top()), QPointF(hx, plot.bottom()))
                self._draw_hover_readout(painter, plot, groups, hx, text)
        self.band_handles = []
        if self.interactive and self.points and self.active_bands:
            accent = QColor("#ff8a1f" if palette.base().color().lightness() < 128 else "#e5470a")
            handle_font = painter.font()
            handle_font.setPointSizeF(max(8.0, handle_font.pointSizeF() * 0.85))
            handle_font.setBold(True)
            painter.setFont(handle_font)
            for idx, band in enumerate(self.active_bands):
                hz = max(20.0, min(20000.0, float(band.get("freq", 1000.0))))
                curve_db = curve_level(self.points, hz)
                hx = x(hz)
                hy = y(curve_db)
                self.band_handles.append((idx, hx, hy))
                active = idx in (self.drag_index, self.hover_index)
                radius = 10.5 if active else 8.5
                painter.setPen(QPen(accent if active else text, 2.2 if active else 1.5))
                painter.setBrush(accent if active else palette.base().color())
                painter.drawEllipse(QPointF(hx, hy), radius, radius)
                painter.setPen(palette.highlightedText().color() if active else text)
                label_rect = painter.boundingRect(
                    int(hx - radius),
                    int(hy - radius),
                    int(radius * 2),
                    int(radius * 2),
                    Qt.AlignmentFlag.AlignCenter,
                    str(idx + 1),
                )
                painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, str(idx + 1))

    def _draw_hover_readout(self, painter: QPainter, plot, groups, hx: float, text: QColor) -> None:
        if self.hover_hz is None:
            return
        hz_val = self.hover_hz
        freq_text = f"{hz_val / 1000:.2f} kHz" if hz_val >= 1000 else f"{round(hz_val)} Hz"
        values: dict[int, float] = {}
        parts = [freq_text]
        short_names = tuple(
            tr(key) for key in ("plot.hover.selected", "plot.hover.dsp", "plot.hover.factory", "plot.hover.target")
        )
        for roles, points in groups:
            if self.is_role_hidden(roles) or not points[0][0] <= hz_val <= points[-1][0]:
                continue
            val = curve_level(points, hz_val)
            for role in roles:
                values[role] = val
            label = short_names[roles[0]]
            parts.append(f"{label}: {val:+.1f}" if self.correction else f"{label}: {val:.1f}")
        ref_val = values.get(1)
        cmp_val = values.get(0) if 0 in values else values.get(3)
        if ref_val is not None and cmp_val is not None and abs(cmp_val - ref_val) >= 0.05:
            parts.append(f"Δ {cmp_val - ref_val:+.1f} dB")
        readout = " · ".join(parts)
        badge_font = painter.font()
        badge_font.setPointSizeF(max(8.0, badge_font.pointSizeF() * 0.86))
        painter.setFont(badge_font)
        fm = painter.fontMetrics()
        tw = min(plot.width() - 16, fm.horizontalAdvance(readout) + 16)
        th = fm.height() + 8
        place_left = hx > plot.center().x()
        bx = plot.left() + 8 if place_left else plot.right() - tw - 8
        by = plot.top() + 6
        bg = self.palette().window().color()
        bg.setAlpha(215)
        border = self.palette().color(QPalette.ColorRole.Mid)
        painter.setBrush(bg)
        painter.setPen(QPen(border, 1))
        painter.drawRoundedRect(QRectF(bx, by, tw, th), 5, 5)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(text)
        painter.drawText(
            QRectF(bx + 8, by, tw - 16, th),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            fm.elidedText(readout, Qt.TextElideMode.ElideRight, int(tw - 16)),
        )

    def _hit_handle(self, pos: QPointF) -> int | None:
        best_idx = None
        best_dist = 14.0
        for idx, hx, hy in self.band_handles:
            dist = math.hypot(pos.x() - hx, pos.y() - hy)
            if dist <= best_dist:
                best_dist = dist
                best_idx = idx
        return best_idx

    def mousePressEvent(self, event) -> None:
        if self.interactive and event.button() == Qt.MouseButton.LeftButton:
            hit = self._hit_handle(event.position())
            if hit is not None and 0 <= hit < len(self.active_bands):
                self.drag_index = hit
                self.drag_start_y = event.position().y()
                self.drag_start_gain = float(self.active_bands[hit].get("gain", 0.0))
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self.update()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        if self.interactive and self.drag_index is not None and self.plot_bounds is not None:
            plot, low, high = self.plot_bounds
            if plot.width() > 0 and plot.height() > 0:
                ratio_x = max(0.0, min(1.0, (pos.x() - plot.left()) / plot.width()))
                new_freq = round(20.0 * (10.0 ** (3.0 * ratio_x)))
                new_freq = max(20, min(20000, new_freq))
                delta_db = (self.drag_start_y - pos.y()) * (high - low) / plot.height()
                new_gain = max(-18.0, min(12.0, round(self.drag_start_gain + delta_db, 1)))
                self.band_changed.emit(self.drag_index, float(new_freq), float(new_gain))
            event.accept()
            return
        new_hover_hz = None
        if self.plot_bounds is not None:
            plot, _, _ = self.plot_bounds
            if plot.contains(pos.toPoint()) and plot.width() > 0:
                ratio_x = max(0.0, min(1.0, (pos.x() - plot.left()) / plot.width()))
                new_hover_hz = max(20.0, min(20000.0, 20.0 * (10.0 ** (3.0 * ratio_x))))
        need_update = new_hover_hz != self.hover_hz
        self.hover_hz = new_hover_hz
        if self.interactive:
            hit = self._hit_handle(pos)
            if hit != self.hover_index:
                self.hover_index = hit
                self.setCursor(Qt.CursorShape.OpenHandCursor if hit is not None else Qt.CursorShape.ArrowCursor)
                need_update = True
        if need_update:
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self.hover_hz is not None or self.hover_index is not None:
            self.hover_hz = None
            self.hover_index = None
            self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self.interactive and self.drag_index is not None:
            self.drag_index = None
            hit = self._hit_handle(event.position())
            self.hover_index = hit
            self.setCursor(Qt.CursorShape.OpenHandCursor if hit is not None else Qt.CursorShape.ArrowCursor)
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        if self.interactive and self.hover_index is not None:
            delta = event.angleDelta().y()
            if delta != 0:
                self.band_q_changed.emit(self.hover_index, 0.1 if delta > 0 else -0.1)
                event.accept()
                return
        super().wheelEvent(event)


class CurveSwatch(QWidget):
    def __init__(self, plot: ResponsePlot, role: int):
        super().__init__()
        self.plot = plot
        self.role = role
        self.dimmed = False
        self.setFixedSize(30, max(14, self.fontMetrics().lineSpacing()))

    def set_dimmed(self, dimmed: bool) -> None:
        if self.dimmed != dimmed:
            self.dimmed = dimmed
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = self.plot.series_pen(self.role)
        if self.dimmed:
            color = pen.color()
            color.setAlpha(65)
            pen.setColor(color)
        painter.setPen(pen)
        y = self.height() / 2
        painter.drawLine(QPointF(2, y), QPointF(self.width() - 2, y))


class _FlowLayout(QLayout):
    def __init__(self, parent=None, spacing: int = 6, max_per_row: int = 0):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self._max_per_row = max_per_row

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0
        row_count = 0
        for item in self._items:
            widget = item.widget()
            if widget is not None and not widget.isVisible():
                continue
            hint = item.sizeHint()
            item_w = min(hint.width(), max(1, effective.width()))
            item_h = hint.height()
            next_x = x + item_w + self._spacing
            wrap_by_count = self._max_per_row > 0 and row_count >= self._max_per_row
            wrap_by_width = next_x - self._spacing > effective.right() + 1
            if (wrap_by_count or wrap_by_width) and line_height > 0:
                x = effective.x()
                y += line_height + self._spacing
                next_x = x + item_w + self._spacing
                line_height = 0
                row_count = 0
            if not test_only:
                item.setGeometry(QRect(x, y, item_w, item_h))
            x = next_x
            line_height = max(line_height, item_h)
            row_count += 1
        return y + line_height - rect.y() + m.bottom()


class _LegendChip(QFrame):
    def __init__(self, plot: ResponsePlot, role: int, on_toggle=None):
        super().__init__()
        self.setObjectName("legendChip")
        self.plot = plot
        self.role = role
        self.active_roles: list[int] = [role]
        self.on_toggle = on_toggle
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        line = QHBoxLayout(self)
        line.setContentsMargins(7, 3, 9, 3)
        line.setSpacing(6)
        self.swatch = CurveSwatch(plot, role)
        self.swatch.setFixedSize(22, max(12, self.fontMetrics().lineSpacing() - 2))
        line.addWidget(self.swatch, 0, Qt.AlignmentFlag.AlignVCenter)
        self.label = QLabel()
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setWordWrap(False)
        self.label.setMinimumWidth(0)
        line.addWidget(self.label, 1)
        self.setMaximumWidth(275)
        self.set_dimmed(False)

    def set_text(self, text: str) -> None:
        elided = self.label.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, 230)
        self.label.setText(elided)

    def set_dimmed(self, dimmed: bool) -> None:
        if not dimmed:
            self.setStyleSheet(
                "QFrame#legendChip { border: 1px solid palette(mid); border-radius: 6px;"
                " background: palette(alternate-base); }"
                "QFrame#legendChip:hover, QFrame#legendChip:focus { border-color: palette(highlight); }"
            )
        else:
            self.setStyleSheet(
                "QFrame#legendChip { border: 1px dashed palette(mid); border-radius: 6px; color: palette(mid); }"
                "QFrame#legendChip:hover, QFrame#legendChip:focus {"
                " border-color: palette(highlight); background: palette(alternate-base); }"
            )
        self.swatch.set_dimmed(dimmed)

    def _trigger_toggle(self) -> None:
        if self.on_toggle is not None:
            self.on_toggle(self.active_roles)
        else:
            self.plot.toggle_roles(self.active_roles)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._trigger_toggle()
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._trigger_toggle()
            event.accept()
            return
        super().keyPressEvent(event)

    def enterEvent(self, event) -> None:
        if not self.plot.is_role_hidden(self.active_roles):
            self.plot.set_solo_role(self.role)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.plot.set_solo_role(None)
        super().leaveEvent(event)


class PlotKey(QWidget):
    def __init__(
        self,
        plot: ResponsePlot,
        labels: tuple[str, ...],
        linked_plots: list[ResponsePlot] | None = None,
        fixed_rows: int = 0,
    ):
        super().__init__()
        self.plot = plot
        self.labels = labels
        self.linked_plots = linked_plots or []
        self.chips: list[_LegendChip] = []
        self.flow = _FlowLayout(self, spacing=6, max_per_row=2 if fixed_rows == 2 else 0)
        self.flow.setContentsMargins(0, 2, 0, 2)
        for role in range(len(labels)):
            chip = _LegendChip(plot, role, on_toggle=self._toggle_chip_roles)
            self.chips.append(chip)
            self.flow.addWidget(chip)
        if fixed_rows > 0 and self.chips:
            row_h = max(self.chips[0].sizeHint().height(), self.fontMetrics().lineSpacing() + 8)
            self.setFixedHeight(fixed_rows * row_h + max(0, fixed_rows - 1) * 6 + 4)
        plot.curves_changed.connect(self.refresh)
        self.refresh()

    def _toggle_chip_roles(self, roles: list[int]) -> None:
        self.plot.toggle_roles(roles)
        hidden = self.plot.is_role_hidden(roles)
        sync_roles = [r for r in roles if r in (0, 1)]
        if sync_roles:
            for linked in self.linked_plots:
                linked.set_roles_hidden(sync_roles, hidden)

    def set_labels(self, labels: tuple[str, ...]) -> None:
        self.labels = labels
        self.refresh()

    def refresh(self) -> None:
        groups = {roles[0]: roles for roles, _ in self.plot.series()}
        for role, chip in enumerate(self.chips):
            roles = groups.get(role, [])
            chip.setVisible(bool(roles))
            if roles:
                chip.active_roles = list(roles)
                text = " = ".join(self.labels[index] for index in roles if self.labels[index])
                chip.set_text(text)
                chip.setToolTip(tr("plot.key.chip_tooltip", label=text))
                chip.set_dimmed(self.plot.is_role_hidden(roles))
        self.flow.invalidate()
        self.updateGeometry()


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
        self.auto_headroom_btn = QPushButton(tr("editor.auto_headroom"))
        self.auto_headroom_btn.setToolTip(tr("tooltip.editor_auto_headroom"))
        self.auto_headroom_btn.clicked.connect(self.apply_auto_headroom)
        top_bar.addWidget(self.auto_headroom_btn)
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

        self.plot = ResponsePlot(interactive=True)
        self.plot.setMinimumHeight(180)
        self.plot.set_factory(factory)
        self.plot.band_changed.connect(self.on_plot_band_changed)
        self.plot.band_q_changed.connect(self.on_plot_band_q_changed)
        plot_header = QHBoxLayout()
        plot_header.addWidget(QLabel(tr("plot.fr_title")))
        self.headroom_label = QLabel()
        self.headroom_label.setTextFormat(Qt.TextFormat.PlainText)
        plot_header.addSpacing(12)
        plot_header.addWidget(self.headroom_label)
        plot_header.addStretch()
        self.compare = QCheckBox(tr("editor.compare"))
        self.compare.setToolTip(tr("tooltip.editor_compare"))
        self.compare.toggled.connect(self.update_reference)
        plot_header.addWidget(self.compare)
        layout.addLayout(plot_header)
        layout.addWidget(self.plot, 1)
        layout.addWidget(
            PlotKey(self.plot, tuple(tr(key) for key in ("plot.key.draft", "plot.key.initial", "plot.key.measured")))
        )
        measurement_note = QLabel(tr("plot.measurement_note") + " · " + tr("plot.treble_note"))
        measurement_note.setWordWrap(True)
        if factory is None:
            measurement_note.setText(measurement_note.text() + " · podgląd zakłada neutralne EQ fabryczne")
        layout.addWidget(measurement_note)
        drag_hint = QLabel(tr("editor.plot_drag_hint"))
        drag_hint.setWordWrap(True)
        layout.addWidget(drag_hint)
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
                (tr("editor.type_lsq"), "LSQ"),
                (tr("editor.type_hsq"), "HSQ"),
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
        enabled = kind.currentData() in {"PK", "LSQ", "HSQ"}
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

    def apply_auto_headroom(self) -> None:
        profile = self.draft()
        peak_boost = max(0.0, max(db for _, db in response_points(profile, EQ_PLOT_FREQUENCIES)))
        self.preamp.setValue(max(-128.0, round(-peak_boost, 2)))

    def on_plot_band_changed(self, index: int, freq: float, gain: float) -> None:
        if 0 <= index < len(self.rows):
            _kind, frequency_box, gain_box, _q = self.rows[index]
            frequency_box.setValue(round(freq))
            gain_box.setValue(gain)

    def on_plot_band_q_changed(self, index: int, delta_q: float) -> None:
        if 0 <= index < len(self.rows):
            _kind, _freq, _gain, q_box = self.rows[index]
            q_box.setValue(max(q_box.minimum(), min(q_box.maximum(), round(q_box.value() + delta_q, 2))))

    def update_draft(self) -> None:
        profile = self.draft()
        if self.live.isChecked() and self.live_previous is not None and profile.preamp == self.live_previous.preamp:
            profile = replace(profile, preamp=self.live_preamp)
        peak_boost = max(db for _, db in response_points(profile, EQ_PLOT_FREQUENCIES))
        net_peak = peak_boost + (profile.preamp or 0.0)
        if net_peak > 0.05:
            self.headroom_label.setText(tr("editor.headroom_clip", peak=net_peak))
            self.headroom_label.setStyleSheet("color: palette(link); font-weight: 600;")
        else:
            self.headroom_label.setText(tr("editor.headroom_ok", peak=net_peak))
            self.headroom_label.setStyleSheet("color: palette(placeholder-text);")
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
        try:
            notice = export_profile_dialog(self, "Zapisz profil EQ", profile)
        except OSError as exc:
            self.message.setText(f"Błąd zapisu profilu. {exc}")
            return
        if notice:
            self.message.setText(notice)


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
        self.preview_entry = None
        self.preview_curve: list[tuple[float, float]] = []
        self.preview_request_id = 0
        self.preview_timer = QTimer(self, singleShot=True, interval=200)
        self.preview_timer.timeout.connect(self.load_selected_preview)
        self.preview_pool = QThreadPool(self)
        self.preview_pool.setMaxThreadCount(1)
        self.preview_jobs: set[Job] = set()
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

        range_row = QHBoxLayout()
        range_row.setSpacing(8)
        self.fit_range_label = QLabel(tr("autoeq.fit_range_label"))
        self.fit_range = QComboBox()
        self.fit_range.setAccessibleName(tr("autoeq.fit_range_label"))
        self.fit_range.setToolTip(tr("tooltip.autoeq_fit_range"))
        self.fit_range.addItem(tr("autoeq.fit_full"), (20000.0, 8))
        self.fit_range.addItem(tr("autoeq.fit_6k"), (6000.0, 6))
        self.fit_range.addItem(tr("autoeq.fit_4k"), (4000.0, 6))
        self.fit_range.addItem(tr("autoeq.fit_2k"), (2000.0, 5))
        range_row.addWidget(self.fit_range_label)
        range_row.addWidget(self.fit_range, 1)
        layout.addLayout(range_row)

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
        if entry is None:
            self.preview_timer.stop()
            self.preview_entry = None
            self.preview_curve = []
            self.preview_request_id += 1
        elif entry != self.preview_entry:
            self.preview_entry = entry
            self.preview_curve = []
            self.preview_request_id += 1
            self.preview_timer.start()
        self.update_actions()
        self.preview_changed.emit()

    def load_selected_preview(self) -> None:
        entry = self.preview_entry
        if entry is None or (not entry.local and not self.isVisible()):
            return
        req_id = self.preview_request_id
        cache_dir = self.cache_directory / "curves"
        job = Job(lambda: read_target_curve(catalog.resolve_curve(entry, cache_dir)))
        self.preview_jobs.add(job)
        job.signals.finished.connect(
            lambda result, error, rid=req_id, target_entry=entry, done_job=job: self._preview_loaded(
                rid, target_entry, result, error, done_job
            )
        )
        self.preview_pool.start(job)

    def _preview_loaded(self, req_id: int, entry: catalog.Entry, result, error: str, done_job: Job) -> None:
        self.preview_jobs.discard(done_job)
        if req_id != self.preview_request_id or entry != self.preview_entry:
            return
        if error or not result:
            self.preview_curve = []
            return
        self.preview_curve = list(result)
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

    def add_custom_target_path(self, path: str | Path) -> None:
        resolved = str(path)
        entry = catalog.Entry(Path(resolved).stem, "Plik lokalny", "target", resolved, True)
        self.entries = list(dict.fromkeys([*self.entries, entry]))
        self.mode.setCurrentIndex(self.mode.findData("target"))
        self.search.clear()
        self.update_results()
        if entry in self.target_model.entries:
            row = self.target_model.entries.index(entry)
            self.targets.setCurrentIndex(self.target_model.index(row, 0))

    def open_target(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Wybierz krzywą docelową", "", "Pomiary (*.csv *.txt)")
        if path:
            self.add_custom_target_path(path)

    def generate_profile(self) -> None:
        entry = self.current_entry()
        if entry is None:
            return
        self.result = None
        self.result_entry = entry
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
        self.status.setText("AutoEq oblicza osiem pasm dla MOONDROP:Gravity Position…")
        self.cancel.show()
        self.preview_changed.emit()
        self.fit_cancelled = False
        self.fit_timer.start()
        python = DATA_DIR.parent / ".venvs/autoeq/bin/python"
        max_fc, fit_bands = self.fit_range.currentData() or (20000.0, 8)
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
                "--max-fc",
                str(max_fc),
                "--bands",
                str(fit_bands),
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
                loaded = load_profile(self.output, name, pad_bands=True)
                self.result = replace(
                    loaded,
                    source=f"AutoEq · {self.result_entry.source}",
                    target_name=self.result_entry.name,
                    target_curve=self.target_curve,
                )
            except (OSError, ValueError, dac.HidError) as exc:
                self.status.setText(f"Nie udało się wczytać wyniku AutoEq. {exc}")
            else:
                self.status.setText("Profil gotowy do wgrania lub zapisania na później.")
        self.finish_fit()

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
        self.preview_timer.stop()
        self.preview_pool.waitForDone(1000)
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.cancel_fit()
            self.process.waitForFinished(1000)


class FeedbackLabel(QLabel):
    """Etykieta komunikatów statusu ukrywana automatycznie, gdy jest pusta."""

    def __init__(self, text: str = ""):
        super().__init__(text)
        self.setVisible(bool(text))

    def setText(self, text: str) -> None:
        super().setText(text)
        self.setVisible(bool(text))

    def clear(self) -> None:
        super().clear()
        self.setVisible(False)


class ProfilesWindow(QWidget):
    def __init__(self, demo: bool, library_directory: Path | None = None):
        super().__init__()
        self.setWindowTitle("MOONDROP:Gravity Position")
        self.setStyleSheet(APP_STYLE)
        self.setAcceptDrops(True)
        self.setMinimumSize(840, 660)
        self.resize(1040, 750)
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
        layout.setContentsMargins(20, 14, 20, 12)
        layout.setSpacing(12)
        heading = QLabel("MOONDROP:Gravity Position")
        font = heading.font()
        font.setPointSizeF(font.pointSizeF() * 1.55)
        font.setBold(True)
        heading.setFont(font)
        self.connection = QLabel(tr("status.demo") if demo else tr("status.searching"))
        self.connection.setTextFormat(Qt.TextFormat.PlainText)
        self.connection.setStyleSheet(STATUS_PILL_STYLE)
        header = QHBoxLayout()
        header.addWidget(heading)
        header.addStretch()
        header.addWidget(self.connection)
        layout.addLayout(header)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        layout.addWidget(self.tabs, 1)

        device_page = QWidget()
        device_layout = QGridLayout(device_page)
        device_layout.setContentsMargins(0, 12, 0, 0)
        device_layout.setHorizontalSpacing(14)
        device_layout.setVerticalSpacing(8)
        device_layout.setColumnStretch(0, 1)
        device_layout.setColumnStretch(1, 1)
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
        device_actions.setSpacing(10)
        device_actions.addWidget(self.backup_button, 1)
        device_actions.addWidget(self.defaults_button, 1)

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

        self.tips_box = QGroupBox(tr("device.tips_group"))
        tips_layout = QVBoxLayout(self.tips_box)
        self.tips_label = QLabel()
        self.tips_label.setTextFormat(Qt.TextFormat.RichText)
        self.tips_label.setWordWrap(True)
        tips_layout.addWidget(self.tips_label)

        device_layout.addWidget(self.device_box, 0, 0)
        device_layout.addWidget(self.gains_box, 0, 1)
        device_layout.addWidget(self.playback_box, 1, 0, 1, 2)
        device_layout.addWidget(self.language_box, 2, 0)
        device_layout.addWidget(self.maintenance_box, 2, 1)
        device_layout.addWidget(self.tips_box, 3, 0, 1, 2)
        device_layout.setRowStretch(4, 1)

        device_scroll = QScrollArea()
        device_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        device_scroll.setWidgetResizable(True)
        device_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        device_scroll.setWidget(device_page)

        self.profile_page = QWidget()
        profile_layout = QVBoxLayout(self.profile_page)
        profile_layout.setContentsMargins(0, 12, 0, 0)
        profile_layout.setSpacing(0)
        library_split = QSplitter(Qt.Orientation.Horizontal)
        library_split.setChildrenCollapsible(False)
        library_split.setHandleWidth(16)
        source_panel = QFrame()
        source_panel.setObjectName("sourceCard")
        source_layout = QVBoxLayout(source_panel)
        source_layout.setContentsMargins(12, 12, 12, 10)
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
        source_divider = QWidget()
        source_divider.setFixedHeight(1)
        source_divider.setStyleSheet("background: palette(mid);")
        source_layout.addWidget(source_divider)
        source_actions = QHBoxLayout()
        source_actions.setContentsMargins(0, 2, 0, 0)
        source_actions.setSpacing(8)
        self.library_actions = QWidget()
        library_actions = QHBoxLayout(self.library_actions)
        library_actions.setContentsMargins(0, 0, 0, 0)
        library_actions.setSpacing(8)
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
        library_actions.addWidget(self.add_button)
        library_actions.addWidget(self.more_button)
        source_actions.addWidget(self.library_actions)
        source_actions.addWidget(self.autoeq_panel.generate)
        source_actions.addWidget(self.autoeq_panel.cancel)
        source_actions.addStretch()
        source_layout.addLayout(source_actions)
        library_split.addWidget(source_panel)
        preview_panel = QWidget()
        preview_panel.setStyleSheet("background: transparent;")
        preview = QVBoxLayout(preview_panel)
        preview.setContentsMargins(14, 12, 14, 10)
        preview.setSpacing(6)
        preview_header = QHBoxLayout()
        preview_header.setContentsMargins(0, 0, 0, 0)
        preview_header.setSpacing(12)
        preview_header_text = QVBoxLayout()
        preview_header_text.setContentsMargins(0, 0, 0, 0)
        preview_header_text.setSpacing(2)
        self.preview_title = QLabel()
        self.preview_title.setTextFormat(Qt.TextFormat.PlainText)
        self.preview_title.setWordWrap(True)
        title_font = self.preview_title.font()
        title_font.setPointSizeF(title_font.pointSizeF() * 1.2)
        title_font.setBold(True)
        self.preview_title.setFont(title_font)
        preview_header_text.addWidget(self.preview_title)
        self.profile_info = QLabel()
        self.profile_info.setTextFormat(Qt.TextFormat.PlainText)
        self.profile_info.setWordWrap(True)
        self.profile_info.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        preview_header_text.addWidget(self.profile_info)
        preview_header.addLayout(preview_header_text, 1)
        self.save_fit_button = QPushButton(tr("actions.save_later"))
        self.save_fit_button.setMinimumHeight(32)
        self.edit_button = QPushButton(tr("actions.edit_eq"))
        self.edit_button.setStyleSheet(SECONDARY_ACCENT_STYLE)
        self.edit_button.setMinimumHeight(32)
        self.edit_button.setIconSize(QSize(16, 16))
        self.apply_button = QPushButton(tr("actions.apply_dac"))
        self.apply_button.setStyleSheet(PRIMARY_ACTION_STYLE)
        self.apply_button.setMinimumWidth(140)
        self.apply_button.setMinimumHeight(32)
        self.apply_button.setEnabled(False)
        preview_header_actions = QHBoxLayout()
        preview_header_actions.setContentsMargins(0, 0, 0, 0)
        preview_header_actions.setSpacing(8)
        preview_header_actions.addWidget(self.save_fit_button)
        preview_header_actions.addWidget(self.edit_button)
        preview_header_actions.addWidget(self.apply_button)
        preview_header.addLayout(preview_header_actions)
        preview.addLayout(preview_header)
        self.fr_title_label = QLabel(tr("plot.fr_title"))
        self.fr_title_label.setStyleSheet("font-weight: 600;")
        preview.addWidget(self.fr_title_label)
        self.preview_plot = ResponsePlot()
        preview.addWidget(self.preview_plot, 2)
        self.correction_plot = ResponsePlot(correction=True)
        self.preview_key = PlotKey(
            self.preview_plot,
            (
                tr("plot.key.selected"),
                tr("plot.key.current_dsp"),
                tr("plot.key.measured"),
                tr("plot.key.target_default"),
            ),
            linked_plots=[self.correction_plot],
            fixed_rows=2,
        )
        preview.addWidget(self.preview_key)
        self.fit_summary = FeedbackLabel()
        self.fit_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.fit_summary.setWordWrap(True)
        preview.addWidget(self.fit_summary)
        preview.addSpacing(4)
        section_divider = QWidget()
        section_divider.setFixedHeight(1)
        section_divider.setStyleSheet("background: palette(mid);")
        preview.addWidget(section_divider)
        preview.addSpacing(4)
        self.correction_title = QLabel(tr("plot.eq_title"))
        self.correction_title.setStyleSheet("font-weight: 600;")
        preview.addWidget(self.correction_title)
        preview.addWidget(self.correction_plot, 1)
        self.preamp_summary = FeedbackLabel()
        self.preamp_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.preamp_summary.setWordWrap(True)
        preview.addWidget(self.preamp_summary)
        self.plot_legend = QLabel()
        self.plot_legend.setTextFormat(Qt.TextFormat.PlainText)
        self.plot_legend.setWordWrap(True)
        self.plot_legend.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        preview.addWidget(self.plot_legend)
        preview_scroll = QScrollArea()
        preview_scroll.setObjectName("previewCard")
        preview_scroll.viewport().setStyleSheet("background: transparent;")
        preview_scroll.setWidgetResizable(True)
        preview_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        preview_scroll.setWidget(preview_panel)
        library_split.addWidget(preview_scroll)
        source_panel.setMinimumWidth(315)
        library_split.setStretchFactor(0, 2)
        library_split.setStretchFactor(1, 4)
        library_split.setSizes([360, 640])
        profile_layout.addWidget(library_split, 1)
        self.tabs.addTab(self.profile_page, tr("tab.tuning"))
        self.tabs.addTab(device_scroll, tr("tab.device"))

        guide_page = QWidget()
        guide_layout = QVBoxLayout(guide_page)
        guide_layout.setContentsMargins(0, 12, 0, 0)
        guide_layout.setSpacing(12)

        self.why_box = QGroupBox(tr("help.why_group"))
        why_layout = QVBoxLayout(self.why_box)
        self.why_label = QLabel()
        self.why_label.setTextFormat(Qt.TextFormat.RichText)
        self.why_label.setOpenExternalLinks(True)
        self.why_label.setWordWrap(True)
        why_layout.addWidget(self.why_label)

        self.guide_tips_box = QGroupBox(tr("help.tips_group"))
        guide_tips_layout = QVBoxLayout(self.guide_tips_box)
        self.guide_tips_label = QLabel()
        self.guide_tips_label.setTextFormat(Qt.TextFormat.RichText)
        self.guide_tips_label.setWordWrap(True)
        guide_tips_layout.addWidget(self.guide_tips_label)

        self.links_box = QGroupBox(tr("help.links_group"))
        links_layout = QHBoxLayout(self.links_box)
        links_layout.setSpacing(10)
        self.guide_hub_btn = QPushButton(tr("help.open_hub"))
        self.guide_hub_btn.clicked.connect(lambda: self.open_external_url(OFFICIAL_HUB_URL))
        innovibe_icon = QIcon(str(INNOVIBE_ICON))
        self.guide_author_btn = QPushButton(tr("help.author_link"))
        self.guide_author_btn.setIcon(innovibe_icon)
        self.guide_author_btn.setToolTip(tr("footer.author_tooltip"))
        self.guide_author_btn.clicked.connect(lambda: self.open_external_url(tr("footer.author_url")))
        self.guide_coffee_btn = QPushButton(tr("help.coffee_link"))
        self.guide_coffee_btn.setStyleSheet(PRIMARY_ACTION_STYLE)
        self.guide_coffee_btn.setToolTip(tr("footer.coffee_tooltip"))
        self.guide_coffee_btn.clicked.connect(lambda: self.open_external_url(tr("footer.coffee_url")))
        links_layout.addWidget(self.guide_hub_btn)
        links_layout.addWidget(self.guide_author_btn)
        links_layout.addWidget(self.guide_coffee_btn)
        links_layout.addStretch()

        guide_layout.addWidget(self.why_box)
        guide_layout.addWidget(self.guide_tips_box)
        guide_layout.addWidget(self.links_box)
        guide_layout.addStretch()
        self.tabs.addTab(guide_page, tr("tab.guide"))
        self.search_shortcut = QShortcut(QKeySequence.StandardKey.Find, self)
        self.search_shortcut.activated.connect(self.focus_search)
        self.import_shortcut = QShortcut(QKeySequence.StandardKey.Open, self)
        self.import_shortcut.activated.connect(self.import_profile)
        self.quit_shortcut = QShortcut(QKeySequence.StandardKey.Quit, self)
        self.quit_shortcut.activated.connect(self.quit_from_tray)
        self.feedback = FeedbackLabel("")
        self.feedback.setTextFormat(Qt.TextFormat.PlainText)
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)

        footer_widget = QWidget()
        footer_widget.setStyleSheet(FOOTER_BUTTON_STYLE)
        footer = QHBoxLayout(footer_widget)
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(6)
        self.author_button = QPushButton(tr("footer.author_label"))
        self.author_button.setIcon(QIcon(str(INNOVIBE_ICON)))
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
        self.update_accent_texts()

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

    def update_accent_texts(self) -> None:
        dark = self.palette().window().color().lightness() < 128
        accent = "#ffb347" if dark else "#e5470a"
        if hasattr(self, "edit_button"):
            self.edit_button.setIcon(build_eq_sliders_icon(accent))
        if hasattr(self, "tips_label"):
            self.tips_label.setText(tr("device.tips_body", accent=accent))
            self.why_label.setText(tr("help.why_body", accent=accent))
            self.guide_tips_label.setText(tr("help.tips_body", accent=accent))

    def apply_theme(self, theme_pref: str) -> None:
        dark = self.system_dark if theme_pref == "auto" else (theme_pref == "dark")
        app_instance = QApplication.instance()
        if app_instance is not None:
            app_instance.setPalette(build_innovibe_palette(dark))
        self.setStyleSheet(APP_STYLE)
        self.update_accent_texts()
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
        self.author_button.setText(tr("footer.author_label"))
        self.coffee_button.setText(tr("footer.coffee"))
        self.report_button.setText(tr("footer.report"))
        self.report_bug_action.setText(tr("footer.report_bug"))
        self.report_feature_action.setText(tr("footer.report_feature"))
        self.copy_diag_action.setText(tr("footer.copy_diag"))
        self.tabs.setTabText(0, tr("tab.tuning"))
        self.tabs.setTabText(1, tr("tab.device"))
        self.tabs.setTabText(2, tr("tab.guide"))
        self.why_box.setTitle(tr("help.why_group"))
        self.guide_tips_box.setTitle(tr("help.tips_group"))
        self.links_box.setTitle(tr("help.links_group"))
        self.guide_hub_btn.setText(tr("help.open_hub"))
        self.guide_author_btn.setText(tr("help.author_link"))
        self.guide_coffee_btn.setText(tr("help.coffee_link"))
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
        self.tips_box.setTitle(tr("device.tips_group"))
        self.update_accent_texts()
        for index, key in enumerate(("source.my_profiles", "source.autoeq_catalog")):
            self.source_group.button(index).setText(tr(key))
        self.profile_search.setPlaceholderText(tr("search.profiles_placeholder"))
        self.profile_search.setAccessibleName(tr("search.profiles_a11y"))
        self.fr_title_label.setText(tr("plot.fr_title"))
        self.correction_title.setText(tr("plot.eq_title"))
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
        self.tray.setToolTip("MOONDROP:Gravity Position")
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
        if (
            using_catalog
            and self.autoeq_panel.preview_entry is not None
            and not self.autoeq_panel.preview_curve
            and not self.autoeq_panel.preview_timer.isActive()
            and not self.autoeq_panel.preview_jobs
        ):
            self.autoeq_panel.preview_timer.start()
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
            context = tr("plot.profile_bands", count=len(profile.bands))
            if profile.source:
                context += f" · {profile.source}"
            self.profile_info.setText(context)
        elif not using_catalog:
            self.profile_info.setText("Wybrano fabryczny EQ" if profile else "")
        self.update_comparison()
        self.refresh_buttons()

    def update_comparison(self) -> None:
        selected = self.candidate_profile()
        waiting_for_fit = self.catalog_selected() and selected is None
        preview_entry = self.autoeq_panel.preview_entry if waiting_for_fit else None
        preview_curve = self.autoeq_panel.preview_curve if waiting_for_fit else []
        sources = (selected, self.readback_profile, self.factory_profile, waiting_for_fit, preview_entry, preview_curve)
        if sources == self.preview_sources:
            return
        self.preview_sources = sources

        self.preview_plot.set_factory(self.factory_profile)
        self.preview_plot.set_profile(selected)
        self.preview_plot.set_reference(self.readback_profile)
        measured = self.preview_plot.factory_points
        predicted = self.preview_plot.points
        raw_target = selected.target_curve if selected and selected.target_curve else preview_curve
        fit = fit_to_target(predicted or measured, raw_target)
        target_points = [(hz, db + fit.offset_db) for hz, db in raw_target] if fit else []
        target_label = (
            selected.target_name
            if selected and selected.target_name
            else (preview_entry.name if preview_entry is not None else tr("plot.key.target_default"))
        )
        self.preview_key.set_labels(
            (
                tr("plot.key.selected"),
                tr("plot.key.current_dsp"),
                tr("plot.key.measured"),
                tr("plot.key.target", name=target_label),
            )
        )
        self.preview_plot.set_target_points(target_points)
        summary = ""
        if fit and predicted:
            low = f"{fit.low_hz:g} Hz" if fit.low_hz < 1000 else f"{fit.low_hz / 1000:g} kHz"
            high = f"{fit.high_hz:g} Hz" if fit.high_hz < 1000 else f"{fit.high_hz / 1000:g} kHz"
            summary = tr("plot.fit_summary", rms=fit.rms_db, low=low, high=high)
            self.fit_summary.setToolTip(
                tr("plot.fit_details", offset=fit.offset_db, peak=fit.peak_db, freq=fit.peak_hz)
            )
        self.fit_summary.setText(summary)

        electrical = self.factory_profile if selected and selected.slot == 0 else selected
        self.correction_plot.set_primary_points(response_points(electrical, EQ_PLOT_FREQUENCIES) if electrical else [])
        self.correction_plot.set_reference_points(
            response_points(self.readback_profile, EQ_PLOT_FREQUENCIES) if self.readback_profile else []
        )
        preamp_parts = []
        if selected is not None and selected.preamp is not None:
            preamp_parts.append(tr("plot.preamp_profile", value=selected.preamp))
        if self.readback_profile is not None:
            preamp_parts.append(tr("plot.preamp_dsp", value=self.readback_profile.preamp))
        self.preamp_summary.setText(" · ".join(preamp_parts))

        notes = []
        if selected and selected.slot == dac.CUSTOM_SLOT and not selected.target_curve:
            notes.append(tr("plot.no_target"))
        if self.factory_profile is None and selected is not None and selected.slot != 0:
            notes.append(tr("plot.neutral_factory"))
        if measured:
            notes.append(tr("plot.measurement_note") + " · " + tr("plot.treble_note"))
        self.plot_legend.setText("\n".join(notes))
        plot_description = [*self.preview_key.labels[: 4 if target_points else 3], summary, *notes]
        self.preview_plot.setAccessibleDescription("\n".join(filter(None, plot_description)))

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
            self.connection.setText(error.split("\n\n", 1)[0] if error else "Podłącz MOONDROP:Gravity Position.")
            if self.tray:
                self.tray.setToolTip(f"MOONDROP:Gravity Position · {self.connection.text()}")
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
            self.tray.setToolTip(f"MOONDROP:Gravity Position · {self.active_profile.text()}")
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

    def import_profile_from_path(self, source: Path) -> bool:
        try:
            if source.suffix.casefold() == ".txt":
                bands, preamp = dac.parse_eqapo(str(source))
                for index in range(len(bands), dac.BAND_COUNT):
                    bands.append({"band": index + 1, "type": "PK", "freq": 1000, "q": 1, "gain": 0})
                profile = custom_profile(source.stem, dac.CUSTOM_SLOT, bands, 0 if preamp is None else preamp)
            else:
                profile = load_profile(source)
        except (OSError, ValueError, dac.HidError, SystemExit) as exc:
            self.feedback.setText(f"Błąd profilu. {exc}")
            return False
        if self.persist_profile(profile):
            self.tabs.setCurrentWidget(self.profile_page)
            self.switch_source(0)
            return True
        return False

    def import_profile(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self, "Importuj profil EQ", "", "Profile EQ (*.json *.txt);;JSON (*.json);;Equalizer APO (*.txt)"
        )
        if not path:
            return
        if self.import_profile_from_path(Path(path)):
            self.feedback.setText("Profil został dodany do biblioteki.")

    def dragEnterEvent(self, event) -> None:
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        if any(
            url.isLocalFile() and Path(url.toLocalFile()).suffix.casefold() in (".json", ".txt", ".csv") for url in urls
        ):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event) -> None:
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        for url in urls:
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            suffix = path.suffix.casefold()
            if suffix == ".json":
                if self.import_profile_from_path(path):
                    self.feedback.setText(tr("drop.loaded_profile", name=path.name))
                event.acceptProposedAction()
                return
            if suffix == ".txt":
                try:
                    dac.parse_eqapo(str(path))
                except (OSError, ValueError, SystemExit):
                    pass
                else:
                    if self.import_profile_from_path(path):
                        self.feedback.setText(tr("drop.loaded_profile", name=path.name))
                    event.acceptProposedAction()
                    return
            if suffix in (".csv", ".txt"):
                try:
                    read_target_curve(path)
                except (OSError, ValueError):
                    self.feedback.setText(tr("drop.unsupported", name=path.name))
                else:
                    self.tabs.setCurrentWidget(self.profile_page)
                    self.switch_source(1)
                    self.autoeq_panel.add_custom_target_path(path)
                    self.feedback.setText(tr("drop.loaded_target", name=path.name))
                event.acceptProposedAction()
                return
        super().dropEvent(event)

    def save_fit(self) -> None:
        profile = self.autoeq_panel.result
        if self.save_fit_button.isEnabled() and profile is not None and self.persist_profile(profile):
            self.feedback.setText("Profil zapisany w Moich profilach.")

    def export_selected(self) -> None:
        profile = self.selected_profile()
        if profile is None or profile.slot != dac.CUSTOM_SLOT:
            return
        try:
            notice = export_profile_dialog(self, "Eksportuj profil", profile)
        except OSError as exc:
            self.feedback.setText(f"Błąd eksportu profilu. {exc}")
        else:
            if notice:
                self.feedback.setText(notice)

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
                raise dac.HidError("Nie znaleziono MOONDROP:Gravity Position w sysfs.")
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
    app.setApplicationName("MOONDROP:Gravity Position")
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
