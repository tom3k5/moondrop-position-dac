#!/usr/bin/env python3
"""DSP Control — aplikacja GUI na Linux oraz tryb demonstracyjny bez USB."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from dataclasses import dataclass, replace
from functools import lru_cache
from html import escape
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote, urlencode
from uuid import uuid4

from PySide6.QtCore import (
    QAbstractListModel,
    QEvent,
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
    QSignalBlocker,
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
    QActionGroup,
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
    QAbstractSpinBox,
    QApplication,
    QBoxLayout,
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
    QStyleOptionButton,
    QStyleOptionTabWidgetFrame,
    QSystemTrayIcon,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import autoeq_catalog as catalog
import i18n
import moondrop_position as dac
from dac_devices import AmbiguousDac, DeviceTarget
from dac_transport import HidDeviceMissing, HidInterface, HidPermissionError
from device_specs import DEFAULT_MODEL_ID, DeviceSpec, default_device_spec, get_device_spec
from i18n import tr
from measurements import FIT_HIGH_HZ, curve_level, fit_to_target, read_squig_txt

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
BUILTIN_PROFILE = DATA_DIR / "profiles/moondrop-position-harman.json"
HARMAN_TARGET = DATA_DIR / "targets/Harman in-ear 2019.csv"
BUNDLED_CATALOG = DATA_DIR / "autoeq-catalog.json"
BUNDLED_TARGETS_DIR = DATA_DIR / "targets"
INNOVIBE_ICON = DATA_DIR / "innovibe.svg"


def _resolve_app_version() -> str:
    """Odczytuje aktualną wersję z AppStream metainfo (źródła lub Flatpak) albo pyproject.toml."""
    root = Path(__file__).resolve().parents[1]
    for metainfo in (
        root / "flatpak/pl.innovibe.DspControl.metainfo.xml",
        Path("/app/share/metainfo/pl.innovibe.DspControl.metainfo.xml"),
    ):
        if metainfo.is_file():
            with contextlib.suppress(OSError, ET.ParseError):
                release = ET.parse(metainfo).find("./releases/release")
                if release is not None and release.get("version"):
                    return release.get("version", "").strip()
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        with contextlib.suppress(OSError):
            match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(encoding="utf-8"), re.MULTILINE)
            if match:
                return match.group(1)
    return "0.4.1"


APP_VERSION = _resolve_app_version()
APP_STORAGE_NAME = "DSP Control"
LEGACY_STORAGE_NAME = "MOONDROP:Gravity Position"
SOURCE_LABELS = (
    ("source.my_profiles", "source.my_profiles_short", "tooltip.source_my_profiles"),
    ("source.autoeq_catalog", "source.autoeq_catalog_short", "tooltip.source_autoeq"),
)
GITHUB_REPO_URL = "https://github.com/tom3k5/moondrop-position-dac"
OFFICIAL_HUB_URL = "https://hub.moondroplab.tech/"
PROFILE_ROLE = Qt.ItemDataRole.UserRole
PATH_ROLE = Qt.ItemDataRole.UserRole + 1
PRIMARY_ACTION_STYLE = (
    "QPushButton { padding: 7px 16px; font-weight: 600; }"
    "QPushButton:enabled { background: palette(highlight); color: palette(highlighted-text);"
    " border: 1px solid palette(highlight); border-radius: 6px; }"
    "QPushButton:enabled:hover { background: palette(link); color: palette(base); border-color: palette(link); }"
    "QPushButton:enabled:pressed { background: palette(midlight); color: palette(text); }"
    "QPushButton:enabled:focus { border-color: palette(text); }"
)
SECONDARY_ACCENT_STYLE = (
    "QPushButton { padding: 6px 14px; font-weight: 600; }"
    "QPushButton:enabled { background: palette(button); color: palette(link);"
    " border: 1px solid palette(highlight); border-radius: 6px; }"
    "QPushButton:enabled:hover { background: palette(alternate-base); color: palette(text);"
    " border-color: palette(text); }"
    "QPushButton:enabled:pressed { background: palette(midlight); color: palette(text); }"
    "QPushButton:enabled:focus { border-color: palette(text); }"
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
    border-color: palette(link);
    background: palette(alternate-base);
}
QToolButton:checked:enabled {
    border-color: palette(link);
    background: palette(alternate-base);
}
QPushButton:pressed:enabled, QToolButton:pressed:enabled {
    border-color: palette(link);
    background: palette(midlight);
}
QPushButton:focus:enabled, QToolButton:focus:enabled {
    border-color: palette(text);
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
    border-color: palette(text);
}
QComboBox:on:enabled {
    background: palette(midlight);
}
QCheckBox:hover:enabled {
    color: palette(link);
}
QCheckBox:pressed:enabled {
    color: palette(text);
    background: palette(midlight);
}
QSlider::groove:horizontal {
    height: 5px;
    border-radius: 2px;
    background: palette(mid);
}
QSlider::sub-page:horizontal:enabled {
    border-radius: 2px;
    background: palette(link);
}
QSlider::handle:horizontal {
    width: 14px;
    margin: -5px 0;
    border: 1px solid palette(mid);
    border-radius: 7px;
    background: palette(button);
}
QSlider::handle:horizontal:enabled {
    border-color: palette(link);
}
QSlider::handle:horizontal:hover:enabled, QSlider::handle:horizontal:focus:enabled {
    border-color: palette(text);
    background: palette(highlight);
}
QSlider::handle:horizontal:pressed:enabled {
    border-color: palette(link);
    background: palette(text);
}
QListWidget, QListView {
    border: 1px solid palette(mid);
    border-radius: 8px;
    padding: 4px;
    background: palette(base);
}
QListWidget::item, QListView::item {
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 5px 8px;
}
QListWidget::item:hover:!selected:enabled, QListView::item:hover:!selected:enabled {
    border-color: palette(link);
    background: palette(alternate-base);
}
QListWidget::item:selected, QListView::item:selected {
    background: palette(highlight);
    color: palette(highlighted-text);
}
QListWidget::item:selected:focus, QListView::item:selected:focus {
    border-color: palette(highlighted-text);
}
QSplitter::handle {
    background: transparent;
    border: none;
}
QSplitter::handle:hover, QSplitter::handle:pressed {
    background: palette(alternate-base);
}
QFrame#sourceCard, QFrame#previewCard, QFrame#catalogList {
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
QTabBar::tab:hover:!selected:enabled {
    background: palette(alternate-base);
    border-color: palette(link);
}
QTabBar::tab:selected {
    border-color: palette(mid);
    border-bottom-color: palette(window);
    background: palette(window);
    font-weight: 600;
}
QTabBar::tab:pressed:enabled {
    background: palette(midlight);
}
QTabBar::tab:focus:selected {
    border-top-color: palette(text);
}
QMenu::item:selected:enabled {
    background: palette(highlight);
    color: palette(highlighted-text);
}
QMenu::item:disabled {
    color: palette(placeholder-text);
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
    "QPushButton:hover:!checked:enabled { border-color: palette(link); background: palette(alternate-base); }"
    "QPushButton:checked { border-color: palette(highlight); background: palette(highlight);"
    " color: palette(highlighted-text); }"
    "QPushButton:enabled:pressed { background: palette(midlight); color: palette(text); }"
    "QPushButton:enabled:focus { border-color: palette(text); }"
)
STATUS_PILL_STYLE = "border-radius: 10px; padding: 4px 10px; background: palette(alternate-base);"


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
            QPalette.ColorRole.HighlightedText: "#1c1917",
            QPalette.ColorRole.Link: "#a83a08",
            QPalette.ColorRole.LinkVisited: "#c23b08",
        }
        disabled_text = "#a8a29e"
    for role, hex_color in colors.items():
        palette.setColor(role, QColor(hex_color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(disabled_text))
    return palette


def size_to_screen(window: QWidget, width: int, height: int) -> None:
    screen = window.parentWidget().screen() if window.parentWidget() else window.screen()
    if screen is not None:
        work_area = screen.availableGeometry()
        width = min(width, max(1, work_area.width() - 32))
        height = min(height, max(1, work_area.height() - 48))
    window.setMinimumSize(window.minimumSize().boundedTo(QSize(width, height)))
    window.resize(width, height)


def scroll_content(content: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setWidget(content)
    return scroll


def _read_settings(settings_path: Path) -> dict:
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write_settings(settings_path: Path, data: dict) -> None:
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_theme_preference(settings_path: Path) -> str:
    value = _read_settings(settings_path).get("theme", "auto")
    return value if value in ("auto", "dark", "light") else "auto"


def save_theme_preference(settings_path: Path, theme: str) -> None:
    data = _read_settings(settings_path)
    data["theme"] = theme if theme in ("auto", "dark", "light") else "auto"
    _write_settings(settings_path, data)


RELEASES_LATEST_URL = "https://github.com/tom3k5/moondrop-position-dac/releases/latest"


def parse_semver_tuple(version: str) -> tuple[int, ...]:
    cleaned = version.strip().lstrip("vV")
    nums = [int(part) for part in re.findall(r"\d+", cleaned.split("-", 1)[0])]
    return tuple(nums)


def is_newer_version(latest: str, current: str = APP_VERSION) -> bool:
    lat = parse_semver_tuple(latest)
    cur = parse_semver_tuple(current)
    return bool(lat and cur and lat > cur)


def check_latest_release(url: str = RELEASES_LATEST_URL, timeout: int = 6) -> str | None:
    """Sprawdza najnowszy tag wydania przez przekierowanie HTTPS bez użycia REST API GitHuba."""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "dsp-control"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            final_url = resp.geturl()
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    tag = final_url.rstrip("/").rsplit("/", 1)[-1]
    return tag.lstrip("vV") if re.search(r"\d+\.\d+", tag) else None


def load_auto_update_check(settings_path: Path) -> bool:
    return bool(_read_settings(settings_path).get("auto_update_check", False))


def save_auto_update_check(settings_path: Path, enabled: bool) -> None:
    data = _read_settings(settings_path)
    data["auto_update_check"] = bool(enabled)
    _write_settings(settings_path, data)


def load_last_profile_for_model(settings_path: Path, model_id: str) -> str | None:
    mapping = _read_settings(settings_path).get("last_profile_by_model")
    if isinstance(mapping, dict):
        name = mapping.get(model_id)
        if isinstance(name, str) and name.strip():
            return name
    return None


def save_last_profile_for_model(settings_path: Path, model_id: str, profile_name: str) -> None:
    data = _read_settings(settings_path)
    mapping = data.get("last_profile_by_model")
    if not isinstance(mapping, dict):
        mapping = {}
    if mapping.get(model_id) == profile_name:
        return
    mapping[model_id] = profile_name
    data["last_profile_by_model"] = mapping
    _write_settings(settings_path, data)


@dataclass(frozen=True)
class HeadphoneSelection:
    mode: str  # "default" | "flat" | "autoeq" | "file"
    name: str = ""
    source: str = ""
    path: str = ""
    revision: str = ""
    form: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "mode": self.mode,
            "name": self.name,
            "source": self.source,
            "path": self.path,
            "revision": self.revision,
            "form": self.form,
        }

    @classmethod
    def from_dict(cls, raw: object, default_mode: str) -> HeadphoneSelection:
        if not isinstance(raw, dict):
            return cls(mode=default_mode)
        mode = str(raw.get("mode", default_mode))
        if mode not in ("default", "flat", "autoeq", "file"):
            mode = default_mode
        if mode in ("autoeq", "file") and not str(raw.get("path", "")).strip():
            mode = default_mode
        return cls(
            mode=mode,
            name=str(raw.get("name", "")),
            source=str(raw.get("source", "")),
            path=str(raw.get("path", "")),
            revision=str(raw.get("revision", "")),
            form=str(raw.get("form", "")),
        )

    def key(self) -> tuple[str, str]:
        return (self.mode, self.path)


def load_headphone_selection(settings_path: Path, spec: DeviceSpec) -> HeadphoneSelection:
    if not spec.allows_headphone_selection:
        return HeadphoneSelection(mode="default", name=spec.display_name)
    raw_map = _read_settings(settings_path).get("connected_headphones", {})
    raw = raw_map.get(spec.model_id) if isinstance(raw_map, dict) else None
    sel = HeadphoneSelection.from_dict(raw, spec.default_headphone_mode)
    if sel.mode == "default" and not spec.has_default_headphone:
        return HeadphoneSelection(mode="flat")
    return sel


RECENT_HEADPHONES_LIMIT = 3


def load_recent_headphones(
    settings_path: Path, spec: DeviceSpec, *, limit: int = RECENT_HEADPHONES_LIMIT
) -> list[HeadphoneSelection]:
    if not spec.allows_headphone_selection:
        return []
    raw_map = _read_settings(settings_path).get("recent_headphones", {})
    raw_list = raw_map.get(spec.model_id, []) if isinstance(raw_map, dict) else []
    if not isinstance(raw_list, list):
        return []
    items: list[HeadphoneSelection] = []
    seen: set[tuple[str, str]] = set()
    for entry in raw_list:
        sel = HeadphoneSelection.from_dict(entry, "flat")
        if sel.mode in ("autoeq", "file") and sel.key() not in seen:
            seen.add(sel.key())
            items.append(sel)
    return items[:limit]


def save_headphone_selection(settings_path: Path, spec: DeviceSpec, selection: HeadphoneSelection) -> None:
    if not spec.allows_headphone_selection:
        return
    data = _read_settings(settings_path)
    connected = data.get("connected_headphones")
    if not isinstance(connected, dict):
        connected = {}
    connected[spec.model_id] = selection.to_dict()
    data["connected_headphones"] = connected
    if selection.mode in ("autoeq", "file") and selection.path:
        recent_map = data.get("recent_headphones")
        if not isinstance(recent_map, dict):
            recent_map = {}
        existing = [
            HeadphoneSelection.from_dict(item, "flat")
            for item in (recent_map.get(spec.model_id) or [])
            if isinstance(item, dict)
        ]
        updated = [selection] + [
            item for item in existing if item.mode in ("autoeq", "file") and item.key() != selection.key()
        ]
        recent_map[spec.model_id] = [item.to_dict() for item in updated[:RECENT_HEADPHONES_LIMIT]]
        data["recent_headphones"] = recent_map
    _write_settings(settings_path, data)


@lru_cache(maxsize=16)
def load_measurement_curve_from_path(path_str: str) -> tuple[tuple[float, float], ...]:
    try:
        freqs, dbs = read_squig_txt(Path(path_str))
    except (OSError, ValueError):
        return ()
    return tuple((hz, db) for hz, db in zip(freqs, dbs, strict=False) if 20 <= hz <= 20000 and math.isfinite(db))


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
    (1, "S16_LE", 16),
    (2, "S24_3LE", 24),
    (3, "S32_LE", 32),
)
UAC2_SAMPLE_RATES = (44100, 48000, 96000, 192000, 384000)
AUTOEQ_FIT_RANGES = (
    ("autoeq.fit_full", (20000, 8)),
    ("autoeq.fit_6k", (6000, 6)),
    ("autoeq.fit_4k", (4000, 6)),
    ("autoeq.fit_2k", (2000, 5)),
)
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


def default_custom_bands(spec: DeviceSpec | None = None) -> list[dict]:
    if spec is not None:
        return spec.default_custom_bands()
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


def read_playback_quality(
    *, interface: HidInterface | None = None, demo: bool = False, demo_forced_rate: int = 0
) -> PlaybackQuality:
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
    if interface is not None:
        usb_device = next((parent for parent in interface.instance.parents if (parent / "idVendor").is_file()), None)
        for card in sorted(Path("/sys/class/sound").glob("card*")):
            try:
                sound_device = (card / "device").resolve(strict=True)
                if usb_device is None or usb_device not in (sound_device, *sound_device.parents):
                    continue
                stream_file = Path("/proc/asound") / card.name / "stream0"
                alsa_info = parse_alsa_stream0(stream_file.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
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
    fit_range: tuple[int, int] | None = None
    sample_rate_hz: float = dac.COEFF_FS
    model_id: str | None = None
    headphone_name: str | None = None
    headphone_selection: dict[str, str] | None = None
    muted_bands: dict[str, dict] | None = None

    def matches_eq(self, state: DeviceState) -> bool:
        if state.model_name != dac.POSITION_NAME:
            expected_slot = state.custom_slot if self.slot == dac.CUSTOM_SLOT else self.slot
            if state.slot != expected_slot or len(state.bands) != len(self.bands):
                return False
            for index, (actual, expected) in enumerate(zip(state.bands, self.bands, strict=True)):
                if actual is None:
                    return False
                if (
                    actual.get("band") != index + 1
                    or actual.get("type") != expected.get("type")
                    or actual.get("freq") != round(float(expected["freq"]))
                    or abs(float(actual["gain"]) - float(expected["gain"])) > 0.06
                    or abs(float(actual["q"]) - float(expected["q"])) > 0.01
                ):
                    return False
            return True
        return state.slot == self.slot and (
            self.slot == 0
            or (
                state.bands == [dac.quantized_band(band) for band in self.bands]
                and dac.preamp_matches(state.preamp, self.preamp, allow_half_db=True)
                and all(
                    coeff is None or state.coefficients[index : index + 1] == (coeff,)
                    for index, expected in enumerate(map(dac.expected_band_readback, self.bands))
                    for coeff in (
                        self.coefficients[index]
                        if len(self.coefficients) == len(self.bands)
                        else expected.get("coefficients"),
                    )
                )
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
    interface: HidInterface | None = None
    model_name: str = dac.POSITION_NAME
    experimental: bool = False
    band_count: int = dac.BAND_COUNT
    custom_slot: int = dac.CUSTOM_SLOT
    slot_names: dict[int, str] | None = None
    sample_rate_hz: float = dac.COEFF_FS
    model_id: str = DEFAULT_MODEL_ID

    @property
    def target(self) -> DeviceTarget:
        return self.interface or self.path


def infer_profile_model_id(meta: dict, bands: list[dict]) -> str | None:
    explicit = meta.get("model_id")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    usb = str(meta.get("usb") or "").strip().lower()
    if usb == "31b2:0113":
        return "moondrop-chu2-dsp"
    if usb == "3302:12c5":
        return "moondrop-echo-a"
    if usb == "35d8:0123":
        return "moondrop-position"
    device = str(meta.get("device") or "").strip().lower()
    if "chu" in device:
        return "moondrop-chu2-dsp"
    if "echo-a" in device or "echo a" in device:
        return "moondrop-echo-a"
    if "position" in device:
        return "moondrop-position"
    if len(bands) == 5:
        return "moondrop-chu2-dsp"
    return None


def load_profile(
    path: Path, name: str | None = None, *, pad_bands: bool = False, spec: DeviceSpec | None = None
) -> Profile:
    try:
        bands, meta = dac.load_eq_file(str(path))
    except SystemExit as exc:
        raise ValueError(str(exc)) from exc
    inferred_model = infer_profile_model_id(meta, bands)
    resolved_spec = spec or (get_device_spec(inferred_model) if inferred_model else default_device_spec())
    slot = meta.get("slot", resolved_spec.dsp.slots.custom)
    preamp = meta.get("preamp")
    if pad_bands and len(bands) < resolved_spec.dsp.band_count:
        neutral = default_custom_bands(resolved_spec)
        bands.extend(neutral[len(bands) :])
    stored_name = meta.get("name")
    if not isinstance(stored_name, str) or not stored_name.strip():
        stored_name = path.stem
    profile = custom_profile(
        name or stored_name,
        slot,
        bands,
        preamp,
        meta.get("global_gain_db"),
        meta.get("mic_gain_raw"),
        model_id=inferred_model or resolved_spec.model_id,
        spec=resolved_spec,
    )
    source = meta.get("source")
    target_name = meta.get("target_name")
    target = valid_curve(meta.get("target_curve", ()))
    fit_meta = meta.get("meta")
    stored_range = fit_meta.get("fit_range") if isinstance(fit_meta, dict) else None
    valid_ranges = [limits for _, limits in AUTOEQ_FIT_RANGES] + [
        (fr.max_fc, fr.bands) for fr in resolved_spec.acoustics.fit_ranges
    ]
    fit_range = next((limits for limits in valid_ranges if list(limits) == stored_range), None)
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
    sample_rate = meta.get("sample_rate_hz")
    if not isinstance(sample_rate, (int, float)) or sample_rate <= 0:
        sample_rate = resolved_spec.dsp.sample_rate_hz
    headphone_name = meta.get("headphone_name")
    hp_sel = meta.get("headphone_selection")
    muted_raw = meta.get("muted_bands")
    muted_bands = (
        {str(k): dict(v) for k, v in muted_raw.items() if isinstance(v, dict)} if isinstance(muted_raw, dict) else None
    )
    return replace(
        profile,
        source=source if isinstance(source, str) else None,
        target_name=target_name if isinstance(target_name, str) else None,
        target_curve=target,
        fit_range=fit_range,
        sample_rate_hz=float(sample_rate),
        model_id=inferred_model or resolved_spec.model_id,
        headphone_name=headphone_name if isinstance(headphone_name, str) and headphone_name.strip() else None,
        headphone_selection=dict(hp_sel) if isinstance(hp_sel, dict) else None,
        muted_bands=muted_bands or None,
    )


def custom_profile(
    name: str,
    slot: int,
    bands: list[dict],
    preamp: float,
    global_gain_db: int | None = None,
    mic_gain_raw: int | None = None,
    *,
    model_id: str | None = None,
    spec: DeviceSpec | None = None,
) -> Profile:
    resolved = spec or get_device_spec(model_id)
    if resolved.model_id == DEFAULT_MODEL_ID:
        dac.validate_profile(bands, slot, preamp)
        if slot != dac.CUSTOM_SLOT or len(bands) != dac.BAND_COUNT or type(preamp) not in (int, float):
            raise ValueError("Profil musi zawierać osiem pasm, pre-gain i dotyczyć slotu Custom.")
        if not -128 <= preamp <= 0 or any(
            b["type"] not in {"PK", "LSQ", "HSQ", "LP", "HP"} or not -18 <= b["gain"] <= 12 for b in bands
        ):
            raise ValueError("Position obsługuje PK, LSQ, HSQ, LP i HP, gain od −18 do +12 dB i pre-gain do 0 dB.")
    else:
        expected_slot = resolved.dsp.slots.custom
        if slot not in (expected_slot, dac.CUSTOM_SLOT) or len(bands) != resolved.dsp.band_count:
            raise ValueError(
                f"Profil dla {resolved.display_name} musi zawierać {resolved.dsp.band_count} pasm "
                "i dotyczyć slotu Custom."
            )
        if type(preamp) not in (int, float):
            raise ValueError("Profil musi zawierać poprawny pre-gain.")
        min_pre, max_pre = resolved.dsp.preamp_range_db
        if not min_pre <= float(preamp) <= max_pre:
            raise ValueError(f"{resolved.display_name} obsługuje pre-gain w zakresie od {min_pre:g} do {max_pre:g} dB.")
        min_g, max_g = resolved.dsp.gain_range_db
        allowed = set(resolved.dsp.supported_types)
        if any(b.get("type") not in allowed or not min_g <= float(b.get("gain", 0)) <= max_g for b in bands):
            raise ValueError(
                f"{resolved.display_name} obsługuje filtry {', '.join(resolved.dsp.supported_types)} "
                f"oraz gain od {min_g:g} do {max_g:g} dB."
            )
        slot = expected_slot
    if global_gain_db is not None and (type(global_gain_db) is not int or not -18 <= global_gain_db <= 0):
        raise ValueError("Global gain w profilu musi być liczbą całkowitą od −18 do 0 dB.")
    if mic_gain_raw is not None and (type(mic_gain_raw) is not int or mic_gain_raw not in MIC_GAIN_REQUESTS):
        raise ValueError("Profil zawiera niepotwierdzony kod wzmocnienia mikrofonu.")
    return Profile(
        name,
        slot,
        bands,
        preamp,
        global_gain_db,
        mic_gain_raw,
        sample_rate_hz=resolved.dsp.sample_rate_hz,
        model_id=resolved.model_id,
    )


def open_dac(target: DeviceTarget | None = None):
    try:
        return dac.connect_device(target)
    except AmbiguousDac as exc:
        raise dac.HidError("Podłącz jeden obsługiwany DAC.") from exc
    except HidPermissionError as exc:
        raise dac.HidError("Brak dostępu do DAC-a. Sprawdź regułę udev na hoście.") from exc
    except HidDeviceMissing as exc:
        raise dac.HidError(
            "System widzi DAC, ale węzeł HID jest niedostępny. "
            "Sprawdź dostęp do urządzenia w Flatpaku lub podłącz DAC ponownie."
        ) from exc


def read_state(dev) -> DeviceState:
    slot = dev.slot()
    firmware = dev.version()
    preamp = dev.preamp()
    band_count = getattr(dev, "band_count", dac.BAND_COUNT)
    bands = []
    coefficients = []
    for index in range(band_count):
        band = dev.read_band(index, include_coefficients=True)
        if band is not None:
            coefficients.append(band.pop("coefficients", b""))
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
    return DeviceState(
        dev.path,
        firmware,
        slot,
        preamp,
        bands,
        global_gain_db,
        mic_gain_raw,
        tuple(coefficients),
        getattr(dev, "interface", None),
        getattr(dev, "model_name", dac.POSITION_NAME),
        bool(getattr(dev, "experimental", False)),
        band_count,
        getattr(dev, "custom_slot", dac.CUSTOM_SLOT),
        dict(getattr(dev, "slot_names", dac.SLOT_NAMES)),
        float(getattr(dev, "sample_rate_hz", dac.COEFF_FS)),
        str(getattr(dev, "model_id", DEFAULT_MODEL_ID)),
    )


@dataclass(frozen=True)
class DeviceChoice:
    target: DeviceTarget
    name: str


def hardware_choices() -> list[DeviceChoice]:
    choices = []
    for item in dac.DEVICE_REGISTRY.detect():
        label = item.model.display_name
        if getattr(item.model.connect, "experimental", False):
            label = f"{label} [Experimental]"
        choices.append(DeviceChoice(item.interface, label))
    return choices


def poll_devices(
    list_devices, open_device, target: DeviceTarget | None
) -> tuple[list[DeviceChoice], DeviceState | None, str]:
    choices = list_devices()
    if target is None and len(choices) == 1:
        target = choices[0].target
    if target is None or all(choice.target != target for choice in choices):
        return choices, None, ""
    try:
        dev = open_device(target)
        if dev is not None:
            with dev:
                return choices, read_state(dev), ""
    except dac.HidError as exc:
        return choices, None, str(exc)
    return choices, None, ""


def build_diagnostic_report(scan=None, open_device=None) -> dict:
    """Build a rootless diagnostic report covering sysfs hidraw nodes and live DSP state."""
    if scan is None:
        from dac_transport import scan_hidraw

        scan_fn = scan_hidraw
    else:
        scan_fn = scan
    open_fn = open_device or open_dac

    interfaces = []
    for iface in scan_fn():
        matched = [model for model in dac.DEVICE_REGISTRY.models if model.matches(iface)]
        interfaces.append(
            {
                "node": iface.node,
                "vid_pid": f"{iface.vendor_id:04x}:{iface.product_id:04x}",
                "name": iface.name,
                "readable": os.access(iface.node, os.R_OK),
                "writable": os.access(iface.node, os.W_OK),
                "matched_model": matched[0].model_id if len(matched) == 1 else None,
                "reports": sorted(
                    ({"id": f"0x{r.report_id:02x}", "kind": r.kind, "length": r.length} for r in iface.reports),
                    key=lambda item: (item["id"], item["kind"]),
                ),
            }
        )

    report: dict[str, object] = {
        "app_version": APP_VERSION,
        "hidraw_interfaces": interfaces,
    }
    try:
        dev = open_fn()
        if dev is None:
            report["open_error"] = "Nie znaleziono obsługiwanego DAC-a w sysfs."
            return report
        with dev:
            state = read_state(dev)
            report.update({key: value for key, value in vars(state).items() if key not in ("interface", "slot_names")})
            report["coefficients"] = [band.hex() for band in state.coefficients]
    except dac.HidError as exc:
        report["open_error"] = str(exc)
    return report


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


def update_global_gain(open_device, device: DeviceTarget, target: int) -> DeviceState:
    with open_device(device) as dev:
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


def update_mic_gain(open_device, device: DeviceTarget, target: int) -> DeviceState:
    with open_device(device) as dev:
        if dev.version() not in ("0.5", "demo"):
            raise dac.HidError("Brak potwierdzonego sterowania mikrofonem dla tego firmware.")
        apply_mic_gain(dev, target)
        state = read_state(dev)
        if state.mic_gain_raw != target:
            raise dac.HidError("Końcowy odczyt nie potwierdził wzmocnienia mikrofonu.")
        return state


def previous_profile_from_state(state: DeviceState) -> Profile | None:
    mic_gain_raw = state.mic_gain_raw if state.mic_gain_raw in MIC_GAIN_REQUESTS else None
    if state.slot == 0:
        return Profile(
            tr("tuning.factory"),
            0,
            [],
            None,
            global_gain_db=state.global_gain_db,
            mic_gain_raw=mic_gain_raw,
        )
    if (
        state.slot == dac.CUSTOM_SLOT
        and len(state.bands) == dac.BAND_COUNT
        and len(state.coefficients) == dac.BAND_COUNT
        and all(band is not None and band["type"] in dac.TYPE_TO_CODE for band in state.bands)
    ):
        return Profile(
            tr("tuning.custom_settings"),
            dac.CUSTOM_SLOT,
            [dict(band) for band in state.bands],
            state.preamp,
            global_gain_db=state.global_gain_db,
            mic_gain_raw=mic_gain_raw,
            coefficients=state.coefficients,
        )
    return None


def _reconnect_after_save(open_device, model_id: str | None, *, timeout_s: float = 4.0) -> DeviceState:
    """Wait for a device that restarts USB on flash commit (e.g. CHU II DSP) and read its state."""
    deadline = time.monotonic() + timeout_s
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        time.sleep(0.25)
        for detected in dac.DEVICE_REGISTRY.detect():
            if model_id is not None and detected.model.model_id != model_id:
                continue
            try:
                dev = open_device(detected.interface)
                if dev is not None:
                    with dev:
                        return read_state(dev)
            except dac.HidError as exc:
                last_error = exc
    detail = f" ({last_error})" if last_error is not None else ""
    raise dac.HidError(f"DAC nie wrócił po restarcie USB po zapisie do flash{detail}.")


def _write_profile_on_device(dev, profile: Profile, state: DeviceState, open_device=None) -> DeviceState:
    if profile.matches(state):
        return state
    if profile.global_gain_db is not None and state.global_gain_db is None:
        raise dac.HidError("Brak odczytu global gainu wymaganego przez profil.")
    if profile.mic_gain_raw is not None and state.mic_gain_raw is None:
        raise dac.HidError("Brak odczytu wzmocnienia mikrofonu wymaganego przez profil.")
    reconnected = False
    if not profile.matches_eq(state):
        if profile.slot == 0 and state.custom_slot != 0:
            dac.activate_slot(dev, 0)
            dev.save()
            time.sleep(dac.DELAY_FLASH_MS / 1000)
        else:
            bands = (
                [
                    {**band, "coefficients": coeff}
                    for band, coeff in zip(profile.bands, profile.coefficients, strict=True)
                ]
                if len(profile.coefficients) == len(profile.bands)
                else profile.bands
            )
            dac.write_profile(dev, bands, profile.preamp, allow_half_db=True)
            reconnected = bool(getattr(dev, "reconnect_on_save", False))
    if reconnected:
        if open_device is None:
            raise dac.HidError("Urządzenie zrestartowało USB po zapisie; odczytaj stan ponownie.")
        updated = _reconnect_after_save(open_device, getattr(dev, "model_id", None))
    else:
        if profile.global_gain_db is not None:
            apply_global_gain(dev, profile.global_gain_db)
        if profile.mic_gain_raw is not None:
            apply_mic_gain(dev, profile.mic_gain_raw)
        updated = read_state(dev)
    if not profile.matches(updated):
        raise dac.HidError("DAC nie potwierdził zastosowania profilu.")
    return updated


def apply_profile(open_device, device: DeviceTarget, profile: Profile) -> DeviceState:
    with open_device(device) as dev:
        return _write_profile_on_device(dev, profile, read_state(dev), open_device=open_device)


def apply_profile_with_previous(
    open_device, device: DeviceTarget, profile: Profile
) -> tuple[Profile | None, DeviceState]:
    with open_device(device) as dev:
        before = read_state(dev)
        previous = previous_profile_from_state(before)
        after = _write_profile_on_device(dev, profile, before, open_device=open_device)
        return previous, after


@dataclass
class LiveEqSnapshot:
    target: DeviceTarget
    slot: int
    preamp: float
    custom: Profile


def begin_live_eq(open_device, device: DeviceTarget) -> LiveEqSnapshot:
    with open_device(device) as dev:
        original_slot = dev.slot()
        original_preamp = dev.preamp()
        if original_slot not in (0, dac.CUSTOM_SLOT):
            raise dac.HidError(f"Odsłuch nie obsługuje slotu {original_slot}.")
        try:
            if original_slot != dac.CUSTOM_SLOT:
                dac.activate_slot(dev, dac.CUSTOM_SLOT)
            bands = dev.read_eq(dac.BAND_COUNT, include_coefficients=True)
            if len(bands) != dac.BAND_COUNT:
                raise dac.HidError("Brak kompletnego EQ w slocie Custom. Wgraj najpierw pełny profil.")
            custom = Profile("EQ przed odsłuchem", dac.CUSTOM_SLOT, bands, dev.preamp())
            dac.validate_profile(custom.bands, custom.slot, custom.preamp)
        except (OSError, ValueError, dac.HidError):
            if original_slot != dac.CUSTOM_SLOT:
                dac.activate_slot(dev, original_slot)
                dac.apply_preamp(dev, original_preamp)
            raise
        return LiveEqSnapshot(device, original_slot, original_preamp, custom)


def listen_live_eq(
    open_device, snapshot: LiveEqSnapshot, profile: Profile, previous: Profile, previous_preamp: float
) -> float:
    with open_device(snapshot.target) as dev:
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
    with open_device(snapshot.target) as dev:
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


def restore_defaults(open_device, device: DeviceTarget) -> DeviceState:
    with open_device(device) as dev:
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


def read_custom_backup(open_device, device: DeviceTarget) -> Profile:
    with open_device(device) as dev:
        state = read_state(dev)
        if state.slot != dac.CUSTOM_SLOT or any(band is None for band in state.bands):
            raise dac.HidError("Kopia wymaga aktywnego slotu Custom i ośmiu odczytanych pasm.")
        bands = [band for band in state.bands if band is not None]
        name = "position-custom-demo" if state.path == "demo" else "position-custom"
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
    if profile.model_id:
        data["model_id"] = profile.model_id
    if profile.headphone_name:
        data["headphone_name"] = profile.headphone_name
    if profile.headphone_selection:
        data["headphone_selection"] = profile.headphone_selection
    if profile.muted_bands:
        data["muted_bands"] = profile.muted_bands
    if profile.sample_rate_hz:
        data["sample_rate_hz"] = profile.sample_rate_hz
    if profile.source:
        data["source"] = profile.source
    if profile.target_curve:
        data["target_name"] = profile.target_name
        data["target_curve"] = profile.target_curve
    if profile.fit_range is not None:
        data["meta"] = {"fit_range": profile.fit_range}
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


def apply_macro_tone(
    bands: list[dict],
    *,
    bass_db: float = 0.0,
    mid_db: float = 0.0,
    treble_db: float = 0.0,
    tilt_db_per_oct: float = 0.0,
    spec: DeviceSpec | None = None,
) -> list[dict]:
    """Deterministycznie modyfikuje pasma EQ o korekty makro (Bas, Średnica, Góra, Tilt)."""
    resolved = spec or default_device_spec()
    gain_min, gain_max = resolved.dsp.gain_range_db
    allowed = set(resolved.dsp.supported_types)
    updated = [dict(band) for band in bands]

    if abs(bass_db) < 1e-6 and abs(mid_db) < 1e-6 and abs(treble_db) < 1e-6 and abs(tilt_db_per_oct) < 1e-6:
        return updated

    # Jeśli brak pasma basowego/wysokotonowego przy niezerowym Bas/Góra, wykorzystaj neutralne pasmo 0 dB.
    def _activate_neutral(target_freq: float, prefer_type: str) -> None:
        if any(
            (target_freq <= 250.0 and b.get("freq", 1000) <= 250.0 and abs(float(b.get("gain", 0.0))) > 1e-6)
            or (target_freq >= 3500.0 and b.get("freq", 1000) >= 3500.0 and abs(float(b.get("gain", 0.0))) > 1e-6)
            for b in updated
        ):
            return
        for b in updated:
            if abs(float(b.get("gain", 0.0))) < 1e-6 and b.get("type", "PK") not in ("LP", "HP"):
                b["type"] = prefer_type if prefer_type in allowed else "PK"
                b["freq"] = round(target_freq)
                b["q"] = 0.71
                return

    if abs(bass_db) >= 1e-6:
        _activate_neutral(105.0, "LSQ")
    if abs(treble_db) >= 1e-6:
        _activate_neutral(6000.0, "HSQ")

    for b in updated:
        ftype = b.get("type", "PK")
        if ftype in ("LP", "HP"):
            continue
        freq = max(20.0, min(20000.0, float(b.get("freq", 1000.0))))
        delta = 0.0
        if abs(bass_db) >= 1e-6:
            if ftype == "LSQ":
                delta += bass_db
            elif freq <= 250.0:
                delta += bass_db * math.exp(-0.5 * (math.log2(freq / 80.0) / 1.1) ** 2)
        if abs(mid_db) >= 1e-6 and ftype == "PK" and 250.0 <= freq <= 3500.0:
            delta += mid_db * math.exp(-0.5 * (math.log2(freq / 1000.0) / 0.9) ** 2)
        if abs(treble_db) >= 1e-6:
            if ftype == "HSQ":
                delta += treble_db
            elif freq >= 3500.0:
                delta += treble_db * math.exp(-0.5 * (math.log2(freq / 8000.0) / 1.1) ** 2)
        if abs(tilt_db_per_oct) >= 1e-6:
            delta += tilt_db_per_oct * math.log2(freq / 1000.0)
        new_gain = max(gain_min, min(gain_max, float(b.get("gain", 0.0)) + delta))
        b["gain"] = round(new_gain, 2)
    return updated


def export_library_zip(library_dir: Path, dest_zip: Path) -> int:
    """Eksportuje wszystkie profile użytkownika (*.json) z biblioteki do archiwum .zip."""
    files = sorted(p for p in library_dir.glob("*.json") if p.is_file())
    manifest = {
        "format": "dsp-control-library",
        "version": 1,
        "app_version": APP_VERSION,
        "count": len(files),
        "files": [p.name for p in files],
    }
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
        for p in files:
            zf.write(p, arcname=f"profiles/{p.name}")
    return len(files)


def import_library_zip(src_zip: Path, library_dir: Path, *, conflict: str = "copy") -> tuple[int, int]:
    """Importuje profile z archiwum .zip do biblioteki. Zwraca (zaimportowane, pominięte)."""
    if conflict not in ("copy", "skip", "overwrite"):
        raise ValueError(f"Unsupported conflict strategy: {conflict}")
    library_dir.mkdir(parents=True, exist_ok=True)
    imported = 0
    skipped = 0
    with zipfile.ZipFile(src_zip, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = Path(info.filename)
            if rel.is_absolute() or ".." in rel.parts or rel.name == "manifest.json" or rel.suffix.lower() != ".json":
                continue
            raw = zf.read(info)
            try:
                data = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                skipped += 1
                continue
            if not isinstance(data, dict) or not isinstance(data.get("bands"), list):
                skipped += 1
                continue
            target = library_dir / rel.name
            if target.exists():
                if conflict == "skip":
                    skipped += 1
                    continue
                if conflict == "copy":
                    stem = rel.stem
                    idx = 2
                    while (library_dir / f"{stem}-{idx}.json").exists():
                        idx += 1
                    target = library_dir / f"{stem}-{idx}.json"
            target.write_bytes(raw)
            imported += 1
    return imported, skipped


class DemoDevice:
    path = "demo"

    def __init__(self, model_id: str = DEFAULT_MODEL_ID):
        self.spec = get_device_spec(model_id)
        self.model_id = self.spec.model_id
        self.model_name = self.spec.display_name
        self.experimental = self.spec.experimental
        self.band_count = self.spec.dsp.band_count
        self.custom_slot = self.spec.dsp.slots.custom
        self.factory_slot = self.spec.dsp.slots.factory
        self.slot_names = dict(self.spec.dsp.slots.names)
        self.sample_rate_hz = self.spec.dsp.sample_rate_hz
        self.reconnect_on_save = self.spec.dsp.reconnect_on_save
        self.active_slot = self.factory_slot if self.factory_slot is not None else self.custom_slot
        self.factory_bands = self.spec.factory_bands_copy() or self.spec.default_custom_bands()
        self.custom_bands = self.spec.default_custom_bands()
        self.custom_coefficients = [
            coefficients_for_band(band, sample_rate_hz=self.sample_rate_hz) for band in self.custom_bands
        ]
        self.custom_preamp = 0.0
        self.default_preamp = 0.0
        self.output_gain = 0 if self.spec.dsp.controls.global_gain_db is not None else None
        self.microphone_gain = 0 if self.spec.dsp.controls.mic_gain else None

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
        return (
            self.default_preamp
            if self.factory_slot is not None and self.active_slot == self.factory_slot
            else self.custom_preamp
        )

    def set_preamp(self, db, *, legacy=True):
        if self.factory_slot is not None and self.active_slot == self.factory_slot:
            self.default_preamp = round(db * 256) / 256
        else:
            self.custom_preamp = round(db * 256) / 256

    def global_gain(self):
        if self.output_gain is None:
            raise dac.HidError("Ten model nie obsługuje Global Gain.")
        return self.output_gain

    def set_global_gain_volatile(self, db):
        self.output_gain = db

    def mic_gain_raw(self):
        if self.microphone_gain is None:
            raise dac.HidError("Ten model nie obsługuje Mic Gain.")
        return self.microphone_gain

    def set_mic_gain_raw(self, value):
        self.microphone_gain = {requested: observed for observed, requested in MIC_GAIN_REQUESTS.items()}[value]

    def read_band(self, index, *, include_coefficients=False):
        if self.factory_slot is not None and self.active_slot == self.factory_slot:
            band = self.factory_bands[index]
            coefficients = coefficients_for_band(band, sample_rate_hz=self.sample_rate_hz)
        else:
            band = self.custom_bands[index]
            coefficients = self.custom_coefficients[index]
        return {**band, "coefficients": coefficients} if include_coefficients else dict(band)

    def read_eq(self, bands, *, include_coefficients=False):
        return [self.read_band(index, include_coefficients=include_coefficients) for index in range(bands)]

    def write_band(self, index, freq, gain, q, ftype, _slot, *, coefficients=None):
        self.custom_coefficients[index] = (
            dac.biquad_coefficients(dac.TYPE_TO_CODE[ftype], freq, gain, q, for_write=True)
            if coefficients is None
            else coefficients
        )
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
    path = DATA_DIR / "measurements" / "Moondrop Position (B&K 5128).csv"
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


def coefficients_for_band(band: dict, sample_rate_hz: float = dac.COEFF_FS) -> bytes:
    if abs(sample_rate_hz - 93750.0) < 1.0:
        import echo_a

        return echo_a.biquad_coefficients(echo_a.TYPE_TO_CODE[band["type"]], band["freq"], band["gain"], band["q"])
    return dac.biquad_coefficients(dac.TYPE_TO_CODE[band["type"]], band["freq"], band["gain"], band["q"])


def response_points(profile: Profile, frequencies) -> list[tuple[float, float]]:
    fs = profile.sample_rate_hz or dac.COEFF_FS
    bank = profile.coefficients or [coefficients_for_band(band, sample_rate_hz=fs) for band in profile.bands]
    coefficients = [struct.unpack("<5i", payload) for payload in bank]
    points = []
    for frequency in frequencies:
        angle = -2 * math.pi * frequency / fs
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
    if len(state.bands) != state.band_count or any(
        band is None or band["type"] not in dac.TYPE_TO_CODE for band in state.bands
    ):
        return None
    has_coeffs = len(state.coefficients) == state.band_count and all(len(c) == 20 for c in state.coefficients)
    return Profile(
        "Odczyt z DAC-a",
        state.slot,
        list(state.bands),
        state.preamp,
        coefficients=state.coefficients if has_coeffs else (),
        sample_rate_hz=state.sample_rate_hz,
        model_id=state.model_id,
    )


def export_profile_dialog(parent: QWidget, title: str, profile: Profile) -> str | None:
    """Eksportuje profil EQ do JSON lub Equalizer APO (.txt); zwraca komunikat lub None."""
    base_name = profile.name.replace("/", "_") or "dsp-control-eq"
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
    return tr("export.saved_json")


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
        self.factory_slot: int | None = 0
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
        self.setAccessibleName(tr("plot.eq_title" if correction else "plot.fr_title"))

    def set_primary_points(self, points: list[tuple[float, float]]) -> None:
        self.points = points
        self.curves_changed.emit()
        self.update()

    def set_measurement_curve(self, points: list[tuple[float, float]], *, factory_slot: int | None = 0) -> None:
        if self.correction:
            return
        self.factory_points = list(points)
        self.factory_slot = factory_slot
        self.frequencies = [hz for hz, _ in self.factory_points]
        self.factory_offsets = (
            [db for _, db in response_points(self.factory_filter, self.frequencies)]
            if self.factory_filter and self.frequencies
            else [0.0] * len(self.frequencies)
        )
        self.curves_changed.emit()
        self.update()

    def acoustic_points(self, profile: Profile | None) -> list[tuple[float, float]]:
        if profile is None or not self.factory_points:
            return []
        if self.factory_slot is not None and profile.slot == self.factory_slot:
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
        self.set_primary_points(self.profile_points(profile))

    def set_reference(self, profile: Profile | None) -> None:
        self.set_reference_points(self.profile_points(profile))

    def profile_points(self, profile: Profile | None) -> list[tuple[float, float]]:
        if self.correction:
            return response_points(profile, EQ_PLOT_FREQUENCIES) if profile is not None else []
        return self.acoustic_points(profile)

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
        dark_bg = QApplication.palette().base().color().lightness() < 128
        # Role: 0 = wybrany/edytowany, 1 = obecnie w DSP / referencja, 2 = pomiar Position, 3 = cel AutoEq
        palette_hex = (
            ("#ff9524", "#e879f9", "#22d3ee", "#4ade80") if dark_bg else ("#e55300", "#a21caf", "#0284c7", "#15803d")
        )
        styles = (Qt.PenStyle.SolidLine, Qt.PenStyle.DashLine, Qt.PenStyle.DotLine, Qt.PenStyle.DashDotLine)
        return QPen(QColor(palette_hex[role]), (2.5, 2.0, 2.2, 2.2)[role], styles[role])

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = QApplication.palette()
        text = palette.color(QPalette.ColorRole.Text)
        card_rect = self.rect().adjusted(0, 0, -1, -1)
        plot_background = QApplication.palette().base()
        painter.setBrush(plot_background)
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
        painter.save()
        painter.setClipRect(QRectF(plot).adjusted(0, -1, 0, 1))
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
        painter.restore()
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
            accent = QColor("#ff8a1f" if plot_background.color().lightness() < 128 else "#a83a08")
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
                radius = 12.0 if idx == self.drag_index else (10.5 if active else 8.5)
                painter.setPen(QPen(accent if active else text, 2.2 if active else 1.5))
                painter.setBrush(accent if active else plot_background.color())
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
    def __init__(self, parent=None, spacing: int = 6, *, align_right: bool = False):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self._align_right = align_right

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
        width = 0
        height = 0
        visible = 0
        for item in self._items:
            widget = item.widget()
            if widget is not None and widget.isHidden() and not widget.sizePolicy().retainSizeWhenHidden():
                continue
            hint = item.sizeHint()
            width += hint.width()
            height = max(height, hint.height())
            visible += 1
        if visible > 1:
            width += self._spacing * (visible - 1)
        m = self.contentsMargins()
        return QSize(width + m.left() + m.right(), height + m.top() + m.bottom())

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            widget = item.widget()
            if widget is not None and widget.isHidden() and not widget.sizePolicy().retainSizeWhenHidden():
                continue
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0
        row = []

        def place_row() -> None:
            offset = effective.right() + 1 - (x - self._spacing) if self._align_right else 0
            for item, geometry in row:
                item.setGeometry(geometry.translated(offset, 0))

        for item in self._items:
            widget = item.widget()
            if widget is not None and widget.isHidden() and not widget.sizePolicy().retainSizeWhenHidden():
                continue
            hint = item.sizeHint()
            item_w = min(hint.width(), max(1, effective.width()))
            item_h = hint.height()
            next_x = x + item_w + self._spacing
            wrap_by_width = next_x - self._spacing > effective.right() + 1
            if wrap_by_width and line_height > 0:
                place_row()
                row.clear()
                x = effective.x()
                y += line_height + self._spacing
                next_x = x + item_w + self._spacing
                line_height = 0
            if not test_only:
                row.append((item, QRect(x, y, item_w, item_h)))
            x = next_x
            line_height = max(line_height, item_h)
        place_row()
        return y + line_height - rect.y() + m.bottom()


class _LegendChip(QPushButton):
    def __init__(self, plot: ResponsePlot, role: int, on_toggle=None):
        super().__init__()
        self.setObjectName("legendChip")
        self.plot = plot
        self.role = role
        self.active_roles: list[int] = [role]
        self.on_toggle = on_toggle
        self.setCheckable(True)
        self.setAutoDefault(False)
        self.clicked.connect(self._trigger_toggle)
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
        self.setStyleSheet(
            "QPushButton#legendChip { border: 1px dashed palette(mid); border-radius: 6px; }"
            "QPushButton#legendChip:checked { border-style: solid; background: palette(alternate-base); }"
            "QPushButton#legendChip:enabled:hover { border-color: palette(link); }"
            "QPushButton#legendChip:enabled:pressed { background: palette(midlight); }"
            "QPushButton#legendChip:enabled:focus { border-color: palette(text); }"
        )
        self.set_dimmed(False)

    def set_text(self, text: str) -> None:
        elided = self.label.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, 230)
        self.label.setText(elided)
        self.setAccessibleName(text)
        self.updateGeometry()

    def sizeHint(self) -> QSize:
        return self.layout().sizeHint() if self.layout() is not None else super().sizeHint()

    def set_dimmed(self, dimmed: bool) -> None:
        self.setChecked(not dimmed)
        self.swatch.set_dimmed(dimmed)

    def _trigger_toggle(self) -> None:
        if self.on_toggle is not None:
            self.on_toggle(self.active_roles)
        else:
            self.plot.toggle_roles(self.active_roles)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not event.isAutoRepeat():
                self.setDown(True)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not event.isAutoRepeat() and self.isDown():
                self.click()
            event.accept()
            return
        super().keyReleaseEvent(event)

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
        reserved_roles: tuple[int, ...] = (),
        order: tuple[int, ...] | None = None,
    ):
        super().__init__()
        self.plot = plot
        self.labels = labels
        self.details: dict[int, str] = {}
        self.linked_plots = linked_plots or []
        chip_order = order or tuple(range(len(labels)))
        created: dict[int, _LegendChip] = {}
        self.flow = _FlowLayout(self, spacing=6)
        self.flow.setContentsMargins(0, 2, 0, 2)
        for role in chip_order:
            chip = _LegendChip(plot, role, on_toggle=self._toggle_chip_roles)
            if role in reserved_roles:
                policy = chip.sizePolicy()
                policy.setRetainSizeWhenHidden(True)
                chip.setSizePolicy(policy)
            created[role] = chip
            self.flow.addWidget(chip)
        self.chips: list[_LegendChip] = [created[role] for role in range(len(labels))]
        plot.curves_changed.connect(self.refresh)
        self.refresh()

    def _toggle_chip_roles(self, roles: list[int]) -> None:
        self.plot.toggle_roles(roles)
        hidden = self.plot.is_role_hidden(roles)
        sync_roles = [r for r in roles if r in (0, 1)]
        if sync_roles:
            for linked in self.linked_plots:
                linked.set_roles_hidden(sync_roles, hidden)

    def set_labels(self, labels: tuple[str, ...], details: dict[int, str] | None = None) -> None:
        self.labels = labels
        self.details = details or {}
        self.refresh()

    def refresh(self) -> None:
        groups = {roles[0]: roles for roles, _ in self.plot.series()}
        for role, chip in enumerate(self.chips):
            roles = groups.get(role, [])
            if roles or chip.sizePolicy().retainSizeWhenHidden():
                text = " = ".join(self.labels[index] for index in roles or [role] if self.labels[index])
                chip.set_text(text)
            chip.setVisible(bool(roles))
            if roles:
                chip.active_roles = list(roles)
                detail = self.details.get(role, "")
                chip.setAccessibleDescription(detail)
                chip.setToolTip(tr("plot.key.chip_tooltip", label=detail or text))
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
        device_path: DeviceTarget | None = None,
        device_spec: DeviceSpec | None = None,
        measurement_curve: list[tuple[float, float]] | None = None,
        compare_profile: Profile | None = None,
    ):
        super().__init__(parent)
        self.device_spec = device_spec or getattr(parent, "active_spec", None) or default_device_spec()
        self.measurement_curve = (
            list(measurement_curve) if measurement_curve is not None else self.device_spec.measured_curve()
        )
        self.compare_profile = compare_profile
        self.setWindowTitle(tr("editor.title"))
        self.setStyleSheet(APP_STYLE)
        self.setMinimumSize(625, 460)
        size_to_screen(self, 900, 850)
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
        self.band_mute_solo: list[tuple[QCheckBox, QPushButton, QSlider]] = []
        self.macro_base_bands: list[dict] | None = None
        self._applying_macro = False
        self.ab_target_mode = "flat"
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(8)

        listen_row = QHBoxLayout()
        self.live = QCheckBox(tr("editor.live"))
        self.live.setEnabled(device_path is not None)
        self.live.setToolTip(tr("editor.live_hint"))
        self.live.toggled.connect(self.toggle_live)
        listen_row.addWidget(self.live)
        self.ab_bypass = QPushButton(tr("editor.ab_bypass"))
        self.ab_bypass.setCheckable(True)
        self.ab_bypass.setEnabled(False)
        self.ab_bypass.setToolTip(tr("tooltip.editor_ab_bypass"))
        self.ab_bypass.toggled.connect(self.toggle_ab_bypass)
        listen_row.addWidget(self.ab_bypass)
        self.ab_target_btn = QToolButton()
        self.ab_target_btn.setArrowType(Qt.ArrowType.DownArrow)
        self.ab_target_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.ab_target_btn.setToolTip(tr("tooltip.editor_ab_target"))
        self.ab_target_menu = QMenu(self.ab_target_btn)
        self.ab_target_group = QActionGroup(self.ab_target_menu)
        self.ab_target_group.setExclusive(True)
        for mode, label_key in (
            ("flat", "editor.ab_target_flat"),
            ("initial", "editor.ab_target_initial"),
            ("compare", "editor.ab_target_compare"),
        ):
            act = self.ab_target_menu.addAction(tr(label_key))
            act.setCheckable(True)
            act.setData(mode)
            if mode == "flat":
                act.setChecked(True)
            if mode == "compare" and self.compare_profile is None:
                act.setEnabled(False)
            act.triggered.connect(lambda _checked=False, m=mode: self._set_ab_target_mode(m))
            self.ab_target_group.addAction(act)
        self.ab_target_btn.setMenu(self.ab_target_menu)
        listen_row.addWidget(self.ab_target_btn)
        self.solo_clear_btn = QPushButton(tr("editor.clear_solo"))
        self.solo_clear_btn.setVisible(False)
        self.solo_clear_btn.clicked.connect(self.clear_solo)
        listen_row.addWidget(self.solo_clear_btn)
        self.live_status = QLabel(tr("editor.live_offline" if device_path is None else "editor.live_off"))
        self.live_status.setTextFormat(Qt.TextFormat.PlainText)
        self.live_status.setWordWrap(True)
        listen_row.addWidget(self.live_status, 1)
        outer.addLayout(listen_row)

        self.editor_content = QWidget()
        layout = QVBoxLayout(self.editor_content)
        layout.setContentsMargins(0, 0, 5, 0)
        layout.setSpacing(8)
        self.editor_scroll = scroll_content(self.editor_content)
        outer.addWidget(self.editor_scroll, 1)

        name_row = QHBoxLayout()
        self.name = QLineEdit()
        self.name.setAccessibleName(tr("editor.profile_label"))
        self.name.setPlaceholderText(tr("editor.profile_placeholder"))
        self.name.setToolTip(tr("tooltip.editor_name"))
        profile_label = QLabel(tr("editor.profile_label"))
        profile_label.setBuddy(self.name)
        name_row.addWidget(profile_label)
        name_row.addWidget(self.name, 1)
        self.paste_btn = QPushButton(tr("editor.paste_eq"))
        self.paste_btn.setToolTip(tr("tooltip.editor_paste_eq"))
        self.paste_btn.clicked.connect(lambda: self.paste_from_clipboard())
        name_row.addWidget(self.paste_btn)
        self.reset_flat_btn = QPushButton(tr("editor.reset_flat"))
        self.reset_flat_btn.setToolTip(tr("tooltip.editor_reset_flat"))
        self.reset_flat_btn.clicked.connect(self.reset_to_flat)
        name_row.addWidget(self.reset_flat_btn)
        if current is not None:
            copy = QPushButton(tr("editor.load_dac"))
            copy.setToolTip(tr("tooltip.editor_load_dac"))
            copy.clicked.connect(lambda: self.set_profile(current))
            name_row.addWidget(copy)
        layout.addLayout(name_row)

        gain_row = QHBoxLayout()
        pre_min, pre_max = self.device_spec.dsp.preamp_range_db
        self.preamp = self.decimal(pre_min, pre_max, 0.1)
        if pre_min == pre_max:
            self.preamp.setEnabled(False)
        self.preamp.setSuffix(" dB")
        self.preamp.setMinimumWidth(96)
        self.preamp.setAccessibleName(tr("editor.preamp_label"))
        self.preamp.setToolTip(tr("tooltip.editor_preamp"))
        preamp_label = QLabel(tr("editor.preamp_label"))
        preamp_label.setBuddy(self.preamp)
        gain_row.addWidget(preamp_label)
        gain_row.addWidget(self.preamp)
        self.auto_headroom_btn = QPushButton(tr("editor.auto_headroom"))
        self.auto_headroom_btn.setToolTip(tr("tooltip.editor_auto_headroom"))
        self.auto_headroom_btn.clicked.connect(self.apply_auto_headroom)
        gain_row.addWidget(self.auto_headroom_btn)
        self.headroom_label = QLabel()
        self.headroom_label.setWordWrap(True)
        self.headroom_label.setTextFormat(Qt.TextFormat.PlainText)
        gain_row.addWidget(self.headroom_label, 1)
        layout.addLayout(gain_row)
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

        self.plot = ResponsePlot(correction=True, interactive=True)
        self.plot.setMinimumHeight(160)
        self.plot.band_changed.connect(self.on_plot_band_changed)
        self.plot.band_q_changed.connect(self.on_plot_band_q_changed)
        self.acoustic_plot = ResponsePlot()
        self.acoustic_plot.setMinimumHeight(160)
        self.acoustic_plot.set_measurement_curve(
            self.measurement_curve, factory_slot=self.device_spec.dsp.slots.factory
        )
        self.acoustic_plot.set_factory(factory if self.device_spec.acoustics.measurement_includes_factory_eq else None)
        self.compare = QCheckBox(tr("editor.compare"))
        self.compare.setToolTip(tr("tooltip.editor_compare"))
        self.compare.toggled.connect(self.update_reference)
        views = QTabWidget()
        views.setDocumentMode(True)
        views.setCornerWidget(self.compare, Qt.Corner.TopRightCorner)

        eq_page = QWidget()
        eq_view = QVBoxLayout(eq_page)
        eq_view.setContentsMargins(0, 6, 0, 0)
        eq_view.addWidget(self.plot)
        eq_labels = (tr("plot.key.draft"), tr("plot.key.initial"))
        eq_view.addWidget(PlotKey(self.plot, eq_labels))
        drag_hint = QLabel(tr("editor.plot_drag_hint"))
        drag_hint.setWordWrap(True)
        eq_view.addWidget(drag_hint)
        views.addTab(eq_page, tr("plot.view_eq"))

        if self.measurement_curve:
            acoustic_page = QWidget()
            acoustic_view = QVBoxLayout(acoustic_page)
            acoustic_view.setContentsMargins(0, 6, 0, 0)
            acoustic_view.addWidget(self.acoustic_plot)
            acoustic_view.addWidget(PlotKey(self.acoustic_plot, (*eq_labels, tr("plot.key.measured"))))
            notes = [tr("plot.measurement_note"), tr("plot.treble_note")]
            if factory is None:
                notes.append(tr("plot.neutral_factory"))
            measurement_note = QLabel(" · ".join(notes))
            measurement_note.setWordWrap(True)
            acoustic_view.addWidget(measurement_note)
            views.addTab(acoustic_page, tr("plot.view_response"))
        else:
            views.tabBar().setVisible(False)
        layout.addWidget(views)
        self.plot_timer = QTimer(self, singleShot=True, interval=0)
        self.plot_timer.timeout.connect(self.update_draft)
        self.live_timer = QTimer(self, singleShot=True, interval=140)
        self.live_timer.timeout.connect(self.send_live)
        self.preamp.valueChanged.connect(lambda: self.plot_timer.start())

        self.macro_panel = QWidget()
        self.macro_panel.setVisible(False)
        macro_grid = QGridLayout(self.macro_panel)
        macro_grid.setContentsMargins(8, 6, 8, 6)
        macro_grid.setHorizontalSpacing(10)
        macro_grid.setVerticalSpacing(4)
        self.macro_controls: dict[str, QDoubleSpinBox] = {}
        for idx, (key, label_key, m_min, m_max, m_step, suffix) in enumerate(
            (
                ("bass", "editor.macro_bass", -6.0, 6.0, 0.5, " dB"),
                ("mid", "editor.macro_mid", -6.0, 6.0, 0.5, " dB"),
                ("treble", "editor.macro_treble", -6.0, 6.0, 0.5, " dB"),
                ("tilt", "editor.macro_tilt", -3.0, 3.0, 0.1, " dB/oct"),
            )
        ):
            r, c = divmod(idx, 2)
            lbl = QLabel(tr(label_key))
            spin = self.decimal(m_min, m_max, m_step)
            spin.setDecimals(1)
            spin.setSuffix(suffix)
            spin.setValue(0.0)
            spin.valueChanged.connect(self._on_macro_changed)
            macro_grid.addWidget(lbl, r, c * 2)
            macro_grid.addWidget(spin, r, c * 2 + 1)
            self.macro_controls[key] = spin
        macro_btns = QHBoxLayout()
        macro_btns.setContentsMargins(0, 0, 0, 0)
        self.apply_macro_btn = QPushButton(tr("editor.macro_apply"))
        self.apply_macro_btn.clicked.connect(self.apply_macro)
        self.revert_macro_btn = QPushButton(tr("editor.macro_revert"))
        self.revert_macro_btn.clicked.connect(self.revert_macro)
        macro_btns.addStretch()
        macro_btns.addWidget(self.apply_macro_btn)
        macro_btns.addWidget(self.revert_macro_btn)
        macro_grid.addLayout(macro_btns, 2, 0, 1, 4)

        self.macro_toggle = QToolButton()
        self.macro_toggle.setText(tr("editor.macro_toggle"))
        self.macro_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.macro_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.macro_toggle.setCheckable(True)
        self.macro_toggle.toggled.connect(self.macro_panel.setVisible)
        self.macro_toggle.toggled.connect(
            lambda open_: self.macro_toggle.setArrowType(Qt.ArrowType.DownArrow if open_ else Qt.ArrowType.RightArrow)
        )
        layout.addWidget(self.macro_toggle)
        layout.addWidget(self.macro_panel)

        bands_panel = QWidget()
        bands_panel.setObjectName("editorBands")
        bands_panel.setStyleSheet(
            "QWidget#editorBands QSpinBox, QWidget#editorBands QDoubleSpinBox { padding: 2px 8px; }"
        )
        grid = QGridLayout(bands_panel)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setVerticalSpacing(4)
        grid.setHorizontalSpacing(8)
        for column, title in enumerate(
            (
                tr("editor.col_band"),
                tr("editor.col_on"),
                tr("editor.col_solo"),
                tr("editor.col_type"),
                tr("editor.col_freq"),
                tr("editor.col_gain"),
                "",
                tr("editor.col_q"),
            )
        ):
            grid.addWidget(QLabel(title), 0, column)
        grid.setColumnStretch(5, 1)
        type_labels = (
            (tr("editor.type_pk"), "PK"),
            (tr("editor.type_lsq"), "LSQ"),
            (tr("editor.type_hsq"), "HSQ"),
            (tr("editor.type_lp"), "LP"),
            (tr("editor.type_hp"), "HP"),
        )
        allowed_types = set(self.device_spec.dsp.supported_types)
        gain_min, gain_max = self.device_spec.dsp.gain_range_db
        q_min, q_max = self.device_spec.dsp.q_range
        freq_min, freq_max = self.device_spec.dsp.freq_range_hz
        for number in range(1, self.device_spec.dsp.band_count + 1):
            enabled_cb = QCheckBox()
            enabled_cb.setChecked(True)
            enabled_cb.setToolTip(tr("tooltip.editor_band_mute", band=number))
            enabled_cb.setAccessibleName(tr("editor.band_field", label=tr("editor.col_on"), band=number))
            solo_btn = QPushButton("S")
            solo_btn.setCheckable(True)
            solo_btn.setFixedWidth(26)
            solo_btn.setToolTip(tr("tooltip.editor_band_solo", band=number))
            solo_btn.setAccessibleName(tr("editor.band_field", label=tr("editor.col_solo"), band=number))
            kind = QComboBox()
            for label, code in type_labels:
                if code in allowed_types:
                    kind.addItem(label, code)
            frequency = QSpinBox()
            frequency.setRange(int(freq_min), int(freq_max))
            frequency.setMinimumWidth(88)
            gain = self.decimal(gain_min, gain_max, 0.1)
            gain.setMinimumWidth(78)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(round(gain_min * 10), round(gain_max * 10))
            slider.setPageStep(10)
            slider.setMinimumWidth(65)
            slider.valueChanged.connect(lambda value, box=gain: box.setValue(value / 10))
            gain.valueChanged.connect(lambda value, control=slider: self.sync_gain_slider(control, value))
            q = self.decimal(q_min, q_max, 0.01)
            q.setMinimumWidth(78)
            for control in (kind, frequency, gain, q):
                control.setMinimumHeight(28)
                control.setSizePolicy(control.sizePolicy().horizontalPolicy(), QSizePolicy.Policy.Expanding)
            grid.addWidget(QLabel(str(number)), number, 0)
            grid.addWidget(enabled_cb, number, 1, Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(solo_btn, number, 2)
            for column, key, widget in (
                (3, "editor.col_type", kind),
                (4, "editor.col_freq", frequency),
                (5, "editor.gain_slider", slider),
                (6, "editor.col_gain", gain),
                (7, "editor.col_q", q),
            ):
                widget.setAccessibleName(tr("editor.band_field", label=tr(key), band=number))
                grid.addWidget(widget, number, column)
            self.rows.append((kind, frequency, gain, q))
            self.band_mute_solo.append((enabled_cb, solo_btn, slider))
            enabled_cb.toggled.connect(lambda _on, idx=number - 1: self._on_band_mute_solo_changed(idx))
            solo_btn.toggled.connect(lambda _on, idx=number - 1: self._on_band_mute_solo_changed(idx))
            kind.currentIndexChanged.connect(
                lambda _index, box=kind, control=slider, value=gain: self.filter_type_changed(box, control, value)
            )
            for control in (frequency, gain, q):
                control.valueChanged.connect(self._on_manual_band_edited)
        layout.addWidget(bands_panel)
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

        self.message = FeedbackLabel()
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        outer.addWidget(self.message)
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
        for button in buttons.buttons():
            button.setAutoDefault(False)
        self.editor_buttons = buttons
        outer.addWidget(buttons)

        for spin_box in self.findChildren(QAbstractSpinBox):
            spin_box.lineEdit().setTextMargins(6, 0, 2, 0)

        if source is None:
            source = Profile(
                "Własny EQ",
                self.device_spec.dsp.slots.custom,
                default_custom_bands(self.device_spec),
                0.0,
                sample_rate_hz=self.device_spec.dsp.sample_rate_hz,
                model_id=self.device_spec.model_id,
            )
        self.set_profile(source)
        self.ensurePolished()
        outer.activate()
        content_height = max(layout.minimumSize().height(), layout.heightForWidth(self.editor_scroll.width()))
        extra_height = max(0, content_height - self.editor_scroll.height())
        size_to_screen(self, self.width(), self.height() + extra_height)

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
        self._applying_macro = True
        try:
            muted_map = profile.muted_bands or {}
            for idx, (band, (kind, frequency, gain, q), (enabled_cb, solo_btn, _slider)) in enumerate(
                zip(profile.bands, self.rows, self.band_mute_solo, strict=False), 1
            ):
                muted_entry = muted_map.get(str(idx))
                is_muted = isinstance(muted_entry, dict)
                source_band = dac.quantized_band(muted_entry if is_muted else band)
                for w in (kind, frequency, gain, q, enabled_cb, solo_btn):
                    w.blockSignals(True)
                kind.setCurrentIndex(kind.findData(source_band["type"]))
                frequency.setValue(source_band["freq"])
                gain.setValue(source_band["gain"])
                q.setValue(source_band["q"])
                enabled_cb.setChecked(not is_muted)
                solo_btn.setChecked(False)
                for w in (kind, frequency, gain, q, enabled_cb, solo_btn):
                    w.blockSignals(False)
                self._apply_band_row_style(idx - 1)
            self.macro_base_bands = None
            for spin in self.macro_controls.values():
                spin.blockSignals(True)
                spin.setValue(0.0)
                spin.blockSignals(False)
            self.solo_clear_btn.setVisible(False)
        finally:
            self._applying_macro = False
        self.plot_timer.start()
        self.update_reference()
        self.message.clear()

    def update_reference(self) -> None:
        reference = self.reference if self.compare.isChecked() else None
        self.plot.set_reference(reference)
        self.acoustic_plot.set_reference(reference)

    def _apply_band_row_style(self, index: int) -> None:
        enabled_cb, _solo_btn, slider = self.band_mute_solo[index]
        active = enabled_cb.isChecked()
        for w in (*self.rows[index], slider):
            w.setEnabled(active)

    def _on_band_mute_solo_changed(self, index: int) -> None:
        self._apply_band_row_style(index)
        any_solo = any(s.isChecked() for _, s, _ in self.band_mute_solo)
        self.solo_clear_btn.setVisible(any_solo)
        self.plot_timer.start()

    def clear_solo(self) -> None:
        for _, solo_btn, _ in self.band_mute_solo:
            solo_btn.blockSignals(True)
            solo_btn.setChecked(False)
            solo_btn.blockSignals(False)
        self.solo_clear_btn.setVisible(False)
        self.plot_timer.start()

    def _on_manual_band_edited(self) -> None:
        if not self._applying_macro and self.macro_base_bands is not None:
            self.macro_base_bands = None
            for spin in self.macro_controls.values():
                spin.blockSignals(True)
                spin.setValue(0.0)
                spin.blockSignals(False)
        self.plot_timer.start()

    def _on_macro_changed(self) -> None:
        if self._applying_macro:
            return
        if self.macro_base_bands is None:
            self.macro_base_bands = [
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
        updated = apply_macro_tone(
            self.macro_base_bands,
            bass_db=self.macro_controls["bass"].value(),
            mid_db=self.macro_controls["mid"].value(),
            treble_db=self.macro_controls["treble"].value(),
            tilt_db_per_oct=self.macro_controls["tilt"].value(),
            spec=self.device_spec,
        )
        self._applying_macro = True
        try:
            for band, (kind, frequency, gain, q) in zip(updated, self.rows, strict=False):
                for w in (kind, frequency, gain, q):
                    w.blockSignals(True)
                kind.setCurrentIndex(kind.findData(band["type"]))
                frequency.setValue(round(band["freq"]))
                gain.setValue(float(band["gain"]))
                q.setValue(float(band["q"]))
                for w in (kind, frequency, gain, q):
                    w.blockSignals(False)
        finally:
            self._applying_macro = False
        self.plot_timer.start()

    def apply_macro(self) -> None:
        self.macro_base_bands = None
        for spin in self.macro_controls.values():
            spin.blockSignals(True)
            spin.setValue(0.0)
            spin.blockSignals(False)

    def revert_macro(self) -> None:
        if self.macro_base_bands is not None:
            self._applying_macro = True
            try:
                for band, (kind, frequency, gain, q) in zip(self.macro_base_bands, self.rows, strict=False):
                    for w in (kind, frequency, gain, q):
                        w.blockSignals(True)
                    kind.setCurrentIndex(kind.findData(band["type"]))
                    frequency.setValue(round(band["freq"]))
                    gain.setValue(float(band["gain"]))
                    q.setValue(float(band["q"]))
                    for w in (kind, frequency, gain, q):
                        w.blockSignals(False)
            finally:
                self._applying_macro = False
            self.macro_base_bands = None
        for spin in self.macro_controls.values():
            spin.blockSignals(True)
            spin.setValue(0.0)
            spin.blockSignals(False)
        self.plot_timer.start()

    def draft(self, *, include_solo: bool = True) -> Profile:
        any_solo = include_solo and any(s.isChecked() for _, s, _ in self.band_mute_solo)
        bands: list[dict] = []
        muted_bands: dict[str, dict] = {}
        for index, ((kind, frequency, gain, q), (enabled_cb, solo_btn, _)) in enumerate(
            zip(self.rows, self.band_mute_solo, strict=False), 1
        ):
            raw_band = dac.quantized_band(
                {
                    "band": index,
                    "type": kind.currentData(),
                    "freq": frequency.value(),
                    "gain": gain.value(),
                    "q": q.value(),
                }
            )
            if not enabled_cb.isChecked():
                muted_bands[str(index)] = raw_band
                bands.append({"band": index, "type": "PK", "freq": 1000, "gain": 0.0, "q": 0.71})
            elif any_solo and not solo_btn.isChecked():
                bands.append({"band": index, "type": "PK", "freq": 1000, "gain": 0.0, "q": 0.71})
            else:
                bands.append(raw_band)
        preamp = dac.clamp_i16(self.preamp.value() * 256) / 256
        global_gain_db = self.global_gain.value() if self.include_global_gain.isChecked() else None
        mic_gain_raw = self.mic_gain.currentData() if self.include_mic_gain.isChecked() else None
        profile = custom_profile(
            self.name.text().strip() or "Własny EQ",
            self.device_spec.dsp.slots.custom,
            bands,
            preamp,
            global_gain_db,
            mic_gain_raw,
            spec=self.device_spec,
        )
        hp_name = self.reference.headphone_name or (
            self.device_window.active_headphone_name() if hasattr(self.device_window, "active_headphone_name") else None
        )
        return replace(
            profile,
            source=self.reference.source,
            target_name=self.reference.target_name,
            target_curve=self.reference.target_curve,
            fit_range=self.reference.fit_range,
            headphone_name=hp_name,
            headphone_selection=self.reference.headphone_selection,
            muted_bands=muted_bands or None,
        )

    def select_draft(self) -> None:
        self.result_profile = self.draft(include_solo=False)
        self.result_apply = False
        self.accept()

    def apply_draft(self) -> None:
        self.result_profile = self.draft(include_solo=False)
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
        self.acoustic_plot.set_profile(profile)
        if self.live.isChecked() and not self.live_timer.isActive():
            self.live_timer.start()

    def run_live(self, operation, finished) -> None:
        self.live_busy = True
        self.device_window.start(operation, finished)

    def show_live_status(self, message: str) -> None:
        self.live_status.setText(message)
        self.live_status.setVisible(bool(message))

    def paste_from_clipboard(self, text: str | None = None) -> bool:
        raw = text if text is not None else QApplication.clipboard().text()
        if not raw.strip():
            QMessageBox.information(self, tr("editor.paste_eq_title"), tr("editor.paste_eq_empty"))
            return False
        try:
            bands, preamp = dac.parse_eqapo_text(raw, source_name="clipboard")
            if len(bands) < self.device_spec.dsp.band_count:
                neutral = default_custom_bands(self.device_spec)
                bands.extend(neutral[len(bands) :])
            elif len(bands) > self.device_spec.dsp.band_count:
                bands = bands[: self.device_spec.dsp.band_count]
            pre_min, pre_max = self.device_spec.dsp.preamp_range_db
            clamped_preamp = max(pre_min, min(pre_max, preamp)) if preamp is not None else self.preamp.value()
            parsed = custom_profile(
                self.draft().name,
                self.device_spec.dsp.slots.custom,
                bands,
                clamped_preamp,
                spec=self.device_spec,
            )
        except (ValueError, SystemExit) as exc:
            QMessageBox.warning(self, tr("editor.paste_eq_title"), tr("editor.paste_eq_error", error=exc))
            return False
        profile = replace(
            self.draft(),
            bands=parsed.bands,
            preamp=parsed.preamp,
            source=tr("editor.paste_eq_source"),
        )
        self.set_profile(profile)
        return True

    def reset_to_flat(self) -> None:
        neutral = default_custom_bands(self.device_spec)
        profile = replace(
            self.draft(),
            bands=neutral,
            preamp=0.0,
            source=tr("headphone.flat_short"),
        )
        self.set_profile(profile)

    def toggle_ab_bypass(self, _bypassed: bool) -> None:
        if not self.live.isChecked() or self.live_snapshot is None:
            return
        self.live_timer.stop()
        self.send_live()

    def toggle_live(self, enabled: bool) -> None:
        if not enabled:
            self.live_timer.stop()
            was_blocked = self.ab_bypass.blockSignals(True)
            self.ab_bypass.setChecked(False)
            self.ab_bypass.blockSignals(was_blocked)
            self.ab_bypass.setEnabled(False)
            self.plot.set_profile(self.draft())
            self.settle_live()
            return
        if self.live_busy:
            return
        self.live_error = ""
        self.live.setEnabled(False)
        self.ab_bypass.setEnabled(False)
        self.show_live_status(tr("editor.live_reading"))
        self.run_live(
            lambda: begin_live_eq(self.device_window.open_device, self.device_path),
            self.live_started,
        )

    def live_started(self, snapshot, error: str) -> None:
        self.live_busy = False
        if error:
            self.fail_live(tr("editor.live_start_error"), error)
            self.settle_live()
            return
        self.live_snapshot = snapshot
        self.live_previous = snapshot.custom
        self.live_preamp = snapshot.custom.preamp
        self.live.setEnabled(self.pending_exit is None)
        self.ab_bypass.setEnabled(self.pending_exit is None and self.live.isChecked())
        if self.live.isChecked():
            self.send_live()
        else:
            self.settle_live()

    def _set_ab_target_mode(self, mode: str) -> None:
        self.ab_target_mode = mode
        label_key = {
            "flat": "editor.ab_bypass",
            "initial": "editor.ab_bypass_initial",
            "compare": "editor.ab_bypass_compare",
        }.get(mode, "editor.ab_bypass")
        self.ab_bypass.setText(tr(label_key))
        if self.ab_bypass.isChecked() and self.live.isChecked() and self.live_snapshot is not None:
            self.live_timer.stop()
            self.send_live()

    def _bypass_profile(self, profile: Profile) -> Profile:
        if self.ab_target_mode == "initial" and self.reference is not None:
            return replace(self.reference, preamp=float(self.reference.preamp or 0.0))
        if self.ab_target_mode == "compare" and self.compare_profile is not None:
            return replace(self.compare_profile, preamp=float(self.compare_profile.preamp or 0.0))
        return replace(profile, bands=default_custom_bands(self.device_spec), preamp=0.0)

    def send_live(self) -> None:
        if not self.live.isChecked() or self.live_busy or self.live_snapshot is None:
            return
        draft = self.draft()
        bypassed = self.ab_bypass.isChecked()
        profile = self._bypass_profile(draft) if bypassed else draft
        previous = self.live_previous
        if (profile.bands, profile.preamp) == (previous.bands, previous.preamp):
            self.plot.set_profile(draft if bypassed else replace(profile, preamp=self.live_preamp))
            if bypassed:
                self.show_live_status(tr("editor.ab_bypass_active"))
            elif dac.preamp_matches(self.live_preamp, profile.preamp):
                self.show_live_status(tr("editor.live_active"))
            else:
                self.show_live_status(tr("editor.live_preamp", actual=self.live_preamp, requested=profile.preamp))
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
            self.fail_live(tr("editor.live_interrupted"), error)
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
            self.show_live_status(tr("editor.live_restoring"))
            self.run_live(lambda: end_live_eq(self.device_window.open_device, snapshot, previous), self.live_restored)
            return
        if self.pending_exit is not None:
            if self.live_error:
                self.device_window.feedback.setText(self.live_error)
            super().done(self.pending_exit)
        else:
            self.live.setEnabled(self.device_path is not None)
            self.show_live_status(self.live_error or tr("editor.live_off"))

    def live_restored(self, _result, error: str) -> None:
        self.live_busy = False
        self.live_snapshot = None
        self.live_previous = None
        self.live_preamp = None
        if error:
            self.fail_live(tr("editor.live_restore_error"), error)
            self.upload.setEnabled(False)
            if self.pending_exit is not None and self.result_apply:
                self.pending_exit = QDialog.DialogCode.Rejected
        self.settle_live()

    def done(self, result: int) -> None:
        if self.pending_exit is not None:
            return
        self.pending_exit = result
        self.editor_content.setEnabled(False)
        self.editor_buttons.setEnabled(False)
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


class HeadphonePickerDialog(QDialog):
    """Modalny wybór podłączonych słuchawek z katalogu AutoEq, pliku CSV/TXT lub trybu Flat."""

    def __init__(
        self,
        parent: QWidget,
        spec: DeviceSpec,
        entries: list[catalog.Entry],
        recent: list[HeadphoneSelection] = (),
    ):
        super().__init__(parent)
        self.spec = spec
        self.model_entries = [entry for entry in entries if entry.kind == "model"]
        self.selected_headphone: HeadphoneSelection | None = None
        self.setWindowTitle(tr("headphone.dialog_title", model=spec.display_name))
        self.setStyleSheet(APP_STYLE)
        self.setMinimumSize(520, 440)
        size_to_screen(self, 680, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(10)

        intro = QLabel(
            tr(
                "headphone.dialog_intro",
                model=spec.display_name,
                bands=spec.dsp.band_count,
                rate=f"{spec.dsp.sample_rate_hz / 1000:g}",
            )
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        if recent:
            recent_row = _FlowLayout(spacing=6)
            recent_row.setContentsMargins(0, 0, 0, 0)
            recent_label = QLabel(tr("headphone.recent_label"))
            recent_row.addWidget(recent_label)
            for item in recent[:RECENT_HEADPHONES_LIMIT]:
                btn = QPushButton(item.name)
                btn.setToolTip(f"{item.name} ({item.source})" if item.source else item.name)
                btn.clicked.connect(lambda _checked=False, sel=item: self.pick_recent(sel))
                recent_row.addWidget(btn)
            layout.addLayout(recent_row)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.source_filter = QComboBox()
        self.source_filter.setAccessibleName(tr("autoeq.source_a11y"))
        self.source_filter.addItem(tr("autoeq.source_all"), "")
        for source in sorted({catalog.measurement_source(e) for e in self.model_entries}, key=str.casefold):
            self.source_filter.addItem(source, source)
        self.form_filter = QComboBox()
        self.form_filter.setAccessibleName(tr("autoeq.mode_a11y"))
        self.form_filter.addItem(tr("headphone.form_all"), "all")
        self.form_filter.addItem(tr("autoeq.mode.in_ear"), "in-ear")
        self.form_filter.addItem(tr("autoeq.mode.over_ear"), "over-ear")
        filters.addWidget(self.source_filter, 1)
        filters.addWidget(self.form_filter, 1)
        layout.addLayout(filters)

        self.search = search_field(tr("headphone.search_placeholder"), tr("headphone.search_a11y"))
        layout.addWidget(self.search)

        self.list_model = CatalogListModel(self)
        self.list_view = QListView()
        self.list_view.setModel(self.list_model)
        self.list_view.setUniformItemSizes(True)
        self.list_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_view.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list_view.setAccessibleName(tr("headphone.list_a11y"))
        self.list_view.doubleClicked.connect(lambda _idx: self.accept_catalog_entry())
        layout.addWidget(self.list_view, 1)

        self.count_label = QLabel()
        self.count_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.count_label)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.file_btn = QPushButton(tr("headphone.open_file"))
        self.file_btn.clicked.connect(self.pick_local_file)
        actions.addWidget(self.file_btn)
        self.flat_btn = QPushButton(tr("headphone.use_flat"))
        self.flat_btn.clicked.connect(self.pick_flat)
        actions.addWidget(self.flat_btn)
        if spec.has_default_headphone:
            self.default_btn = QPushButton(tr("headphone.use_default"))
            self.default_btn.clicked.connect(self.pick_default)
            actions.addWidget(self.default_btn)
        actions.addStretch()
        self.cancel_btn = QPushButton(tr("editor.cancel"))
        self.cancel_btn.clicked.connect(self.reject)
        self.choose_btn = QPushButton(tr("headphone.choose_btn"))
        self.choose_btn.setStyleSheet(PRIMARY_ACTION_STYLE)
        self.choose_btn.setDefault(True)
        self.choose_btn.clicked.connect(self.accept_catalog_entry)
        actions.addWidget(self.cancel_btn)
        actions.addWidget(self.choose_btn)
        layout.addLayout(actions)

        self.source_filter.currentIndexChanged.connect(self.refresh_list)
        self.form_filter.currentIndexChanged.connect(self.refresh_list)
        self.search.textChanged.connect(self.refresh_list)
        self.list_view.selectionModel().currentChanged.connect(self._sync_choose_state)
        self.refresh_list()

    def refresh_list(self) -> None:
        selected_source = self.source_filter.currentData() or ""
        form = self.form_filter.currentData() or "all"
        words = re.sub(r"[-_/]+", " ", self.search.text().casefold()).split()
        matching = [
            entry
            for entry in self.model_entries
            if (not selected_source or catalog.measurement_source(entry) == selected_source)
            and (form == "all" or catalog.headphone_form(entry) == form)
            and all(word in re.sub(r"[-_/]+", " ", f"{entry.name} {entry.source}".casefold()) for word in words)
        ]
        self.list_model.set_entries(matching)
        if matching:
            self.list_view.setCurrentIndex(self.list_model.index(0, 0))
        self.count_label.setText(tr("autoeq.results_count", count=len(matching)))
        self._sync_choose_state()

    def _sync_choose_state(self) -> None:
        self.choose_btn.setEnabled(self.list_view.currentIndex().isValid())

    def accept_catalog_entry(self) -> None:
        idx = self.list_view.currentIndex()
        entry = idx.data(PROFILE_ROLE) if idx.isValid() else None
        if entry is None:
            return
        self.selected_headphone = HeadphoneSelection(
            mode="autoeq",
            name=entry.name,
            source=entry.source,
            path=entry.path,
            revision=entry.revision,
            form=catalog.headphone_form(entry),
        )
        self.accept()

    def pick_local_file(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            tr("headphone.open_file_title"),
            "",
            tr("headphone.open_file_filter"),
        )
        if not path_str:
            return
        curve = load_measurement_curve_from_path(path_str)
        if not curve:
            QMessageBox.warning(self, tr("headphone.open_file_title"), tr("headphone.invalid_file"))
            return
        file_path = Path(path_str)
        self.selected_headphone = HeadphoneSelection(
            mode="file",
            name=file_path.stem,
            source=file_path.name,
            path=str(file_path),
            form="in-ear",
        )
        self.accept()

    def pick_flat(self) -> None:
        self.selected_headphone = HeadphoneSelection(mode="flat")
        self.accept()

    def pick_default(self) -> None:
        self.selected_headphone = HeadphoneSelection(mode="default")
        self.accept()

    def pick_recent(self, selection: HeadphoneSelection) -> None:
        self.selected_headphone = selection
        self.accept()


class AutoEqPanel(QWidget):
    preview_changed = Signal()

    def __init__(self, parent, cache_directory: Path):
        super().__init__(parent)
        self.window = parent
        self.cache_directory = cache_directory
        self.index_path = cache_directory / "catalog.json"
        self.local_index_path = cache_directory / "local-catalog.json"
        self.entries: list[catalog.Entry] = []
        self.result = None
        self.result_entry = None
        self.result_range = None
        self.result_options = None
        self.fit_active = False
        self.fit_cancelled = False
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

        self.source_filter = QComboBox()
        self.source_filter.setAccessibleName(tr("autoeq.source_a11y"))
        self.source_filter.addItem(tr("autoeq.source_all"), "")
        self.mode = QComboBox()
        self.mode.addItem(tr("autoeq.mode.all"), "all")
        self.mode.addItem(tr("autoeq.mode.in_ear"), "in-ear")
        self.mode.addItem(tr("autoeq.mode.over_ear"), "over-ear")
        self.mode.addItem(tr("autoeq.mode.target"), "target")
        self.mode.setAccessibleName(tr("autoeq.mode_a11y"))
        self.fit_range = QComboBox()
        self.fit_range.setAccessibleName(tr("autoeq.fit_range_label"))
        self.fit_range.setToolTip(tr("tooltip.autoeq_fit_range"))
        for key, limits in AUTOEQ_FIT_RANGES:
            self.fit_range.addItem(tr(key), limits)
        for combo in (self.source_filter, self.mode, self.fit_range):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(9)
        self.fit_controls = self.fit_range
        self.bass_boost = QDoubleSpinBox()
        self.bass_boost.setRange(-6.0, 12.0)
        self.bass_boost.setSingleStep(0.5)
        self.bass_boost.setDecimals(1)
        self.bass_boost.setValue(0.0)
        self.bass_boost.setPrefix(tr("autoeq.bass_prefix"))
        self.bass_boost.setSuffix(" dB")
        self.bass_boost.setToolTip(tr("tooltip.autoeq_bass_boost"))
        self.bass_boost.valueChanged.connect(self.range_changed)
        self.tilt = QDoubleSpinBox()
        self.tilt.setRange(-3.0, 3.0)
        self.tilt.setSingleStep(0.1)
        self.tilt.setDecimals(1)
        self.tilt.setValue(0.0)
        self.tilt.setPrefix(tr("autoeq.tilt_prefix"))
        self.tilt.setSuffix(" dB")
        self.tilt.setToolTip(tr("tooltip.autoeq_tilt"))
        self.tilt.valueChanged.connect(self.range_changed)
        self.pk_only = QCheckBox(tr("autoeq.pk_only"))
        self.pk_only.setToolTip(tr("tooltip.autoeq_pk_only"))
        self.pk_only.toggled.connect(self.range_changed)
        fit_options = QHBoxLayout()
        fit_options.setContentsMargins(0, 0, 0, 0)
        fit_options.setSpacing(6)
        fit_options.addWidget(self.bass_boost)
        fit_options.addWidget(self.tilt)
        fit_options.addWidget(self.pk_only)
        fit_options.addStretch()
        self.search = search_field(tr("search.autoeq_placeholder"), tr("search.autoeq_a11y"))
        layout.addWidget(self.source_filter)
        layout.addWidget(self.mode)
        layout.addWidget(self.fit_range)
        layout.addLayout(fit_options)
        layout.addWidget(self.search)
        self.catalog_menu = QMenu(self)
        self.refresh_action = QAction(tr("autoeq.download_catalog"), self)
        self.refresh_action.triggered.connect(self.download_catalog)
        self.folder_action = self.catalog_menu.addAction(tr("autoeq.open_local"), self.open_catalog)
        self.file_action = self.catalog_menu.addAction(tr("autoeq.open_custom"), self.open_target)
        self.catalog_button = QToolButton()
        self.catalog_button.setDefaultAction(self.refresh_action)
        self.catalog_button.setMenu(self.catalog_menu)
        self.catalog_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)

        self.fit_provenance = FeedbackLabel()
        self.fit_provenance.setTextFormat(Qt.TextFormat.PlainText)
        self.fit_provenance.setWordWrap(True)

        self.target_model = CatalogListModel(self)
        self.targets = QListView()
        self.targets.setModel(self.target_model)
        self.targets.setUniformItemSizes(True)
        self.targets.setMouseTracking(True)
        self.targets.setAccessibleName(tr("autoeq.target_list"))
        self.targets.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.targets.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.catalog_list = QFrame()
        self.catalog_list.setObjectName("catalogList")
        list_layout = QVBoxLayout(self.catalog_list)
        list_layout.setContentsMargins(4, 4, 4, 4)
        list_layout.setSpacing(2)
        list_layout.addWidget(self.targets, 1)
        layout.addWidget(self.catalog_list, 1)

        self.status = ElidingLabel(retain_hidden=True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(False)
        self.catalog_progress = FeedbackLabel()
        self.catalog_progress.setTextFormat(Qt.TextFormat.PlainText)
        self.catalog_progress.setWordWrap(True)
        self.catalog_progress.setContentsMargins(8, 3, 8, 3)
        list_layout.addWidget(self.catalog_progress)
        self.catalog_error_detail = ""
        self.catalog_error = QLabel()
        self.catalog_error.setTextFormat(Qt.TextFormat.RichText)
        self.catalog_error.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        )
        self.catalog_error.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.catalog_error.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.catalog_error.setStyleSheet(
            "QLabel { border-left: 2px solid palette(link); padding: 3px 8px;"
            " background: palette(alternate-base); }"
            " QLabel:hover { background: palette(midlight); }"
            " QLabel:focus { border-color: palette(text); }"
        )
        self.catalog_error.linkActivated.connect(self.report_catalog_error)
        self.catalog_error.hide()
        list_layout.addWidget(self.catalog_error)
        layout.addWidget(self.fit_provenance)
        self.fit_status = FeedbackLabel()
        self.fit_status.setTextFormat(Qt.TextFormat.PlainText)
        self.fit_status.setWordWrap(True)
        self.generate = QPushButton(tr("autoeq.compute"))
        self.headphone_cta = QPushButton(tr("autoeq.choose_headphones_cta"))
        self.headphone_cta.clicked.connect(lambda: self.window.choose_headphones())
        self.headphone_cta.hide()
        layout.addWidget(self.headphone_cta)
        self.cancel = QPushButton(tr("autoeq.cancel"))
        self.cancel.hide()
        self.apply_tooltips()

        self.mode.currentIndexChanged.connect(self.update_results)
        self.source_filter.currentIndexChanged.connect(self.update_results)
        self.search.textChanged.connect(self.update_results)
        self.targets.selectionModel().currentChanged.connect(self.target_changed)
        self.fit_range.currentIndexChanged.connect(self.range_changed)
        self.generate.clicked.connect(self.generate_profile)
        self.cancel.clicked.connect(self.cancel_fit)
        self.entries = self.load_initial_entries()
        self.update_results()

    @staticmethod
    def _bundled_target_fallbacks(existing: list[catalog.Entry]) -> list[catalog.Entry]:
        covered = {Path(entry.path).name for entry in existing if entry.kind == "target"}
        fallbacks: list[catalog.Entry] = []
        if BUNDLED_TARGETS_DIR.is_dir():
            for csv_path in sorted(BUNDLED_TARGETS_DIR.glob("*.csv")):
                if csv_path.name not in covered:
                    fallbacks.append(catalog.Entry(csv_path.stem, "AutoEq", "target", str(csv_path), True))
        return fallbacks

    def load_initial_entries(self) -> list[catalog.Entry]:
        remote_entries: list[catalog.Entry] = []
        for path in (self.index_path, BUNDLED_CATALOG):
            with contextlib.suppress(OSError, ValueError, TypeError):
                loaded = catalog.load_index(path)
                if loaded:
                    remote_entries = loaded
                    break
        local_entries: list[catalog.Entry] = []
        with contextlib.suppress(OSError, ValueError, TypeError):
            local_entries = catalog.load_index(self.local_index_path)
        entries = [*remote_entries, *local_entries]
        entries.extend(self._bundled_target_fallbacks(entries))
        return entries

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
            compact = ""
        else:
            message = tr("autoeq.results_count", count=len(matching))
            compact = str(len(matching))
        self.status.set_title(message, wrap=False, compact=compact)

    def sync_device_spec(self, spec: DeviceSpec) -> None:
        self.fit_range.blockSignals(True)
        self.fit_range.clear()
        for key, (max_fc, bands) in AUTOEQ_FIT_RANGES:
            clamped_bands = min(bands, spec.dsp.band_count)
            self.fit_range.addItem(tr(key), (max_fc, clamped_bands))
        self.fit_range.blockSignals(False)
        supports_shelves = "LSQ" in spec.dsp.supported_types and "HSQ" in spec.dsp.supported_types
        was_blocked = self.pk_only.blockSignals(True)
        if not supports_shelves:
            self.pk_only.setChecked(True)
        self.pk_only.setEnabled(supports_shelves)
        self.pk_only.blockSignals(was_blocked)
        self.result = None
        self.result_entry = None
        self.result_range = None
        self.result_options = None
        self.fit_status.clear()
        self.update_actions()

    def apply_tooltips(self) -> None:
        self.mode.setToolTip(tr("tooltip.autoeq_mode"))
        self.source_filter.setToolTip(tr("tooltip.autoeq_source"))
        self.search.setToolTip(tr("tooltip.autoeq_search"))
        self.catalog_button.setToolTip(tr("tooltip.autoeq_catalog_btn"))
        self.generate.setToolTip(tr("tooltip.autoeq_compute"))
        self.bass_boost.setToolTip(tr("tooltip.autoeq_bass_boost"))
        self.tilt.setToolTip(tr("tooltip.autoeq_tilt"))
        self.pk_only.setToolTip(tr("tooltip.autoeq_pk_only"))

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
        self.headphone_cta.setText(tr("autoeq.choose_headphones_cta"))
        self.set_catalog_error(self.catalog_error_detail)
        self.folder_action.setText(tr("autoeq.open_local"))
        self.file_action.setText(tr("autoeq.open_custom"))
        self.source_filter.setAccessibleName(tr("autoeq.source_a11y"))
        self.fit_range.setAccessibleName(tr("autoeq.fit_range_label"))
        self.fit_range.setToolTip(tr("tooltip.autoeq_fit_range"))
        for index, (key, _) in enumerate(AUTOEQ_FIT_RANGES):
            self.fit_range.setItemText(index, tr(key))
        self.bass_boost.setPrefix(tr("autoeq.bass_prefix"))
        self.tilt.setPrefix(tr("autoeq.tilt_prefix"))
        self.pk_only.setText(tr("autoeq.pk_only"))
        self.targets.setAccessibleName(tr("autoeq.target_list"))
        self.update_generate_label()
        self.cancel.setText(tr("autoeq.cancel"))
        self.apply_tooltips()
        self.update_results()

    def target_changed(self, *_args) -> None:
        entry = self.current_entry()
        if entry is None or entry != self.result_entry:
            self.result = None
            if not self.fit_active:
                self.fit_status.clear()
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

    def range_changed(self) -> None:
        self.update_actions()

    def update_generate_label(self) -> None:
        self.generate.setText(tr("autoeq.recompute" if self.result is not None else "autoeq.compute"))

    def current_fit_options(self) -> tuple[float, float, bool]:
        return (round(self.bass_boost.value(), 2), round(self.tilt.value(), 2), self.pk_only.isChecked())

    def ready_result(self) -> Profile | None:
        if (
            self.result_range == self.fit_range.currentData()
            and self.result_entry == self.current_entry()
            and (self.result_options is None or self.result_options == self.current_fit_options())
        ):
            return self.result
        return None

    def load_selected_preview(self) -> None:
        entry = self.preview_entry
        if entry is None or (not entry.local and not self.isVisible()):
            return
        req_id = self.preview_request_id
        cache_dir = self.cache_directory / "curves"
        job = Job(
            lambda: read_target_curve(catalog.resolve_curve(entry, cache_dir, bundled_targets=BUNDLED_TARGETS_DIR))
        )
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
        busy = self.job is not None or self.fit_active
        has_measurement = self.window.active_measurement_path() is not None
        self.headphone_cta.setVisible(not has_measurement and self.window.active_spec.allows_headphone_selection)
        self.update_generate_label()
        self.generate.setEnabled(not busy and self.current_entry() is not None and has_measurement)
        self.generate.setStyleSheet(PRIMARY_ACTION_STYLE)
        self.targets.setEnabled(not busy)
        self.search.setEnabled(not busy)
        self.mode.setEnabled(not busy)
        self.source_filter.setEnabled(not busy)
        self.fit_range.setEnabled(not busy)
        self.cancel.setEnabled(self.fit_active and not self.fit_cancelled)
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

    def set_catalog_error(self, detail: str) -> None:
        self.catalog_error_detail = detail
        self.catalog_error.setText(f'<a href="report">{escape(tr("autoeq.error_status"))}</a>' if detail else "")
        description = tr("autoeq.error_report_hint", error=detail) if detail else ""
        self.catalog_error.setToolTip(f"<p>{escape(description)}</p>" if description else "")
        self.catalog_error.setAccessibleName(tr("autoeq.error_status"))
        self.catalog_error.setAccessibleDescription(description)
        self.catalog_error.setVisible(bool(detail))

    def report_catalog_error(self) -> None:
        if self.catalog_error_detail:
            self.window.open_github_issue(
                "bug_report.yml",
                area="AutoEq / EQ Optimizer",
                summary=self.catalog_error_detail,
                diagnostics=f"{self.window.diagnostic_summary()}\nAutoEq: {self.catalog_error_detail}",
            )

    def download_catalog(self) -> None:
        self.set_catalog_error("")
        self.status.clear()
        self.catalog_progress.setText(tr("autoeq.loading_catalog"))
        self.start_job(lambda: catalog.download_index(self.index_path), self.catalog_downloaded)

    def catalog_downloaded(self, entries, error: str) -> None:
        self.catalog_progress.clear()
        if error:
            self.status.clear()
            self.set_catalog_error(tr("autoeq.catalog_failed", error=error))
            return
        local_entries = [
            entry
            for entry in self.entries
            if entry.local and not (entry.kind == "target" and Path(entry.path).parent == BUNDLED_TARGETS_DIR)
        ]
        merged = [*local_entries, *entries]
        merged.extend(self._bundled_target_fallbacks(merged))
        self.entries = merged
        self.update_results()

    def open_catalog(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Wybierz folder repozytorium AutoEq")
        if path:
            self.set_catalog_error("")
            self.status.clear()
            self.catalog_progress.setText(tr("autoeq.indexing_catalog"))
            self.start_job(lambda: self.index_local_catalog(Path(path)), self.catalog_opened)

    def index_local_catalog(self, root: Path) -> list[catalog.Entry]:
        entries = catalog.scan_checkout(root)
        catalog.save_index(self.local_index_path, entries)
        return entries

    def catalog_opened(self, entries, error: str) -> None:
        self.catalog_progress.clear()
        if error:
            self.status.clear()
            self.set_catalog_error(error)
            return
        self.entries = [
            entry
            for entry in self.entries
            if not entry.local or entry.source == "Plik lokalny" or Path(entry.path).parent == BUNDLED_TARGETS_DIR
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
        if entry is None or self.job is not None or self.fit_active:
            return
        self.result = None
        self.result_entry = entry
        self.result_range = self.fit_range.currentData()
        self.result_options = self.current_fit_options()
        self.fit_active = True
        self.fit_cancelled = False
        self.fit_status.setText(tr("autoeq.reading_target"))
        self.start_job(
            lambda: catalog.resolve_curve(entry, self.cache_directory / "curves", bundled_targets=BUNDLED_TARGETS_DIR),
            self.start_fit,
        )

    def start_fit(self, target, error: str) -> None:
        if self.fit_cancelled:
            self.finish_fit()
            return
        if error:
            self.fit_status.setText(tr("autoeq.target_error", error=error))
            self.finish_fit()
            return
        try:
            self.target_curve = read_target_curve(target)
        except (OSError, ValueError) as exc:
            self.fit_status.setText(tr("autoeq.target_error", error=exc))
            self.finish_fit()
            return
        spec = self.window.active_spec
        self.fit_factory = self.window.factory_profile
        measurement = self.window.active_measurement_path()
        if measurement is None:
            self.fit_status.setText(tr("autoeq.dongle_needs_measurement", model=spec.display_name))
            self.finish_fit()
            return
        if not measurement.exists():
            self.fit_status.setText(tr("autoeq.missing_measurement"))
            self.finish_fit()
            return
        try:
            self.temporary = TemporaryDirectory(prefix="dsp-control-autoeq-")
            work = Path(self.temporary.name)
            if (
                self.window.headphone_selection.mode == "default"
                and spec.acoustics.measurement_includes_factory_eq
                and self.fit_factory is not None
            ):
                measured = self.window.active_measurement_curve()
                offsets = response_points(self.fit_factory, [hz for hz, _ in measured])
                if measured and len(offsets) == len(measured):
                    measurement = work / f"{spec.model_id}-no-factory.csv"
                    measurement.write_text(
                        "frequency,raw\n"
                        + "".join(
                            f"{hz},{db - offset}\n" for (hz, db), (_, offset) in zip(measured, offsets, strict=False)
                        )
                    )
        except OSError as exc:
            self.fit_status.setText(tr("autoeq.fit_error", error=exc))
            self.finish_fit()
            return
        self.output = work / "profile.json"
        self.fit_timer.start()
        python = DATA_DIR.parent / ".venvs/autoeq/bin/python"
        max_fc, fit_bands = self.result_range
        min_q, max_q = spec.dsp.q_range
        min_gain, max_gain = spec.dsp.gain_range_db
        pre_min, pre_max = spec.dsp.preamp_range_db
        self.fit_status.setText(tr("autoeq.calculating", bands=fit_bands))
        bass_boost, tilt, pk_only = self.result_options or self.current_fit_options()
        argv = [
            str(Path(__file__).with_name("eq_fit.py")),
            "-m",
            str(measurement),
            "-t",
            str(target),
            "-o",
            str(self.output),
            "--fs",
            str(spec.dsp.sample_rate_hz),
            "--slot",
            str(spec.dsp.slots.custom),
            "--model-id",
            spec.model_id,
            "--device-name",
            spec.display_name,
            "--usb",
            spec.usb_id_str,
            "--min-q",
            str(min_q),
            "--max-q",
            str(max_q),
            "--cut-max",
            str(max(min_gain, -12.0)),
            "--boost-max",
            str(min(max_gain, 6.0)),
            "--preamp-min",
            str(pre_min),
            "--preamp-max",
            str(pre_max),
            "--max-fc",
            str(max_fc),
            "--bands",
            str(fit_bands),
            "--bass-boost",
            str(bass_boost),
            "--tilt",
            str(tilt),
        ]
        if pk_only:
            argv.append("--no-shelves")
        self.process.start(
            str(python if python.is_file() else Path(sys.executable)),
            argv,
        )
        self.update_actions()
        self.preview_changed.emit()

    def fit_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self.fit_status.setText(tr("autoeq.fit_error", error=self.process.errorString()))
            self.finish_fit()

    def fit_timeout(self) -> None:
        self.fit_cancelled = True
        self.fit_status.setText(tr("autoeq.fit_timeout"))
        self.process.kill()

    def cancel_fit(self) -> None:
        self.fit_cancelled = True
        self.fit_status.setText(tr("autoeq.fit_cancelled"))
        self.cancel.setEnabled(False)
        self.process.kill()

    def fit_finished(self, code: int, _exit_status) -> None:
        stderr = bytes(self.process.readAllStandardError()).decode(errors="replace")
        self.process.readAllStandardOutput()
        if self.fit_cancelled:
            pass
        elif code != 0:
            message = next((line for line in reversed(stderr.splitlines()) if line.strip()), "")
            self.fit_status.setText(tr("autoeq.fit_error", error=message))
        else:
            try:
                spec = self.window.active_spec
                hp_label = self.window.active_headphone_label()
                name = f"{hp_label} → {self.result_entry.name}"
                loaded = load_profile(self.output, name, pad_bands=True, spec=spec)
                self.result = replace(
                    loaded,
                    source=f"AutoEq · {self.result_entry.source}",
                    target_name=self.result_entry.name,
                    target_curve=self.target_curve,
                    fit_range=self.result_range,
                    headphone_name=self.window.active_headphone_name(),
                    headphone_selection=self.window.headphone_selection.to_dict(),
                )
            except (OSError, ValueError, dac.HidError) as exc:
                self.fit_status.setText(tr("autoeq.fit_error", error=exc))
            else:
                self.fit_status.clear()
        self.finish_fit()

    def finish_fit(self) -> None:
        self.fit_timer.stop()
        self.fit_active = False
        if self.temporary is not None:
            self.temporary.cleanup()
            self.temporary = None
        self.update_actions()
        self.preview_changed.emit()

    def reset_preview(self) -> None:
        self.result_entry = None
        if self.fit_active:
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


class ElidingLabel(FeedbackLabel):
    def __init__(self, text: str = "", *, retain_hidden: bool = False):
        super().__init__(text)
        self._retain_hidden = retain_hidden
        if retain_hidden:
            policy = self.sizePolicy()
            policy.setRetainSizeWhenHidden(True)
            self.setSizePolicy(policy)
            self.setMinimumHeight(self.fontMetrics().lineSpacing())

    def set_title(self, title: str, *, wrap: bool, detail: str = "", compact: str = "") -> None:
        self.full_title = title
        self.detail = detail
        self.compact_title = compact
        self.setWordWrap(wrap)
        policy = QSizePolicy(
            QSizePolicy.Policy.Preferred if wrap else QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        policy.setRetainSizeWhenHidden(self._retain_hidden)
        self.setSizePolicy(policy)
        self.setAccessibleName(title)
        self.setAccessibleDescription(detail)
        self.update_text()
        self.setVisible(bool(title))

    def update_text(self) -> None:
        title = self.full_title
        if not self.wordWrap():
            metrics = self.fontMetrics()
            width = self.contentsRect().width()
            if self.compact_title and metrics.horizontalAdvance(title) > width:
                title = self.compact_title
            title = metrics.elidedText(title, Qt.TextElideMode.ElideRight, width)
        QLabel.setText(self, title)
        parts = (
            (self.full_title, self.detail) if title != self.full_title and not self.compact_title else (self.detail,)
        )
        self.setToolTip("\n\n".join(filter(None, parts)))

    def clear(self) -> None:
        self.full_title = ""
        self.detail = ""
        self.compact_title = ""
        super().clear()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "full_title") and not self.wordWrap():
            self.update_text()


class ProfilesWindow(QWidget):
    def __init__(self, demo: bool, library_directory: Path | None = None, *, demo_model_id: str = DEFAULT_MODEL_ID):
        super().__init__()
        self.setStyleSheet(APP_STYLE)
        self.setAcceptDrops(True)
        self.setMinimumSize(720, 500)
        size_to_screen(self, 1140, 820)
        app_data = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
        if library_directory is None and not app_data.exists():
            legacy_data = app_data.with_name(LEGACY_STORAGE_NAME)
            if legacy_data.is_dir():
                with contextlib.suppress(OSError):
                    shutil.copytree(legacy_data, app_data, dirs_exist_ok=True)
        self.library_directory = library_directory or app_data / ("profiles-demo" if demo else "profiles")
        self.settings_path = self.library_directory.parent / "settings.json"
        lang_pref = i18n.load_language_preference(self.settings_path)
        i18n.set_language(lang_pref, locale_name=QLocale.system().name())
        self.setWindowTitle(tr("app.title"))
        self.theme_pref = load_theme_preference(self.settings_path)
        app_instance = QApplication.instance()
        self.system_dark = (
            app_instance.styleHints().colorScheme() == Qt.ColorScheme.Dark if app_instance is not None else False
        )
        self.apply_theme(self.theme_pref)
        if app_instance is not None:
            app_instance.styleHints().colorSchemeChanged.connect(self.on_system_scheme_changed)

        self.demo = demo
        self.active_spec: DeviceSpec = get_device_spec(demo_model_id)
        self.headphone_selection: HeadphoneSelection = load_headphone_selection(self.settings_path, self.active_spec)
        self.resolved_headphone_path: Path | None = None
        self.headphone_loading = False
        self.headphone_job: Job | None = None
        self.demo_forced_rate = 0
        self.observed_forced_rate = None
        demo_device = DemoDevice(self.active_spec.model_id) if demo else None
        self.open_device = (lambda _path=None: demo_device) if demo else open_dac
        self.list_devices = (
            (lambda: [DeviceChoice(demo_device.path, demo_device.model_name)]) if demo else hardware_choices
        )
        self.device_choices: list[DeviceChoice] = []
        self.selected_target: DeviceTarget | None = None
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.job = None
        self.command_active = False
        self.editor_active = False
        self.pending_command = None
        self.state = None
        self.last_applied_profile = None
        self.previous_dac_profile = None
        self.readback_profile = None
        self.factory_profile = self._default_factory_profile(self.active_spec)
        self.builtin_items: list[QListWidgetItem] = []
        self.preview_sources = None
        self.applying_profile = None
        self.applying_restore = False
        self.apply_error = ""
        self.apply_notice = ""
        self.tray = None
        self.allow_quit = False
        self.tray_notice_shown = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 12)
        layout.setSpacing(12)
        self.heading = QLabel(tr("app.title"))
        font = self.heading.font()
        font.setPointSizeF(font.pointSizeF() * 1.55)
        font.setBold(True)
        self.heading.setFont(font)
        self.connection = ElidingLabel()
        self.connection.setTextFormat(Qt.TextFormat.PlainText)
        self.connection.setStyleSheet(STATUS_PILL_STYLE)
        self.connection.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.set_connection_status("status.demo" if demo else "status.searching")
        header = QHBoxLayout()
        header.addWidget(self.heading)
        header.addStretch()
        header.addWidget(self.connection, 1, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(header)
        self.connection_problem = FeedbackLabel()
        self.connection_problem.setTextFormat(Qt.TextFormat.PlainText)
        self.connection_problem.setWordWrap(True)
        layout.addWidget(self.connection_problem)
        self.latest_release_url = ""
        self.update_job = None
        self.update_banner = QFrame()
        self.update_banner.setObjectName("updateBanner")
        self.update_banner.setVisible(False)
        banner_layout = QHBoxLayout(self.update_banner)
        banner_layout.setContentsMargins(10, 6, 10, 6)
        banner_layout.setSpacing(8)
        self.update_banner_label = QLabel()
        self.update_banner_label.setTextFormat(Qt.TextFormat.PlainText)
        self.update_banner_label.setWordWrap(True)
        banner_layout.addWidget(self.update_banner_label, 1)
        self.update_open_btn = QPushButton(tr("updates.open_release"))
        self.update_open_btn.setStyleSheet(PRIMARY_ACTION_STYLE)
        self.update_open_btn.clicked.connect(self.open_update_release)
        banner_layout.addWidget(self.update_open_btn)
        self.update_copy_cmd_btn = QPushButton(tr("updates.copy_flatpak_cmd"))
        self.update_copy_cmd_btn.setToolTip("flatpak update pl.innovibe.DspControl")
        self.update_copy_cmd_btn.setVisible(Path("/.flatpak-info").exists())
        self.update_copy_cmd_btn.clicked.connect(self.copy_flatpak_update_command)
        banner_layout.addWidget(self.update_copy_cmd_btn)
        self.update_dismiss_btn = QPushButton(tr("updates.dismiss"))
        self.update_dismiss_btn.clicked.connect(lambda: self.update_banner.setVisible(False))
        banner_layout.addWidget(self.update_dismiss_btn)
        layout.addWidget(self.update_banner)
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
        self.device_select_label = QLabel(tr("device.selected_model"))
        self.device_select = QComboBox()
        self.device_select.setAccessibleName(self.device_select_label.text())
        self.device_select.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.device_select.setMinimumContentsLength(12)
        self.device_select_label.setBuddy(self.device_select)
        details.addWidget(self.device_select_label, 0, 0)
        details.addWidget(self.device_select, 0, 1)
        self.update_device_choices([])
        self.device_select.currentIndexChanged.connect(self.change_device)
        self.active_slot = QLabel("—")
        self.active_profile = QLabel("—")
        self.preamp = QLabel("—")
        self.firmware = QLabel("—")
        self.global_gain = QLabel("—")
        self.mic_gain = QLabel("—")
        self.detail_labels: dict[str, QLabel] = {}
        for row, key, value in (
            (1, "device.profile", self.active_profile),
            (2, "device.preamp", self.preamp),
            (3, "device.active_slot", self.active_slot),
        ):
            value.setTextFormat(Qt.TextFormat.PlainText)
            value.setWordWrap(True)
            lbl = QLabel(tr(key))
            self.detail_labels[key] = lbl
            details.addWidget(lbl, row, 0)
            details.addWidget(value, row, 1)
        self.gains_box = QGroupBox(tr("device.gain_group"))
        gains_grid = QGridLayout(self.gains_box)
        gains_grid.setColumnStretch(0, 1)
        self.global_gain_button = QPushButton(tr("device.adjust"))
        self.global_gain_button.setAccessibleName(tr("device.output_gain"))
        self.global_gain_button.setEnabled(False)
        self.output_gain_label = QLabel(tr("device.output_gain"))
        self.mic_gain_button = QPushButton(tr("device.adjust"))
        self.mic_gain_button.setAccessibleName(tr("device.microphone"))
        self.mic_gain_button.setEnabled(False)
        self.mic_gain_label = QLabel(tr("device.microphone"))
        for row, label, value, button in (
            (0, self.output_gain_label, self.global_gain, self.global_gain_button),
            (1, self.mic_gain_label, self.mic_gain, self.mic_gain_button),
        ):
            gains_grid.addWidget(label, row, 0)
            gains_grid.addWidget(value, row, 1, Qt.AlignmentFlag.AlignRight)
            gains_grid.addWidget(button, row, 2)
        self.backup_button = QPushButton(tr("device.export_dac"))
        self.backup_button.setEnabled(False)
        self.defaults_button = QPushButton(tr("device.factory_reset"))
        self.defaults_button.setEnabled(False)
        self.maintenance_box = QGroupBox(tr("device.backup_group"))
        self.device_actions = QBoxLayout(QBoxLayout.Direction.TopToBottom, self.maintenance_box)
        self.device_actions.setSpacing(8)
        for button in (self.backup_button, self.defaults_button):
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            self.device_actions.addWidget(button, 1, Qt.AlignmentFlag.AlignTop)
        self.device_actions.addStretch()
        self.maintenance_box.installEventFilter(self)

        self.playback_box = QGroupBox(tr("device.playback_group"))
        playback_form = QFormLayout(self.playback_box)
        playback_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        playback_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        playback_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.playback_format = QLabel("—")
        self.playback_format.setTextFormat(Qt.TextFormat.PlainText)
        self.playback_format.setWordWrap(True)
        self.playback_rate = QLabel("—")
        self.playback_rate.setTextFormat(Qt.TextFormat.PlainText)
        self.playback_rate.setWordWrap(True)
        self.playback_stream_label = QLabel(tr("device.active_stream"))
        self.playback_rate_label = QLabel(tr("device.sample_rate"))
        self.playback_force_label = QLabel(tr("device.force_rate"))
        playback_form.addRow(self.playback_stream_label, self.playback_format)

        rate_row = QHBoxLayout()
        self.sample_rate_combo = QComboBox()
        self.sample_rate_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.sample_rate_combo.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.sample_rate_combo.setAccessibleName(tr("device.force_rate"))
        self.sample_rate_combo.addItem(tr("device.rate_auto"), 0)
        for rate in UAC2_SAMPLE_RATES:
            self.sample_rate_combo.addItem(format_rate_khz(rate), rate)
        self.apply_rate_button = QPushButton(tr("device.apply"))
        self.apply_rate_button.setAccessibleName(tr("device.apply"))
        self.refresh_rate_button = QPushButton(tr("device.refresh"))
        self.refresh_rate_button.setAccessibleName(tr("device.refresh"))
        rate_row.addWidget(self.sample_rate_combo, 1)
        rate_row.addWidget(self.apply_rate_button)
        rate_row.addWidget(self.refresh_rate_button)
        rate_row.addStretch(2)
        self.playback_force_label.setBuddy(self.sample_rate_combo)
        playback_form.addRow(self.playback_force_label, rate_row)

        self.pipewire_scope = QLabel(tr("device.pipewire_scope"))
        self.pipewire_scope.setWordWrap(True)
        playback_form.addRow(self.pipewire_scope)

        self.usb_details = QToolButton()
        self.usb_details.setText(tr("device.usb_details"))
        self.usb_details.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.usb_details.setArrowType(Qt.ArrowType.RightArrow)
        self.usb_details.setCheckable(True)
        playback_form.addRow(self.usb_details)
        usb_content = QWidget()
        usb_form = QFormLayout(usb_content)
        usb_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        usb_form.setContentsMargins(0, 4, 0, 0)
        usb_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        usb_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.detail_labels["device.firmware"] = QLabel(tr("device.firmware"))
        usb_form.addRow(self.detail_labels["device.firmware"], self.firmware)
        self.raw_stream_label = QLabel(tr("device.usb_format"))
        self.playback_raw = QLabel("—")
        self.playback_raw.setTextFormat(Qt.TextFormat.PlainText)
        self.playback_raw.setWordWrap(True)
        usb_form.addRow(self.raw_stream_label, self.playback_raw)
        usb_form.addRow(self.playback_rate_label, self.playback_rate)

        modes_text = " · ".join(
            f"Alt {alt} · {fmt} ({tr('device.bit_depth', bits=bits)})" for alt, fmt, bits in UAC2_PLAYBACK_MODES
        )
        self.playback_hint = QLabel(tr("device.playback_hint", modes=modes_text))
        self.playback_hint.setWordWrap(True)
        self.playback_hint.setTextFormat(Qt.TextFormat.PlainText)
        usb_form.addRow(self.playback_hint)
        playback_form.addRow(usb_content)
        usb_content.hide()
        self.usb_details.toggled.connect(usb_content.setVisible)
        self.usb_details.toggled.connect(
            lambda opened: self.usb_details.setArrowType(Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow)
        )

        self.language_box = QGroupBox(tr("device.language_group"))
        lang_form = QFormLayout(self.language_box)
        lang_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        lang_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
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

        device_layout.addWidget(self.device_box, 0, 0)
        device_layout.addWidget(self.gains_box, 0, 1)
        device_layout.addWidget(self.playback_box, 1, 0, 1, 2)
        device_layout.addWidget(self.maintenance_box, 2, 0)
        device_layout.addWidget(self.language_box, 2, 1)
        device_layout.setRowStretch(3, 1)

        device_scroll = scroll_content(device_page)

        self.profile_page = QWidget()
        profile_layout = QVBoxLayout(self.profile_page)
        profile_layout.setContentsMargins(0, 12, 0, 0)
        profile_layout.setSpacing(0)
        library_split = QSplitter(Qt.Orientation.Horizontal)
        library_split.setChildrenCollapsible(False)
        library_split.setHandleWidth(16)
        source_panel = self.source_panel = QFrame()
        source_panel.setObjectName("sourceCard")
        source_layout = self.source_layout = QVBoxLayout(source_panel)
        source_layout.setContentsMargins(12, 12, 12, 10)
        source_layout.setSpacing(8)
        source_buttons = QHBoxLayout()
        source_buttons.setSpacing(0)
        self.source_group = QButtonGroup(self)
        for index, (key, _, _) in enumerate(SOURCE_LABELS):
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
        self.profiles.setMouseTracking(True)
        self.profiles.setAccessibleName(tr("tuning.library"))
        self.profiles.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.profiles.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.profiles.setMinimumWidth(205)
        self.profiles.setMinimumHeight(162)
        self.user_heading = None
        self.builtin_heading = self.add_library_heading(tr("tuning.builtin"))
        self.factory_item: QListWidgetItem | None = None
        self.flat_item: QListWidgetItem | None = None
        initial_profile = self.rebuild_builtin_profiles(self.active_spec)
        library_layout.addWidget(self.profiles, 1)
        self.sources.addWidget(library)
        self.autoeq_panel = AutoEqPanel(self, self.library_directory.parent / "autoeq")
        self.autoeq_panel.sync_device_spec(self.active_spec)
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
        self.save_setup_action = add_menu.addAction(tr("actions.save_setup"), self.save_current_setup)
        add_menu.addSeparator()
        self.new_profile_action = add_menu.addAction(tr("actions.new_empty"), lambda: self.edit_profile(new=True))
        self.import_profile_action = add_menu.addAction(tr("actions.import_profile"), self.import_profile)
        self.import_bundle_action = add_menu.addAction(tr("actions.import_bundle"), self.import_library_bundle)
        self.add_button.setMenu(add_menu)
        self.more_button = QToolButton()
        self.more_button.setText(tr("actions.more"))
        self.more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more_menu = QMenu(self.more_button)
        self.duplicate_action = more_menu.addAction(tr("actions.duplicate"), lambda: self.edit_profile(duplicate=True))
        self.export_action = more_menu.addAction(tr("actions.export_selected"), self.export_selected)
        self.export_bundle_action = more_menu.addAction(tr("actions.export_bundle"), self.export_library_bundle)
        more_menu.addSeparator()
        self.delete_action = more_menu.addAction(tr("actions.delete_profile"), self.delete_selected)
        self.more_button.setMenu(more_menu)
        library_actions.addWidget(self.add_button)
        library_actions.addWidget(self.more_button)
        library_actions.addStretch()
        self.catalog_actions = QWidget()
        catalog_actions = QHBoxLayout(self.catalog_actions)
        catalog_actions.setContentsMargins(0, 0, 0, 0)
        catalog_actions.setSpacing(6)
        catalog_actions.addWidget(self.autoeq_panel.catalog_button)
        self.autoeq_panel.status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        status_policy = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        status_policy.setRetainSizeWhenHidden(True)
        self.autoeq_panel.status.setSizePolicy(status_policy)
        catalog_actions.addWidget(self.autoeq_panel.status, 1, Qt.AlignmentFlag.AlignVCenter)
        tool_height = max(
            self.add_button.sizeHint().height(),
            self.more_button.sizeHint().height(),
            self.autoeq_panel.catalog_button.sizeHint().height(),
        )
        for button in (self.add_button, self.more_button, self.autoeq_panel.catalog_button):
            button.setFixedHeight(tool_height)
        source_actions.addWidget(self.library_actions, 1)
        source_actions.addWidget(self.catalog_actions, 1)
        source_layout.addLayout(source_actions)
        library_split.addWidget(source_panel)
        preview_card = QFrame()
        preview_card.setObjectName("previewCard")
        card = QVBoxLayout(preview_card)
        card.setContentsMargins(12, 10, 12, 10)
        card.setSpacing(8)

        self.preview_title = ElidingLabel()
        self.preview_title.setTextFormat(Qt.TextFormat.PlainText)
        title_font = self.preview_title.font()
        title_font.setPointSizeF(title_font.pointSizeF() * 1.2)
        title_font.setBold(True)
        self.preview_title.setFont(title_font)
        self.profile_info = ElidingLabel(retain_hidden=True)
        self.profile_info.setTextFormat(Qt.TextFormat.PlainText)
        self.active_summary = ElidingLabel()
        self.active_summary.setTextFormat(Qt.TextFormat.PlainText)

        preview_panel = QWidget()
        preview = QVBoxLayout(preview_panel)
        preview.setContentsMargins(0, 0, 5, 0)
        preview.setSpacing(6)
        preview.addWidget(self.preview_title)
        preview.addWidget(self.profile_info)
        preview.addWidget(self.active_summary)
        self.headphone_bar = QWidget()
        hp_row = QHBoxLayout(self.headphone_bar)
        hp_row.setContentsMargins(0, 2, 0, 2)
        hp_row.setSpacing(6)
        self.headphone_label = QLabel(tr("headphone.label"))
        self.headphone_combo = QComboBox()
        self.headphone_combo.setAccessibleName(tr("headphone.label"))
        self.headphone_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.headphone_combo.setMinimumContentsLength(4)
        self.headphone_combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.headphone_combo.currentIndexChanged.connect(self.on_headphone_combo_changed)
        self.headphone_choose_btn = QPushButton(tr("headphone.change"))
        self.headphone_choose_btn.clicked.connect(self.choose_headphones)
        self.headphone_flat_btn = QToolButton()
        self.headphone_flat_btn.setText(tr("headphone.flat_chip"))
        self.headphone_flat_btn.setToolTip(tr("headphone.use_flat"))
        self.headphone_flat_btn.clicked.connect(lambda: self.set_headphone_selection(HeadphoneSelection(mode="flat")))
        hp_row.addWidget(self.headphone_label)
        hp_row.addWidget(self.headphone_combo, 1)
        hp_row.addWidget(self.headphone_choose_btn)
        hp_row.addWidget(self.headphone_flat_btn)
        preview.addWidget(self.headphone_bar)

        self.compare_profile: Profile | None = None
        self.compare_bar = QWidget()
        cmp_row = QHBoxLayout(self.compare_bar)
        cmp_row.setContentsMargins(0, 0, 0, 0)
        cmp_row.setSpacing(6)
        self.compare_label = QLabel(tr("compare.label"))
        self.compare_combo = QComboBox()
        self.compare_combo.setAccessibleName(tr("compare.label"))
        self.compare_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.compare_combo.setMinimumContentsLength(4)
        self.compare_combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.compare_combo.addItem(tr("compare.dsp_default"), None)
        self.compare_combo.currentIndexChanged.connect(self._on_compare_combo_changed)
        self.compare_clear_btn = QToolButton()
        self.compare_clear_btn.setText("×")
        self.compare_clear_btn.setToolTip(tr("compare.clear_tooltip"))
        self.compare_clear_btn.setEnabled(False)
        self.compare_clear_btn.clicked.connect(self.clear_compare_profile)
        cmp_row.addWidget(self.compare_label)
        cmp_row.addWidget(self.compare_combo, 1)
        cmp_row.addWidget(self.compare_clear_btn)
        preview.addWidget(self.compare_bar)
        self.fit_controls = self.autoeq_panel.fit_controls
        self.fit_provenance = self.autoeq_panel.fit_provenance

        self.plot_switcher = QWidget()
        view_row = _FlowLayout(self.plot_switcher, spacing=6)
        view_row.setContentsMargins(0, 0, 0, 0)
        self.plot_view_group = QButtonGroup(self)
        for index, key in enumerate(("plot.view_response", "plot.view_eq")):
            button = QPushButton(tr(key))
            button.setCheckable(True)
            button.setStyleSheet(SEGMENT_BUTTON_STYLE)
            self.plot_view_group.addButton(button, index)
            view_row.addWidget(button)
        self.plot_view_group.button(0).setChecked(True)
        self.plot_view_group.idClicked.connect(self.update_plot_layout)
        preview.addWidget(self.plot_switcher)

        self.response_section = QWidget()
        response_layout = QVBoxLayout(self.response_section)
        response_layout.setContentsMargins(0, 0, 0, 0)
        response_layout.setSpacing(6)
        self.fr_title_label = QLabel(tr("plot.fr_title"))
        self.fr_title_label.setWordWrap(True)
        self.fr_title_label.setStyleSheet("font-weight: 600;")
        response_layout.addWidget(self.fr_title_label)
        self.preview_plot = ResponsePlot()
        self.preview_plot.set_measurement_curve(
            self.active_measurement_curve(), factory_slot=self.active_spec.dsp.slots.factory
        )
        response_layout.addWidget(self.preview_plot, 1)
        self.correction_plot = ResponsePlot(correction=True)
        self.preview_key = PlotKey(
            self.preview_plot,
            tuple(
                tr(key)
                for key in ("plot.key.selected", "plot.key.current_dsp", "plot.key.measured", "plot.key.target_short")
            ),
            linked_plots=[self.correction_plot],
            reserved_roles=(0, 1, 2, 3),
            order=(2, 0, 3, 1),
        )
        response_layout.addWidget(self.preview_key)
        summary_row = QHBoxLayout()
        summary_row.setSpacing(8)
        self.fit_summary = ElidingLabel()
        self.fit_summary.setTextFormat(Qt.TextFormat.PlainText)
        summary_row.addWidget(self.fit_summary, 1)
        self.fit_detail_button = QToolButton()
        self.fit_detail_button.setText(tr("plot.fit_more"))
        self.fit_detail_button.setAccessibleName(tr("plot.fit_disclosure"))
        self.fit_detail_button.clicked.connect(self.show_fit_details)
        summary_row.addWidget(self.fit_detail_button)
        response_layout.addLayout(summary_row)
        self.fit_details_text = ""

        self.plot_legend = QLabel()
        self.plot_legend.setTextFormat(Qt.TextFormat.PlainText)
        self.plot_legend.setWordWrap(True)
        response_layout.addWidget(self.plot_legend)
        preview.addWidget(self.response_section, 2)

        self.correction_section = QWidget()
        correction_layout = QVBoxLayout(self.correction_section)
        correction_layout.setContentsMargins(0, 0, 0, 0)
        correction_layout.setSpacing(6)
        self.correction_title = QLabel(tr("plot.eq_title"))
        self.correction_title.setWordWrap(True)
        self.correction_title.setStyleSheet("font-weight: 600;")
        correction_layout.addWidget(self.correction_title)
        correction_layout.addWidget(self.correction_plot, 1)
        self.correction_key = PlotKey(
            self.correction_plot,
            (tr("plot.key.profile_eq"), tr("plot.key.current_dsp")),
            linked_plots=[self.preview_plot],
            reserved_roles=(0, 1),
            order=(0, 1),
        )
        self.correction_key.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        self.preamp_summary = FeedbackLabel()
        self.preamp_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.preamp_summary.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        preamp_policy = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        preamp_policy.setRetainSizeWhenHidden(True)
        self.preamp_summary.setSizePolicy(preamp_policy)
        self.correction_footer = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.correction_footer.setContentsMargins(0, 0, 0, 0)
        self.correction_footer.setSpacing(12)
        self.correction_footer.addWidget(self.correction_key, 0, Qt.AlignmentFlag.AlignVCenter)
        self.correction_footer.addWidget(self.preamp_summary, 1, Qt.AlignmentFlag.AlignVCenter)
        correction_layout.addLayout(self.correction_footer)
        preview.addWidget(self.correction_section, 1)

        self.preview_scroll = scroll_content(preview_panel)
        # Rezerwuj szerokość paska także wtedy, gdy bieżąca treść mieści się w widoku.
        self.preview_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.preview_scroll.viewport().setAutoFillBackground(False)
        preview_panel.setAutoFillBackground(False)
        self.preview_scroll.viewport().installEventFilter(self)
        card.addWidget(self.preview_scroll, 1)
        self.apply_status = ElidingLabel()
        self.apply_status.setTextFormat(Qt.TextFormat.PlainText)
        for status_label in (self.autoeq_panel.fit_status, self.apply_status):
            status_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        # Pole pozostaje w układzie, żeby pojawienie się statusu nie zawijało przycisków.
        self.action_status_box = QWidget()
        self.action_status_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        compact_preamp = tr("tuning.applied_preamp_compact", actual=-0.0)
        self.action_status_min_w = self.apply_status.fontMetrics().horizontalAdvance(compact_preamp)
        self.action_status_box.setMinimumWidth(self.action_status_min_w)
        status_layout = QVBoxLayout(self.action_status_box)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(2)
        status_layout.addWidget(self.autoeq_panel.fit_status)
        status_layout.addWidget(self.apply_status)

        self.save_fit_button = QPushButton(tr("actions.save_later"))
        self.edit_button = QPushButton(tr("actions.edit_eq"))
        self.edit_button.setStyleSheet(SECONDARY_ACCENT_STYLE)
        self.edit_button.setIconSize(QSize(16, 16))
        self.apply_button = QPushButton(tr("actions.apply_dac"))
        self.apply_button.setStyleSheet(PRIMARY_ACTION_STYLE)
        self.apply_button.setEnabled(False)
        self.action_bar = QWidget()
        self.preview_actions = _FlowLayout(self.action_bar, spacing=8, align_right=True)
        self.preview_actions.setContentsMargins(0, 0, 0, 0)
        for button in (
            self.autoeq_panel.generate,
            self.autoeq_panel.cancel,
            self.save_fit_button,
            self.edit_button,
            self.apply_button,
        ):
            button.setMinimumHeight(34)
            self.preview_actions.addWidget(button)
        self.footer_bar = QWidget()
        self.footer_bar.setMinimumHeight(34)
        self.footer_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, self.footer_bar)
        self.footer_layout.setContentsMargins(0, 0, 0, 0)
        self.footer_layout.setSpacing(12)
        self.footer_layout.addWidget(self.action_status_box, 1, Qt.AlignmentFlag.AlignVCenter)
        self.footer_layout.addWidget(self.action_bar, 0, Qt.AlignmentFlag.AlignVCenter)
        self.action_primary_w = 0
        card.addWidget(self.footer_bar)

        library_split.addWidget(preview_card)
        source_panel.setMinimumWidth(245)
        source_panel.installEventFilter(self)
        library_split.setStretchFactor(0, 1)
        library_split.setStretchFactor(1, 3)
        library_split.setSizes([310, 800])
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
        links_layout = _FlowLayout(self.links_box, spacing=8)
        links_layout.setContentsMargins(10, 12, 10, 10)
        links_layout.setSpacing(10)
        self.guide_hub_btn = QPushButton(tr("help.open_hub"))
        self.guide_hub_btn.clicked.connect(lambda: self.open_external_url(OFFICIAL_HUB_URL))
        innovibe_icon = QIcon(str(INNOVIBE_ICON))
        self.guide_author_btn = QPushButton(tr("help.author_link"))
        self.guide_author_btn.setIcon(innovibe_icon)
        self.guide_author_btn.setToolTip(tr("footer.author_tooltip"))
        self.guide_author_btn.clicked.connect(lambda: self.open_external_url(tr("footer.author_url")))
        self.guide_support_box = QGroupBox(tr("help.support_group"))
        self.guide_support_box.setObjectName("guideSupport")
        self.guide_support_box.setStyleSheet(
            "QGroupBox#guideSupport { border-left: 3px solid palette(highlight); background: palette(alternate-base); }"
        )
        support_layout = QVBoxLayout(self.guide_support_box)
        self.guide_support_text = QLabel(tr("help.support_body"))
        self.guide_support_text.setWordWrap(True)
        support_layout.addWidget(self.guide_support_text)
        self.guide_coffee_btn = QPushButton(tr("help.coffee_link"))
        self.guide_coffee_btn.setStyleSheet(PRIMARY_ACTION_STYLE)
        self.guide_coffee_btn.setToolTip(tr("footer.coffee_tooltip"))
        self.guide_coffee_btn.clicked.connect(lambda: self.open_external_url(tr("footer.coffee_url")))
        support_layout.addWidget(self.guide_coffee_btn, 0, Qt.AlignmentFlag.AlignLeft)

        self.guide_updates_box = QGroupBox(tr("updates.group"))
        updates_row = QHBoxLayout(self.guide_updates_box)
        updates_row.setSpacing(12)
        self.check_update_btn = QPushButton(tr("updates.check_now"))
        self.check_update_btn.clicked.connect(lambda: self.check_for_updates(manual=True))
        updates_row.addWidget(self.check_update_btn)
        self.auto_update_check = QCheckBox(tr("updates.auto_check"))
        self.auto_update_check.setChecked(load_auto_update_check(self.settings_path))
        self.auto_update_check.toggled.connect(self._toggle_auto_update_check)
        updates_row.addWidget(self.auto_update_check)
        self.update_status_label = ElidingLabel()
        self.update_status_label.set_title("", wrap=False)
        updates_row.addWidget(self.update_status_label, 1)
        self.guide_version_label = QLabel(tr("help.version", version=APP_VERSION))
        self.guide_version_label.setTextFormat(Qt.TextFormat.PlainText)
        self.guide_version_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.guide_version_label.setStyleSheet("color: palette(placeholder-text);")
        updates_row.addWidget(self.guide_version_label)

        guide_layout.addWidget(self.why_box)
        guide_layout.addWidget(self.guide_tips_box)
        guide_layout.addWidget(self.links_box)
        guide_layout.addWidget(self.guide_support_box)
        guide_layout.addStretch()
        guide_layout.addWidget(self.guide_updates_box)
        self.tabs.addTab(scroll_content(guide_page), tr("tab.guide"))
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

        self.report_button = QToolButton()
        self.report_button.setText(tr("footer.report"))
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
        links_layout.addWidget(self.report_button)
        links_layout.addWidget(self.guide_author_btn)
        links_layout.addWidget(self.guide_hub_btn)
        self.apply_tooltips()
        self.update_accent_texts()
        self.ensurePolished()
        self.size_preview_actions()
        layout.activate()
        margins = layout.contentsMargins()
        minimum_page_width = max(device_layout.minimumSize().width(), guide_layout.minimumSize().width())
        scroll_width = self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
        required_width = minimum_page_width + margins.left() + margins.right() + scroll_width
        size_to_screen(self, max(self.width(), required_width), self.height())
        layout.activate()
        tab_style = QStyleOptionTabWidgetFrame()
        self.tabs.initStyleOption(tab_style)
        tab_contents = self.tabs.style().subElementRect(QStyle.SubElement.SE_TabWidgetTabContents, tab_style, self.tabs)
        page_height = max(
            max(page_layout.minimumSize().height(), page_layout.heightForWidth(tab_contents.width()))
            for page_layout in (device_layout, guide_layout)
        )
        size_to_screen(self, self.width(), self.height() + max(0, page_height - tab_contents.height()))
        self.update_source_labels()

        self.load_library()
        self.filter_profiles("")
        self.refresh_headphone_ui()
        self.update_plot_layout()
        self.profiles.currentItemChanged.connect(self.update_selection)
        self.profiles.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.profiles.customContextMenuRequested.connect(self._show_profile_context_menu)
        self._refresh_compare_combo()
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
        self._restore_last_profile(self.active_spec.model_id)
        self._ui_ready = True
        if not self.demo and load_auto_update_check(self.settings_path):
            QTimer.singleShot(1500, lambda: self.check_for_updates(manual=False))
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
        return self.autoeq_panel.ready_result() if self.catalog_selected() else self.selected_profile()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize:
            if watched is self.maintenance_box:
                self.update_device_actions_layout()
            elif watched is self.preview_scroll.viewport():
                self.update_plot_layout()
            elif watched is self.source_panel:
                self.update_source_labels()
        return super().eventFilter(watched, event)

    def update_source_labels(self) -> None:
        margin = self.source_layout.contentsMargins()
        available = self.source_panel.contentsRect().width() - margin.left() - margin.right()
        required = 0
        for index, (full, _, _) in enumerate(SOURCE_LABELS):
            button = self.source_group.button(index)
            option = QStyleOptionButton()
            option.initFrom(button)
            option.text = tr(full)
            text_size = QSize(button.fontMetrics().horizontalAdvance(option.text), button.fontMetrics().height())
            required += (
                button.style().sizeFromContents(QStyle.ContentsType.CT_PushButton, option, text_size, button).width()
            )
        for index, (full, short, tooltip) in enumerate(SOURCE_LABELS):
            button = self.source_group.button(index)
            button.setText(tr(short if available < required else full))
            button.setAccessibleName(tr(full))
            button.setToolTip(f"{tr(full)}\n{tr(tooltip)}")

    def update_device_actions_layout(self) -> None:
        margins = self.device_actions.contentsMargins()
        available = self.maintenance_box.contentsRect().width() - margins.left() - margins.right()
        required = 2 * max(self.backup_button.sizeHint().width(), self.defaults_button.sizeHint().width())
        wide = available >= required + self.device_actions.spacing()
        self.device_actions.setDirection(QBoxLayout.Direction.LeftToRight if wide else QBoxLayout.Direction.TopToBottom)

    @staticmethod
    def _measure_button_states(button: QPushButton, states: tuple[tuple[str, bool, str], ...]) -> tuple[int, int]:
        was_enabled = button.isEnabled()
        was_text = button.text()
        was_style = button.styleSheet()
        button.setMinimumSize(0, 0)
        button.setMaximumSize(16777215, 16777215)
        max_w, max_h = 0, 0
        for text, enabled, stylesheet in states:
            button.setEnabled(enabled)
            button.setText(text)
            button.setStyleSheet(stylesheet)
            button.ensurePolished()
            hint = button.sizeHint()
            max_w = max(max_w, hint.width())
            max_h = max(max_h, hint.height())
        button.setEnabled(was_enabled)
        button.setText(was_text)
        button.setStyleSheet(was_style)
        button.ensurePolished()
        return max_w, max_h

    def size_preview_actions(self) -> None:
        panel = self.autoeq_panel
        specs = (
            (
                self.apply_button,
                (
                    (tr("tuning.already_active"), False, PRIMARY_ACTION_STYLE),
                    (tr("actions.apply_dac"), True, PRIMARY_ACTION_STYLE),
                    (tr("actions.restore_previous"), True, SECONDARY_ACCENT_STYLE),
                ),
            ),
            (
                panel.generate,
                (
                    (tr("autoeq.compute"), True, PRIMARY_ACTION_STYLE),
                    (tr("autoeq.recompute"), True, PRIMARY_ACTION_STYLE),
                ),
            ),
            (
                panel.cancel,
                (
                    (tr("autoeq.cancel"), True, ""),
                    (tr("autoeq.cancel"), False, ""),
                ),
            ),
        )
        measured = [self._measure_button_states(button, states) for button, states in specs]
        primary_w = max(width for width, _ in measured)
        save_w, save_h = self._measure_button_states(
            self.save_fit_button,
            ((tr("actions.save_later"), True, ""), (tr("actions.saved"), False, "")),
        )
        edit_w, edit_h = self._measure_button_states(
            self.edit_button,
            ((tr("actions.edit_eq"), True, SECONDARY_ACCENT_STYLE),),
        )
        action_h = max(34, *(height for _, height in measured), save_h, edit_h)
        for button, width in (
            (self.apply_button, primary_w),
            (panel.generate, primary_w),
            (panel.cancel, primary_w),
            (self.save_fit_button, save_w),
            (self.edit_button, edit_w),
        ):
            button.setFixedSize(width, action_h)
        self.action_primary_w = primary_w
        compact_preamp = tr("tuning.applied_preamp_compact", actual=-0.0)
        self.action_status_min_w = self.apply_status.fontMetrics().horizontalAdvance(compact_preamp)
        self.footer_bar.setMinimumHeight(action_h)
        self.update_plot_layout()

    def update_plot_layout(self) -> None:
        compact = self.preview_scroll.width() < 560 or self.preview_scroll.height() < 505
        narrow = self.preview_scroll.width() < 560
        self.correction_footer.setDirection(
            QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight
        )
        self.correction_key.setSizePolicy(
            QSizePolicy.Policy.Preferred if narrow else QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Preferred,
        )
        self.preamp_summary.setWordWrap(narrow)
        self.preamp_summary.setAlignment(
            (Qt.AlignmentFlag.AlignLeft if narrow else Qt.AlignmentFlag.AlignRight) | Qt.AlignmentFlag.AlignVCenter
        )
        has_acoustic = bool(self.active_measurement_curve())
        self.plot_switcher.setVisible(compact and has_acoustic)
        self.response_section.setVisible(has_acoustic and (not compact or self.plot_view_group.checkedId() == 0))
        self.correction_section.setVisible((not has_acoustic) or (not compact or self.plot_view_group.checkedId() == 1))
        footer_w = self.preview_scroll.width()
        min_side_by_side = self.action_status_min_w + self.footer_layout.spacing() + self.action_primary_w
        stack_footer = footer_w > 0 and footer_w < min_side_by_side
        self.footer_layout.setDirection(
            QBoxLayout.Direction.TopToBottom if stack_footer else QBoxLayout.Direction.LeftToRight
        )
        self.action_status_box.setMinimumWidth(0 if stack_footer else self.action_status_min_w)
        self.footer_layout.setStretchFactor(self.action_status_box, 0 if stack_footer else 1)
        self.footer_layout.setStretchFactor(self.action_bar, 0)
        self.footer_layout.setAlignment(
            self.action_status_box, Qt.AlignmentFlag.AlignLeft if stack_footer else Qt.AlignmentFlag.AlignVCenter
        )
        self.footer_layout.setAlignment(
            self.action_bar, Qt.AlignmentFlag.AlignRight if stack_footer else Qt.AlignmentFlag.AlignVCenter
        )

    def show_fit_details(self) -> None:
        if not self.fit_details_text:
            return
        box = QMessageBox(self)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        box.setWindowTitle(tr("plot.fit_disclosure"))
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(self.fit_summary.text())
        box.setInformativeText(self.fit_details_text)
        box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.setStandardButtons(QMessageBox.StandardButton.Close)
        box.button(QMessageBox.StandardButton.Close).setText(tr("plot.fit_close"))
        box.open()

    @staticmethod
    def _default_factory_profile(spec: DeviceSpec) -> Profile | None:
        if spec.has_factory_slot and spec.acoustics.factory_bands:
            return Profile(
                "Fabryczny EQ",
                spec.dsp.slots.factory,
                spec.factory_bands_copy(),
                0.0,
                sample_rate_hz=spec.dsp.sample_rate_hz,
                model_id=spec.model_id,
            )
        return None

    def profile_matches_active_model(self, profile: Profile) -> bool:
        if profile.model_id is not None:
            return profile.model_id == self.active_spec.model_id
        if self.active_spec.has_factory_slot and profile.slot == self.active_spec.dsp.slots.factory:
            return True
        return len(profile.bands) == self.active_spec.dsp.band_count

    def rebuild_builtin_profiles(self, spec: DeviceSpec) -> QListWidgetItem | None:
        for item in self.builtin_items:
            row = self.profiles.row(item)
            if row >= 0:
                self.profiles.takeItem(row)
        self.builtin_items = []
        self.factory_item = None
        self.flat_item = None
        insert_row = self.profiles.row(self.builtin_heading) + 1

        def insert_builtin(profile: Profile) -> QListWidgetItem:
            nonlocal insert_row
            item = QListWidgetItem(profile.name)
            item.setData(PROFILE_ROLE, profile)
            item.setToolTip(profile.name)
            self.profiles.insertItem(insert_row, item)
            insert_row += 1
            self.builtin_items.append(item)
            return item

        if spec.has_factory_slot:
            self.factory_item = insert_builtin(
                Profile(
                    tr("tuning.factory"),
                    spec.dsp.slots.factory,
                    [],
                    None,
                    sample_rate_hz=spec.dsp.sample_rate_hz,
                    model_id=spec.model_id,
                )
            )
        self.flat_item = insert_builtin(
            Profile(
                tr("profile.flat_bypass"),
                spec.dsp.slots.custom,
                default_custom_bands(spec),
                0.0,
                sample_rate_hz=spec.dsp.sample_rate_hz,
                model_id=spec.model_id,
            )
        )
        initial: QListWidgetItem | None = self.flat_item
        for bp in spec.builtin_profiles:
            try:
                loaded = load_profile(bp.path, bp.name, spec=spec)
            except (OSError, ValueError, dac.HidError):
                continue
            item = insert_builtin(loaded)
            if initial is self.flat_item:
                initial = item
        return initial

    def active_measurement_path(self) -> Path | None:
        sel = self.headphone_selection
        if sel.mode == "default":
            return self.active_spec.acoustics.measurement_path
        if sel.mode == "file":
            p = Path(sel.path)
            return p if p.is_file() else None
        if sel.mode == "autoeq":
            if self.resolved_headphone_path is not None and self.resolved_headphone_path.is_file():
                return self.resolved_headphone_path
            panel = getattr(self, "autoeq_panel", None)
            cache_base = panel.cache_directory if panel is not None else (self.library_directory.parent / "autoeq")
            cache_dir = cache_base / "curves"
            key = hashlib.sha256(f"{sel.path}\n{sel.revision}".encode()).hexdigest()
            cached = cache_dir / f"{key}.csv"
            return cached if cached.is_file() else None
        return None

    def active_measurement_curve(self) -> list[tuple[float, float]]:
        sel = self.headphone_selection
        if sel.mode == "default":
            return self.active_spec.measured_curve()
        path = self.active_measurement_path()
        if path is None:
            return []
        return list(load_measurement_curve_from_path(str(path)))

    def active_headphone_name(self) -> str | None:
        sel = self.headphone_selection
        if sel.mode in ("autoeq", "file") and sel.name:
            return sel.name
        if sel.mode == "default":
            return self.active_spec.display_name
        return None

    def active_headphone_label(self) -> str:
        sel = self.headphone_selection
        if sel.mode in ("autoeq", "file") and sel.name:
            return sel.name
        return self.active_spec.display_name.removeprefix("MOONDROP:Gravity ").removeprefix("MOONDROP ")

    def refresh_headphone_ui(self) -> None:
        spec = self.active_spec
        show_bar = spec.allows_headphone_selection
        self.headphone_bar.setVisible(show_bar)
        if not show_bar:
            return
        sel = self.headphone_selection
        self.headphone_combo.blockSignals(True)
        self.headphone_combo.clear()
        if spec.has_default_headphone:
            short_name = spec.display_name.removeprefix("MOONDROP:Gravity ").removeprefix("MOONDROP ")
            self.headphone_combo.addItem(
                tr("headphone.default_item", model=short_name), HeadphoneSelection(mode="default")
            )
        self.headphone_combo.addItem(tr("headphone.flat_item"), HeadphoneSelection(mode="flat"))
        items = load_recent_headphones(self.settings_path, spec)
        if sel.mode in ("autoeq", "file") and all(item.key() != sel.key() for item in items):
            items = [sel, *items[: RECENT_HEADPHONES_LIMIT - 1]]
        if items:
            self.headphone_combo.insertSeparator(self.headphone_combo.count())
        for item in items:
            label = f"{item.name} ({item.source})" if item.source else item.name
            self.headphone_combo.addItem(label, item)
        selected_idx = 0
        for idx in range(self.headphone_combo.count()):
            data = self.headphone_combo.itemData(idx)
            if isinstance(data, HeadphoneSelection) and data.key() == sel.key():
                selected_idx = idx
                break
        self.headphone_combo.setCurrentIndex(selected_idx)
        self.headphone_combo.setToolTip(self.headphone_combo.currentText())
        self.headphone_combo.blockSignals(False)
        self.headphone_flat_btn.setVisible(sel.mode != "flat")

    def on_headphone_combo_changed(self) -> None:
        sel = self.headphone_combo.currentData()
        if isinstance(sel, HeadphoneSelection):
            self.set_headphone_selection(sel)

    def choose_headphones(self) -> None:
        if not self.active_spec.allows_headphone_selection:
            return
        recent = load_recent_headphones(self.settings_path, self.active_spec)
        dialog = HeadphonePickerDialog(self, self.active_spec, self.autoeq_panel.entries, recent=recent)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_headphone is not None:
            self.set_headphone_selection(dialog.selected_headphone)

    def set_headphone_selection(self, selection: HeadphoneSelection) -> None:
        self.headphone_selection = selection
        self.resolved_headphone_path = None
        save_headphone_selection(self.settings_path, self.active_spec, selection)
        self.refresh_headphone_ui()
        if selection.mode == "autoeq" and self.active_measurement_path() is None:
            self.headphone_loading = True
            self.headphone_combo.setEnabled(False)
            self.headphone_choose_btn.setEnabled(False)
            entry = catalog.Entry(
                name=selection.name,
                source=selection.source,
                kind="model",
                path=selection.path,
                local=False,
                revision=selection.revision,
            )
            panel = getattr(self, "autoeq_panel", None)
            cache_base = panel.cache_directory if panel is not None else (self.library_directory.parent / "autoeq")
            cache_dir = cache_base / "curves"

            def done(path, error: str) -> None:
                self.headphone_loading = False
                self.headphone_job = None
                self.headphone_combo.setEnabled(True)
                self.headphone_choose_btn.setEnabled(True)
                if error or path is None:
                    self.feedback.setText(tr("headphone.fetch_error", error=error or "unknown"))
                    self.set_headphone_selection(HeadphoneSelection(mode="flat"))
                    return
                self.resolved_headphone_path = Path(path)
                self._apply_active_measurement_curve()

            job = Job(lambda: catalog.resolve_curve(entry, cache_dir, bundled_targets=BUNDLED_TARGETS_DIR))
            self.headphone_job = job
            job.signals.finished.connect(done)
            self.pool.start(job)
            return
        self._apply_active_measurement_curve()

    def _apply_active_measurement_curve(self) -> None:
        spec = self.active_spec
        curve = self.active_measurement_curve()
        factory_slot = spec.dsp.slots.factory if self.headphone_selection.mode == "default" else None
        self.preview_plot.set_measurement_curve(curve, factory_slot=factory_slot)
        self.preview_plot.set_factory(
            self.factory_profile
            if (self.headphone_selection.mode == "default" and spec.acoustics.measurement_includes_factory_eq)
            else None
        )
        self.preview_sources = None
        self.autoeq_panel.update_actions()
        self.update_plot_layout()
        self.update_comparison()

    def apply_device_spec(self, spec: DeviceSpec) -> None:
        self.active_spec = spec
        self.headphone_selection = load_headphone_selection(self.settings_path, spec)
        self.resolved_headphone_path = None
        self.factory_profile = self._default_factory_profile(spec)
        self.refresh_headphone_ui()
        self._restoring_last_profile = True
        try:
            initial = self.rebuild_builtin_profiles(spec)
            self.autoeq_panel.sync_device_spec(spec)
            self.filter_profiles(self.profile_search.text())
            self._restore_last_profile(spec.model_id)
            current = self.profiles.currentItem()
            if (current is None or current.isHidden()) and initial is not None:
                self.profiles.setCurrentItem(initial)
        finally:
            self._restoring_last_profile = False
        self._apply_active_measurement_curve()
        self.update_selection()

    def _restore_last_profile(self, model_id: str) -> None:
        last_name = load_last_profile_for_model(self.settings_path, model_id)
        if not last_name:
            return
        for row in range(self.profiles.count()):
            item = self.profiles.item(row)
            if item.isHidden():
                continue
            prof = item.data(PROFILE_ROLE)
            if prof is not None and prof.name == last_name:
                self._restoring_last_profile = True
                try:
                    self.profiles.setCurrentItem(item)
                finally:
                    self._restoring_last_profile = False
                return

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
            matches = self.profile_matches_active_model(profile) and all(
                word in profile.name.casefold() for word in words
            )
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
        accent = "#ffb347" if dark else "#a83a08"
        if hasattr(self, "edit_button"):
            self.edit_button.setIcon(build_eq_sliders_icon(accent))
        if hasattr(self, "why_label"):
            self.why_label.setText(tr("help.why_body", accent=accent))
            self.guide_tips_label.setText(tr("help.tips_body", accent=accent))

    def apply_theme(self, theme_pref: str) -> None:
        dark = self.system_dark if theme_pref == "auto" else (theme_pref == "dark")
        app_instance = QApplication.instance()
        if app_instance is not None:
            app_instance.setPalette(build_innovibe_palette(dark))
        self.setStyleSheet(APP_STYLE)
        self.update_accent_texts()
        if hasattr(self, "apply_button"):
            self.size_preview_actions()
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

    def sync_device_spec(self, spec: DeviceSpec) -> None:
        self.fit_range.blockSignals(True)
        self.fit_range.clear()
        for key, (max_fc, bands) in AUTOEQ_FIT_RANGES:
            clamped_bands = min(bands, spec.dsp.band_count)
            self.fit_range.addItem(tr(key), (max_fc, clamped_bands))
        self.fit_range.blockSignals(False)
        self.result = None
        self.result_entry = None
        self.result_range = None
        self.result_options = None
        self.fit_status.clear()
        self.update_actions()

    def apply_tooltips(self) -> None:
        self.update_source_labels()
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
        self.guide_author_btn.setToolTip(tr("footer.author_tooltip"))
        self.guide_coffee_btn.setToolTip(tr("footer.coffee_tooltip"))
        self.report_button.setToolTip(tr("footer.report_tooltip"))
        self.guide_version_label.setToolTip(tr("tooltip.app_version", version=APP_VERSION))

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        paint_innovibe_backdrop(self)

    def _toggle_auto_update_check(self, enabled: bool) -> None:
        save_auto_update_check(self.settings_path, enabled)

    def open_update_release(self) -> None:
        if self.latest_release_url:
            self.open_external_url(self.latest_release_url)

    def copy_flatpak_update_command(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText("flatpak update pl.innovibe.DspControl")
        self.feedback.setText(tr("updates.flatpak_cmd_copied"))

    def check_for_updates(self, *, manual: bool = True) -> None:
        if self.update_job is not None:
            return
        self.check_update_btn.setEnabled(False)
        if manual:
            self.update_status_label.set_title(tr("updates.checking"), wrap=False)
        job = Job(check_latest_release)
        self.update_job = job
        job.signals.finished.connect(lambda result, error: self._on_update_checked(result, error, manual=manual))
        QThreadPool.globalInstance().start(job)

    def _on_update_checked(self, result, error: str, *, manual: bool) -> None:
        self.update_job = None
        self.check_update_btn.setEnabled(True)
        if error:
            if manual:
                self.update_status_label.set_title(tr("updates.error", error=error), wrap=False)
            return
        latest_version = result
        if latest_version and is_newer_version(latest_version, APP_VERSION):
            self.latest_release_url = (
                f"https://github.com/tom3k5/moondrop-position-dac/releases/tag/v{latest_version.lstrip('vV')}"
            )
            self.update_banner_label.setText(tr("updates.available_banner", version=latest_version))
            self.update_banner.setVisible(True)
            self.update_status_label.set_title(tr("updates.available_banner", version=latest_version), wrap=False)
        elif manual:
            self.update_status_label.set_title(tr("updates.up_to_date", version=APP_VERSION), wrap=False)

    def diagnostic_summary(self) -> str:
        lines = [
            f"App: {tr('app.title')} {APP_VERSION}",
            f"OS: {platform.platform()}",
            f"Python: {platform.python_version()}",
            f"Mode: {'demo' if self.demo else 'hardware'}",
            f"Connection: {self.connection.full_title}",
        ]
        if self.state is not None:
            slot_label = dac.SLOT_NAMES.get(self.state.slot, str(self.state.slot))
            lines.extend(
                [
                    f"Model: {self.state.model_name}",
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

    def open_github_issue(self, template: str, **fields: str) -> None:
        params = {
            "template": template,
            "os": platform.platform(),
        }
        if template == "bug_report.yml":
            params["diagnostics"] = self.diagnostic_summary()
        params.update(fields)
        url = f"{GITHUB_REPO_URL}/issues/new?{urlencode(params, quote_via=quote)}"
        self.open_external_url(url)

    def retranslate_ui(self) -> None:
        self.setWindowTitle(tr("app.title"))
        self.heading.setText(tr("app.title"))
        self.guide_version_label.setToolTip(tr("tooltip.app_version", version=APP_VERSION))
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
        self.guide_updates_box.setTitle(tr("updates.group"))
        self.auto_update_check.setText(tr("updates.auto_check"))
        self.check_update_btn.setText(tr("updates.check_now"))
        self.update_open_btn.setText(tr("updates.open_release"))
        self.update_copy_cmd_btn.setText(tr("updates.copy_flatpak_cmd"))
        self.update_dismiss_btn.setText(tr("updates.dismiss"))
        self.guide_support_box.setTitle(tr("help.support_group"))
        self.guide_support_text.setText(tr("help.support_body"))
        self.guide_hub_btn.setText(tr("help.open_hub"))
        self.guide_author_btn.setText(tr("help.author_link"))
        self.guide_coffee_btn.setText(tr("help.coffee_link"))
        self.guide_version_label.setText(tr("help.version", version=APP_VERSION))
        self.device_box.setTitle(tr("device.read_settings"))
        self.device_select_label.setText(tr("device.selected_model"))
        self.device_select.setAccessibleName(self.device_select_label.text())
        self.update_device_choices(self.device_choices, force=True)
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
        self.sample_rate_combo.setAccessibleName(tr("device.force_rate"))
        self.sample_rate_combo.setItemText(0, tr("device.rate_auto"))
        self.apply_rate_button.setText(tr("device.apply"))
        self.refresh_rate_button.setText(tr("device.refresh"))
        self.pipewire_scope.setText(tr("device.pipewire_scope"))
        self.usb_details.setText(tr("device.usb_details"))
        self.raw_stream_label.setText(tr("device.usb_format"))
        modes_text = " · ".join(
            f"Alt {alt} · {fmt} ({tr('device.bit_depth', bits=bits)})" for alt, fmt, bits in UAC2_PLAYBACK_MODES
        )
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
        self.update_device_actions_layout()
        self.update_accent_texts()
        self.profile_search.setPlaceholderText(tr("search.profiles_placeholder"))
        self.profile_search.setAccessibleName(tr("search.profiles_a11y"))
        self.profiles.setAccessibleName(tr("tuning.library"))
        self.builtin_heading.setText(tr("tuning.builtin"))
        if self.factory_item is not None and self.active_spec.has_factory_slot:
            self.factory_item.setData(
                PROFILE_ROLE,
                Profile(
                    tr("tuning.factory"),
                    self.active_spec.dsp.slots.factory,
                    [],
                    None,
                    sample_rate_hz=self.active_spec.dsp.sample_rate_hz,
                    model_id=self.active_spec.model_id,
                ),
            )
            self.factory_item.setToolTip(tr("tuning.factory"))
        if self.user_heading is not None:
            self.user_heading.setText(tr("source.my_profiles"))
        self.fr_title_label.setText(tr("plot.fr_title"))
        self.headphone_label.setText(tr("headphone.label"))
        self.headphone_combo.setAccessibleName(tr("headphone.label"))
        self.headphone_choose_btn.setText(tr("headphone.change"))
        self.headphone_flat_btn.setText(tr("headphone.flat_chip"))
        self.headphone_flat_btn.setToolTip(tr("headphone.use_flat"))
        self.refresh_headphone_ui()
        self.correction_title.setText(tr("plot.eq_title"))
        self.preview_plot.setAccessibleName(tr("plot.fr_title"))
        self.correction_plot.setAccessibleName(tr("plot.eq_title"))
        self.plot_view_group.button(0).setText(tr("plot.view_response"))
        self.plot_view_group.button(1).setText(tr("plot.view_eq"))
        self.fit_detail_button.setText(tr("plot.fit_more"))
        self.fit_detail_button.setAccessibleName(tr("plot.fit_disclosure"))
        self.correction_key.set_labels((tr("plot.key.profile_eq"), tr("plot.key.current_dsp")))
        self.add_button.setText(tr("actions.add_profile"))
        self.new_profile_action.setText(tr("actions.new_empty"))
        self.import_profile_action.setText(tr("actions.import_profile"))
        self.import_bundle_action.setText(tr("actions.import_bundle"))
        self.export_bundle_action.setText(tr("actions.export_bundle"))
        self.compare_label.setText(tr("compare.label"))
        self.compare_combo.setAccessibleName(tr("compare.label"))
        self.compare_combo.setItemText(0, tr("compare.dsp_default"))
        self.compare_clear_btn.setToolTip(tr("compare.clear_tooltip"))
        self.save_setup_action.setText(tr("actions.save_setup"))
        self.import_profile_action.setText(tr("actions.import_profile"))
        self.more_button.setText(tr("actions.more"))
        self.duplicate_action.setText(tr("actions.duplicate"))
        self.export_action.setText(tr("actions.export_selected"))
        self.delete_action.setText(tr("actions.delete_profile"))
        self.edit_button.setText(tr("actions.edit_eq"))
        self.autoeq_panel.retranslate_ui()
        self.size_preview_actions()
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
        icon_file = Path(__file__).resolve().parents[1] / "flatpak/pl.innovibe.DspControl.svg"
        fallback = QIcon(str(icon_file))
        if fallback.isNull():
            fallback = self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume)
        self.tray = QSystemTrayIcon(QIcon.fromTheme("pl.innovibe.DspControl", fallback), self)
        self.tray_menu = QMenu(self)
        self.tray_menu.aboutToShow.connect(self.populate_tray)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(self.tray_activated)
        self.tray.setToolTip(tr("app.title"))
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
        status = tr("tuning.active_profile", name=self.active_profile.text()) if self.state else self.connection.text()
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
            matches = self.state is not None and profile.matches(self.state)
            action.setCheckable(True)
            action.setChecked(matches and profile.name == self.active_profile.text())
            action.setEnabled(self.state is not None and not matches)
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
            self.user_heading = self.add_library_heading(tr("source.my_profiles"))
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

    def _sync_headphone_from_profile(self, profile: Profile) -> None:
        if not self.active_spec.allows_headphone_selection:
            return
        target_sel: HeadphoneSelection | None = None
        if profile.headphone_selection:
            target_sel = HeadphoneSelection.from_dict(profile.headphone_selection, default_mode="flat")
        elif profile.headphone_name:
            for item in self.recent_headphones:
                if item.display_label(tr) == profile.headphone_name or item.entry_name == profile.headphone_name:
                    target_sel = item
                    break
        if target_sel is not None and target_sel != self.headphone_selection:
            self.set_headphone_selection(target_sel)

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
        panel = self.autoeq_panel
        profile = self.candidate_profile()
        if using_catalog or profile is None:
            self._last_synced_profile_key = None
        elif not getattr(self, "_syncing_headphone", False):
            profile_key = (
                profile.name,
                profile.model_id,
                tuple(profile.headphone_selection.items()) if profile.headphone_selection else None,
                profile.headphone_name,
            )
            if profile_key != getattr(self, "_last_synced_profile_key", None):
                self._last_synced_profile_key = profile_key
                self._syncing_headphone = True
                try:
                    self._sync_headphone_from_profile(profile)
                finally:
                    self._syncing_headphone = False
            if getattr(self, "_ui_ready", False) and not getattr(self, "_restoring_last_profile", False):
                save_last_profile_for_model(self.settings_path, self.active_spec.model_id, profile.name)
        shown = panel.result if using_catalog else profile
        self.apply_error = ""
        self.apply_notice = ""
        self.library_actions.setVisible(not using_catalog)
        self.catalog_actions.setVisible(using_catalog)
        self.fit_controls.setVisible(using_catalog)
        panel.generate.setVisible(using_catalog and not panel.fit_active and profile is None)
        panel.cancel.setVisible(using_catalog and panel.fit_active)
        panel.fit_status.setVisible(using_catalog and bool(panel.fit_status.text()))
        self.edit_button.setVisible(profile is not None)
        self.save_fit_button.setVisible(using_catalog and profile is not None)
        if shown is not None:
            self.preview_title.set_title(tr("tuning.selected_profile", name=shown.name), wrap=False)
            context = (
                tr("plot.profile_bands", count=len(shown.bands))
                if shown.slot == self.active_spec.dsp.slots.custom
                else tr("tuning.factory_slot")
            )
            range_note = ""
            if not using_catalog and shown.fit_range is not None:
                range_note = panel.fit_range.itemText(panel.fit_range.findData(shown.fit_range))
            context = " · ".join(filter(None, (context, shown.headphone_name, shown.source, range_note)))
            self.profile_info.set_title(context, wrap=False)
        elif using_catalog:
            entry = panel.current_entry()
            self.preview_title.set_title(entry.name if entry else tr("autoeq.select_target"), wrap=False)
            self.profile_info.set_title(entry.source if entry else "", wrap=False)
        else:
            self.preview_title.set_title(tr("tuning.no_profiles"), wrap=False)
            self.profile_info.set_title("", wrap=False)
        provenance = ""
        shown_range = (panel.result_range if using_catalog else shown.fit_range) if shown is not None else None
        if using_catalog and shown_range is not None:
            fit_range = panel.fit_range.itemText(panel.fit_range.findData(shown_range))
            provenance = tr("autoeq.computed_range", range=fit_range)
            if profile is None:
                provenance += " · " + tr("autoeq.stale_result")
        self.fit_provenance.setText(provenance)
        self.preview_actions.invalidate()
        self.update_comparison()
        self.refresh_buttons()

    def update_comparison(self) -> None:
        selected = self.autoeq_panel.result if self.catalog_selected() else self.selected_profile()
        waiting_for_fit = self.catalog_selected() and selected is None
        preview_entry = self.autoeq_panel.preview_entry if waiting_for_fit else None
        preview_curve = self.autoeq_panel.preview_curve if waiting_for_fit else []
        reference = self.compare_profile if self.compare_profile is not None else self.readback_profile
        sources = (
            selected,
            reference,
            self.factory_profile,
            waiting_for_fit,
            preview_entry,
            preview_curve,
        )
        if sources == self.preview_sources:
            return
        self.preview_sources = sources

        self.preview_plot.set_factory(
            self.factory_profile if self.active_spec.acoustics.measurement_includes_factory_eq else None
        )
        self.preview_plot.set_profile(selected)
        self.preview_plot.set_reference(reference)
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
        target_detail = tr("plot.key.target", name=target_label) if target_points else ""
        ref_short = (
            tr("plot.key.compare_short", name=self.compare_profile.name)
            if self.compare_profile is not None
            else tr("plot.key.current_dsp")
        )
        ref_detail = (
            tr("plot.key.compare_detail", name=self.compare_profile.name) if self.compare_profile is not None else ""
        )
        self.preview_key.set_labels(
            (
                tr("plot.key.selected"),
                ref_short,
                tr("plot.key.measured"),
                tr("plot.key.target_short"),
            ),
            {1: ref_detail, 3: target_detail},
        )
        self.correction_key.set_labels((tr("plot.key.profile_eq"), ref_short), {1: ref_detail})
        self.preview_plot.set_target_points(target_points)
        summary = tr("plot.fit_not_available")
        if selected is not None and not raw_target:
            summary = tr("plot.no_target")
        self.fit_details_text = ""
        if fit and predicted:
            low = f"{fit.low_hz:g} Hz" if fit.low_hz < 1000 else f"{fit.low_hz / 1000:g} kHz"
            high = f"{fit.high_hz:g} Hz" if fit.high_hz < 1000 else f"{fit.high_hz / 1000:g} kHz"
            summary = tr("plot.fit_summary", rms=fit.rms_db, low=low, high=high)
            fit_details = tr("plot.fit_details", offset=fit.offset_db, peak=fit.peak_db, freq=fit.peak_hz)
            self.fit_details_text = f"{target_detail}\n\n{fit_details}"
        self.fit_summary.set_title(summary, wrap=False, detail=self.fit_details_text)
        self.fit_detail_button.setEnabled(bool(self.fit_details_text))

        electrical = (
            self.factory_profile
            if (selected and self.active_spec.has_factory_slot and selected.slot == self.active_spec.dsp.slots.factory)
            else selected
        )
        self.correction_plot.set_primary_points(response_points(electrical, EQ_PLOT_FREQUENCIES) if electrical else [])
        self.correction_plot.set_reference_points(response_points(reference, EQ_PLOT_FREQUENCIES) if reference else [])
        preamp_parts = []
        if selected is not None and selected.preamp is not None:
            preamp_parts.append(tr("plot.preamp_profile", value=selected.preamp))
        elif selected is not None:
            preamp_parts.append(tr("plot.preamp_unspecified"))
        if self.readback_profile is not None:
            preamp_parts.append(tr("plot.preamp_dsp", value=self.readback_profile.preamp))
        self.preamp_summary.setText(" · ".join(preamp_parts))

        notes = []
        if (
            self.active_spec.acoustics.measurement_includes_factory_eq
            and self.factory_profile is None
            and selected is not None
            and selected.slot != self.active_spec.dsp.slots.factory
        ):
            notes.append(tr("plot.neutral_factory"))
        if measured:
            notes.append(tr("plot.measurement_note") + " · " + tr("plot.treble_note"))
        elif self.active_spec.is_dongle:
            notes.append(tr("plot.dongle_no_curve", model=self.active_spec.display_name))
        self.plot_legend.setText("\n".join(notes))
        plot_description = [*self.preview_key.labels[:3], target_detail, summary, *notes]
        self.preview_plot.setAccessibleDescription("\n".join(filter(None, plot_description)))

    def set_connection_status(self, key: str, model: str = "") -> None:
        status = tr(key)
        if model:
            status = f"{status} · {model}"
        self.connection.setMaximumWidth(self.connection.fontMetrics().horizontalAdvance(status) + 24)
        self.connection.set_title(status, wrap=False, detail=tr("tooltip.connection"))

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
            active_name = active.data(PROFILE_ROLE).name if active else tr("tuning.custom_settings")
        for item in items:
            name = item.data(PROFILE_ROLE).name
            label = tr("tuning.active_item", name=name) if item is active else name
            if item.text() != label:
                item.setText(label)
        self.connection_problem.setText(error if state is None else "")
        if state is None:
            if error:
                self.set_connection_status("status.connection_error")
            elif len(self.device_choices) > 1 or (self.device_choices and self.selected_target is not None):
                self.set_connection_status("status.choose_device")
            else:
                self.set_connection_status("tuning.dac_offline")
            if self.tray:
                self.tray.setToolTip(f"{tr('app.title')} · {self.connection.full_title}")
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
        self.set_connection_status("status.demo" if self.demo else "status.connected", state.model_name)
        slot_name = {0: tr("tuning.factory"), dac.CUSTOM_SLOT: tr("tuning.custom")}.get(state.slot)
        self.active_slot.setText(f"{state.slot} · {slot_name}" if slot_name else str(state.slot))
        self.active_profile.setText(active_name)
        if self.tray:
            self.tray.setToolTip(f"{state.model_name} · {self.active_profile.text()}")
        self.preamp.setText(f"{state.preamp:+.2f} dB")
        self.global_gain.setText("—" if state.global_gain_db is None else f"{state.global_gain_db} dB")
        self.mic_gain.setText("—" if state.mic_gain_raw is None else mic_gain_label(state.mic_gain_raw))
        self.firmware.setText(state.firmware)

    def can_restore_previous(self) -> bool:
        return (
            self.previous_dac_profile is not None
            and self.state is not None
            and not self.previous_dac_profile.matches(self.state)
        )

    def refresh_buttons(self) -> None:
        self.device_select.setEnabled(bool(self.device_choices) and not self.command_active and not self.editor_active)
        profile = self.candidate_profile()
        active = profile is not None and self.state is not None and profile.matches(self.state)
        restore_ready = active and self.can_restore_previous()
        self.active_summary.set_title(
            tr("tuning.active_profile", name=self.active_profile.text()) if self.state else tr("tuning.dac_offline"),
            wrap=False,
        )
        self.apply_button.setEnabled(
            not self.command_active and self.state is not None and profile is not None and (not active or restore_ready)
        )
        if restore_ready:
            self.apply_button.setText(tr("actions.restore_previous"))
            self.apply_button.setStyleSheet(SECONDARY_ACCENT_STYLE)
            self.apply_button.setToolTip(tr("tooltip.restore_previous"))
        else:
            self.apply_button.setText(tr("tuning.already_active" if active else "actions.apply_dac"))
            self.apply_button.setStyleSheet(PRIMARY_ACTION_STYLE)
            self.apply_button.setToolTip(tr("tooltip.apply_dac"))
        self.apply_button.setVisible(profile is not None)
        self.preview_actions.invalidate()
        message = self.apply_error or self.apply_notice
        detail = ""
        compact = ""
        if self.applying_profile is not None:
            message = tr("tuning.applying")
        elif not message and profile is not None and self.state is None:
            message = tr("tuning.connect_to_apply")
        elif (
            not message
            and active
            and profile == self.last_applied_profile
            and profile.preamp is not None
            and not dac.preamp_matches(self.state.preamp, profile.preamp)
        ):
            message = tr("tuning.applied_preamp_short", actual=self.state.preamp, requested=profile.preamp)
            detail = tr("tuning.applied_preamp", actual=self.state.preamp, requested=profile.preamp)
            compact = tr("tuning.applied_preamp_compact", actual=self.state.preamp)
        self.apply_status.set_title(message, wrap=False, detail=detail, compact=compact)
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

    def update_device_choices(self, choices: list[DeviceChoice], *, force: bool = False) -> None:
        if not force and self.device_select.count() and self.device_choices == choices:
            return
        self.device_choices = choices
        active = self.selected_target
        if active is None and len(choices) == 1:
            active = choices[0].target
        counts = Counter(choice.name for choice in choices)
        with QSignalBlocker(self.device_select):
            self.device_select.clear()
            self.device_select.addItem(tr("device.choose_model"))
            selected = 0
            for index, choice in enumerate(choices, 1):
                name = choice.name
                if counts[name] > 1:
                    node = choice.target.node if isinstance(choice.target, HidInterface) else choice.target
                    name = f"{name} · {node}"
                self.device_select.addItem(name, choice.target)
                self.device_select.setItemData(index, name, Qt.ItemDataRole.ToolTipRole)
                if active == choice.target:
                    selected = index
            self.device_select.setCurrentIndex(selected)
            self.device_select.setToolTip(self.device_select.currentText())

    def change_device(self) -> None:
        self.selected_target = self.device_select.currentData()
        self.update_device_choices(self.device_choices, force=True)
        self.refresh_done(None, "")
        self.refresh()

    def refresh(self) -> None:
        target = self.selected_target

        def finished(result, error: str) -> None:
            if self.selected_target != target:
                self.refresh()
                return
            if result is None:
                self.refresh_done(None, error)
                return
            choices, state, device_error = result
            self.update_device_choices(choices)
            self.refresh_done(state, device_error)

        self.start(lambda: poll_devices(self.list_devices, self.open_device, target), finished, background=True)

    def refresh_done(self, state, error: str) -> None:
        if state is not None and state.model_id != self.active_spec.model_id:
            self.apply_device_spec(get_device_spec(state.model_id))
        if (
            self.state is None
            or state is None
            or (self.state.target, self.state.firmware, self.state.model_id)
            != (state.target, state.firmware, state.model_id)
        ):
            self.factory_profile = self._default_factory_profile(self.active_spec)
            self.last_applied_profile = None
            self.previous_dac_profile = None
        self.state = state
        self.readback_profile = profile_from_readback(state) if state is not None else None
        if (
            self.readback_profile is not None
            and self.active_spec.has_factory_slot
            and state.slot == self.active_spec.dsp.slots.factory
        ):
            self.factory_profile = replace(self.readback_profile, preamp=0)
        self.update_comparison()
        self.render_state(error)
        self.refresh_buttons()
        self.refresh_playback_quality()

    def refresh_playback_quality(self) -> None:
        interface = self.state.interface if self.state is not None else None
        quality = read_playback_quality(interface=interface, demo=self.demo, demo_forced_rate=self.demo_forced_rate)
        if quality.altset is not None and quality.audio_format:
            status = tr("device.stream_running") if quality.running else tr("device.stream_ready")
            channels = ""
            if quality.channels is not None:
                channels = (
                    tr("device.stereo") if quality.channels == 2 else tr("device.channels", count=quality.channels)
                )
            rate = format_rate_khz(quality.rate_hz) if quality.rate_hz and (quality.running or self.demo) else ""
            bit_depth = next((bits for _, fmt, bits in UAC2_PLAYBACK_MODES if fmt == quality.audio_format), None)
            format_name = tr("device.bit_depth", bits=bit_depth) if bit_depth else quality.audio_format
            self.playback_format.setText(" · ".join(filter(None, (rate, format_name, channels, status))))
            self.playback_raw.setText(f"Alt {quality.altset} · {quality.audio_format}")
        else:
            missing = tr("device.stream_missing") if not quality.pipewire_available else tr("device.stream_waiting")
            self.playback_format.setText(missing)
            self.playback_raw.setText("—")

        if quality.rate_hz:
            mode = tr("device.rate_forced" if quality.forced_rate_hz else "device.rate_auto")
            self.playback_rate.setText(f"{format_rate_khz(quality.rate_hz)} · {mode} · {quality.source}")
        else:
            self.playback_rate.setText("—")

        target_rate = quality.forced_rate_hz or 0
        if self.observed_forced_rate != target_rate:
            self.observed_forced_rate = target_rate
            index = self.sample_rate_combo.findData(target_rate)
            if index >= 0:
                self.sample_rate_combo.setCurrentIndex(index)
        self.apply_rate_button.setEnabled(quality.pipewire_available)

    def apply_playback_rate(self) -> None:
        rate_hz = self.sample_rate_combo.currentData()
        if rate_hz is None:
            return
        if self.demo:
            self.demo_forced_rate = int(rate_hz)
            self.refresh_playback_quality()
            label = tr("device.rate_auto") if rate_hz == 0 else format_rate_khz(rate_hz)
            self.feedback.setText(tr("device.rate_simulated", rate=label))
            return
        try:
            confirmed = apply_pipewire_sample_rate(int(rate_hz))
        except (ValueError, RuntimeError) as exc:
            self.feedback.setText(tr("device.rate_failed", error=exc))
            return
        self.refresh_playback_quality()
        label = tr("device.rate_auto") if confirmed == 0 else format_rate_khz(confirmed)
        self.feedback.setText(tr("device.rate_changed", rate=label))

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
            url.isLocalFile() and Path(url.toLocalFile()).suffix.casefold() in (".json", ".txt", ".csv", ".zip")
            for url in urls
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
            if suffix == ".zip":
                self.import_library_bundle(path)
                event.acceptProposedAction()
                return
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

    def build_current_setup_profile(self, name: str) -> Profile:
        spec = self.active_spec
        source_profile = self.selected_profile()
        if self.readback_profile is not None and len(self.readback_profile.bands) == spec.dsp.band_count:
            bands = [dict(b) for b in self.readback_profile.bands]
            preamp = float(self.readback_profile.preamp or 0.0)
        elif source_profile is not None and len(source_profile.bands) == spec.dsp.band_count:
            bands = [dict(b) for b in source_profile.bands]
            preamp = float(source_profile.preamp or 0.0)
        else:
            bands = default_custom_bands(spec)
            preamp = 0.0
        min_pre, max_pre = spec.dsp.preamp_range_db
        preamp = max(min_pre, min(max_pre, preamp))
        global_gain = self.state.global_gain_db if self.state is not None else None
        mic_gain = (
            self.state.mic_gain_raw if self.state is not None and self.state.mic_gain_raw in MIC_GAIN_REQUESTS else None
        )
        hp_name = self.active_headphone_name() or tr("headphone.flat_short")
        dac_short = spec.display_name.removeprefix("MOONDROP:Gravity ").removeprefix("MOONDROP ")
        profile = custom_profile(
            name,
            spec.dsp.slots.custom,
            bands,
            preamp,
            global_gain,
            mic_gain,
            spec=spec,
        )
        return replace(
            profile,
            headphone_name=hp_name,
            headphone_selection=self.headphone_selection.to_dict(),
            source=tr("headphone.setup_source", model=dac_short, headphone=hp_name),
        )

    def save_current_setup(self) -> None:
        spec = self.active_spec
        dac_short = spec.display_name.removeprefix("MOONDROP:Gravity ").removeprefix("MOONDROP ")
        hp_label = self.active_headphone_name() or tr("headphone.flat_short")
        suggested = f"{dac_short} × {hp_label}"
        name, accepted = QInputDialog.getText(
            self,
            tr("actions.save_setup_title"),
            tr("actions.save_setup_prompt"),
            text=suggested,
        )
        if not accepted or not name.strip():
            return
        try:
            profile = self.build_current_setup_profile(name.strip())
        except (ValueError, dac.HidError) as exc:
            self.feedback.setText(str(exc))
            return
        if self.persist_profile(profile):
            self.switch_source(0)
            self.feedback.setText(tr("actions.saved_library"))

    def save_fit(self) -> None:
        profile = self.autoeq_panel.ready_result()
        if self.save_fit_button.isEnabled() and profile is not None and self.persist_profile(profile):
            self.feedback.setText(tr("actions.saved_library"))

    def _refresh_compare_combo(self) -> None:
        if not hasattr(self, "compare_combo"):
            return
        current_name = self.compare_profile.name if self.compare_profile is not None else None
        self.compare_combo.blockSignals(True)
        try:
            self.compare_combo.clear()
            self.compare_combo.addItem(tr("compare.dsp_default"), None)
            restored_idx = 0
            for item in self.profile_items():
                prof = item.data(PROFILE_ROLE)
                if prof is None or not self.profile_matches_active_model(prof):
                    continue
                self.compare_combo.addItem(prof.name, prof)
                if current_name is not None and prof.name == current_name:
                    restored_idx = self.compare_combo.count() - 1
            self.compare_combo.setCurrentIndex(restored_idx)
            if restored_idx == 0:
                self.compare_profile = None
                self.compare_clear_btn.setEnabled(False)
        finally:
            self.compare_combo.blockSignals(False)

    def _on_compare_combo_changed(self, index: int) -> None:
        prof = self.compare_combo.itemData(index) if index >= 0 else None
        self.compare_profile = prof if isinstance(prof, Profile) else None
        self.compare_clear_btn.setEnabled(self.compare_profile is not None)
        self.update_comparison()

    def set_compare_profile(self, profile: Profile | None) -> None:
        if profile is None:
            self.clear_compare_profile()
            return
        self._refresh_compare_combo()
        for idx in range(1, self.compare_combo.count()):
            p = self.compare_combo.itemData(idx)
            if isinstance(p, Profile) and p.name == profile.name:
                self.compare_combo.setCurrentIndex(idx)
                return
        self.compare_combo.addItem(profile.name, profile)
        self.compare_combo.setCurrentIndex(self.compare_combo.count() - 1)

    def clear_compare_profile(self) -> None:
        self.compare_profile = None
        self.compare_combo.setCurrentIndex(0)
        self.compare_clear_btn.setEnabled(False)
        self.update_comparison()

    def _show_profile_context_menu(self, pos) -> None:
        item = self.profiles.itemAt(pos)
        prof = item.data(PROFILE_ROLE) if item is not None else None
        if prof is None:
            return
        menu = QMenu(self)
        menu.addAction(tr("compare.set_as_b"), lambda: self.set_compare_profile(prof))
        menu.exec(self.profiles.viewport().mapToGlobal(pos))

    def export_library_bundle(self, dest_zip: Path | None = None) -> bool:
        if dest_zip is None:
            chosen, _ = QFileDialog.getSaveFileName(
                self,
                tr("actions.export_bundle_title"),
                str(Path.home() / "dsp-control-profiles.zip"),
                "ZIP (*.zip)",
            )
            if not chosen:
                return False
            dest_zip = Path(chosen)
            if dest_zip.suffix.casefold() != ".zip":
                dest_zip = dest_zip.with_suffix(".zip")
        try:
            count = export_library_zip(self.library_directory, dest_zip)
        except OSError as exc:
            self.feedback.setText(tr("actions.export_bundle_error", error=exc))
            return False
        self.feedback.setText(tr("actions.export_bundle_done", count=count))
        return True

    def import_library_bundle(self, src_zip: Path | None = None, *, conflict: str | None = None) -> bool:
        if src_zip is None:
            chosen, _ = QFileDialog.getOpenFileName(
                self,
                tr("actions.import_bundle_title"),
                str(Path.home()),
                "ZIP (*.zip)",
            )
            if not chosen:
                return False
            src_zip = Path(chosen)
        if conflict is None:
            box = QMessageBox(self)
            box.setWindowTitle(tr("actions.import_bundle_title"))
            box.setText(tr("actions.import_bundle_conflict"))
            copy_btn = box.addButton(tr("actions.conflict_copy"), QMessageBox.ButtonRole.AcceptRole)
            skip_btn = box.addButton(tr("actions.conflict_skip"), QMessageBox.ButtonRole.ActionRole)
            overwrite_btn = box.addButton(tr("actions.conflict_overwrite"), QMessageBox.ButtonRole.DestructiveRole)
            cancel_btn = box.addButton(tr("editor.cancel"), QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(copy_btn)
            box.exec()
            clicked = box.clickedButton()
            if clicked is cancel_btn:
                return False
            conflict = "overwrite" if clicked is overwrite_btn else ("skip" if clicked is skip_btn else "copy")
        try:
            imported, skipped = import_library_zip(src_zip, self.library_directory, conflict=conflict)
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            self.feedback.setText(tr("actions.import_bundle_error", error=exc))
            return False
        self.load_library()
        self.filter_profiles(self.profile_search.text())
        self._refresh_compare_combo()
        self.feedback.setText(tr("actions.import_bundle_done", imported=imported, skipped=skipped))
        return True

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
        box.setWindowTitle(tr("actions.delete_title"))
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(tr("actions.delete_confirm", name=profile.name))
        remove = box.addButton(tr("actions.delete_title"), QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton(tr("editor.cancel"), QMessageBox.ButtonRole.RejectRole)
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
            self.feedback.setText(tr("actions.delete_failed", error=exc))
            return
        active = self.state is not None and profile.matches(self.state)
        self.profiles.takeItem(self.profiles.row(item))
        if self.user_heading is not None and not any(entry.data(PATH_ROLE) for entry in self.profile_items()):
            self.profiles.takeItem(self.profiles.row(self.user_heading))
            self.user_heading = None
        self.render_state()
        self.update_selection()
        self.feedback.setText(tr("actions.deleted_active" if active else "actions.deleted"))

    def edit_profile(self, *, duplicate: bool = False, new: bool = False) -> None:
        if self.command_active or self.editor_active:
            return
        selected = None if new else self.candidate_profile()
        item = None if new or self.catalog_selected() else self.profiles.currentItem()
        source = selected if selected is not None and selected.slot == dac.CUSTOM_SLOT else None
        if source is not None and (duplicate or (item is not None and not item.data(PATH_ROLE))):
            source = replace(source, name=tr("actions.profile_copy", name=source.name))
        current = None
        state = self.state
        if state is not None and state.slot == self.active_spec.dsp.slots.custom and all(state.bands):
            with contextlib.suppress(dac.HidError, ValueError):
                current = custom_profile(
                    "Aktualny Custom",
                    state.slot,
                    state.bands,
                    state.preamp,
                    state.global_gain_db,
                    state.mic_gain_raw if state.mic_gain_raw in MIC_GAIN_REQUESTS else None,
                    spec=self.active_spec,
                )
        editor = EqualizerDialog(
            self,
            source,
            current,
            self.factory_profile,
            device_path=state.target if state is not None else None,
            device_spec=self.active_spec,
            measurement_curve=self.active_measurement_curve(),
            compare_profile=self.compare_profile,
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
                self.feedback.setText(tr("actions.saved_library"))
        editor.deleteLater()
        self.refresh()

    def apply_selected(self) -> None:
        profile = self.candidate_profile()
        active = profile is not None and self.state is not None and profile.matches(self.state)
        if active and self.can_restore_previous():
            self.apply_candidate(self.previous_dac_profile, restoring=True)
            return
        self.apply_candidate(profile)

    def apply_candidate(self, profile: Profile | None, *, restoring: bool = False) -> None:
        if self.state is None or self.command_active or self.editor_active or profile is None:
            return
        device = self.state.target
        self.applying_profile = profile
        self.applying_restore = restoring
        self.apply_error = ""
        self.apply_notice = ""
        self.feedback.clear()
        self.start(lambda: apply_profile_with_previous(self.open_device, device, profile), self.apply_done)

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
            self.start(lambda: update_global_gain(self.open_device, state.target, target), self.global_gain_done)

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
            self.start(lambda: update_mic_gain(self.open_device, state.target, target), self.mic_gain_done)

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
        device = self.state.target
        self.feedback.setText(tr("device.backup_reading"))
        self.start(lambda: read_custom_backup(self.open_device, device), self.backup_done)

    def backup_done(self, profile: Profile | None, error: str) -> None:
        self.refresh_buttons()
        if profile is None:
            self.feedback.setText(tr("device.backup_failed", error=error))
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
            self.feedback.setText(tr("device.backup_failed", error=exc))
            return
        self.feedback.setText(tr("device.backup_saved"))

    def apply_done(self, result, error: str) -> None:
        profile = self.applying_profile
        restoring = self.applying_restore
        self.applying_profile = None
        self.applying_restore = False
        previous, state = result if isinstance(result, tuple) else (None, result)
        self.apply_error = tr("tuning.apply_error", error=error) if error else ""
        if not error and state is not None:
            self.last_applied_profile = profile
            if restoring:
                self.previous_dac_profile = None
                self.apply_notice = tr("tuning.restored_previous")
            elif previous is not None and not previous.matches(state):
                self.previous_dac_profile = previous
            self.refresh_done(state, "")
        else:
            self.render_state(error)
            self.refresh_buttons()
        if error and self.tabs.currentWidget() is not self.profile_page:
            self.feedback.setText(self.apply_error)

    def confirm_defaults(self) -> None:
        if self.editor_active or not self.defaults_button.isEnabled():
            return
        device = self.state.target
        self.open_window()
        box = QMessageBox(self)
        box.setWindowTitle(tr("device.factory_reset"))
        box.setText(tr("device.reset_question"))
        box.setInformativeText(tr("device.reset_mic" if self.state.mic_gain_raw is not None else "device.reset_scope"))
        restore = box.addButton(tr("device.restore"), QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton(tr("editor.cancel"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.setEscapeButton(cancel)
        box.exec()
        if box.clickedButton() is restore:
            self.feedback.setText(tr("device.resetting"))
            self.start(lambda: restore_defaults(self.open_device, device), self.defaults_done)

    def defaults_done(self, state, error: str) -> None:
        self.refresh_done(state, error)
        if error:
            self.feedback.setText(tr("device.reset_failed", error=error))
            return
        if self.factory_item is not None:
            self.last_applied_profile = self.factory_item.data(PROFILE_ROLE)
        self.previous_dac_profile = None
        self.profile_search.clear()
        if self.factory_item is not None:
            self.profiles.setCurrentItem(self.factory_item)
        self.autoeq_panel.reset_preview()
        self.switch_source(0)
        self.feedback.setText(tr("device.reset_done"))

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
                    "DSP Control",
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
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL_ID,
        help="identyfikator modelu dla --demo (np. moondrop-position, moondrop-chu2-dsp, moondrop-echo-a)",
    )
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
    if args.diagnose:
        print(json.dumps(build_diagnostic_report(), indent=2, ensure_ascii=False))
        return 0
    if args.diagnose_controls or args.test_global_gain or args.test_mic_gain:
        try:
            dev = open_dac()
            if dev is None:
                raise dac.HidError("Nie znaleziono obsługiwanego DAC-a w sysfs.")
            with dev:
                if args.test_global_gain:
                    report = test_global_gain(dev)
                elif args.test_mic_gain:
                    report = test_mic_gain(dev)
                else:
                    report = diagnose_controls(dev)
        except dac.HidError as exc:
            print(exc, file=sys.stderr)
            return 1
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    app = QApplication([sys.argv[0]])
    app.setApplicationName(APP_STORAGE_NAME)
    app.setApplicationDisplayName(tr("app.title"))
    app.setApplicationVersion(APP_VERSION)
    server_name = f"dsp-control-{'demo' if args.demo else 'live'}"
    if activate_existing_instance(server_name):
        return 0
    app.setQuitOnLastWindowClosed(not QSystemTrayIcon.isSystemTrayAvailable())
    desktop_id = "pl.innovibe.DspControl"
    if QStandardPaths.locate(QStandardPaths.StandardLocation.GenericDataLocation, f"applications/{desktop_id}.desktop"):
        app.setDesktopFileName(desktop_id)
    window = ProfilesWindow(args.demo, demo_model_id=args.model)
    instance_server = start_instance_server(server_name, window.open_window)
    if instance_server is not None:
        app.aboutToQuit.connect(instance_server.close)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
