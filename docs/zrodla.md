# Źródła i licencje

## Protokół sterowania (HID 0x4B)

| Projekt | Licencja | Co wykorzystano |
|---|---|---|
| [jeromeof/devicePEQ](https://github.com/jeromeof/devicePEQ) | 0BSD | `devicePEQ/moondropUsbHidHandler.js` — pełny handler rodziny Moondrop (komendy, układ ramek, kolejność zapisu); `devicePEQ/walkplayHidHandler.js` + `testing/protocol-docs/walkplayHIDHandler.md` — opis rodziny Walkplay; `devicePEQ/usbDeviceConfig.js` — mapowanie PID→scheme (PID 0x0123 = scheme 13) |
| [EffectiveEquivalent/FreeDSP-Studio](https://github.com/EffectiveEquivalent/FreeDSP-Studio) | MIT | `tools/app/src/dsp2.rs`, `hid_gen2.rs` — niezależna implementacja „gen-2” (współczynniki, tempo, pułapki, kolejność commit) |
| [potatosalad775/eqcaps](https://github.com/potatosalad775/eqcaps) | kod MIT, dane CC0 | profil `data/profiles/moondrop/moondrop-position.json`, baza `data/bases/moondrop-hub.json` — limity z oficjalnej aplikacji Moondrop |
| [modernGraphTool — Hardware EQ](https://potatosalad775.github.io/modernGraphTool/docs/features/device-peq/) | — | dokumentacja użycia WebHID do EQ w urządzeniach (m.in. Moondrop) |
| [eqcaps — katalog urządzeń](https://potatosalad775.github.io/eqcaps/?kind=hardware) | — | publiczna baza profili urządzeń |
| [hub.mondroplab.com](https://hub.mondroplab.com/) | — | oficjalna aplikacja web „Custom EQ” (WebHID); wersja 1.8.0 build 26B1107, konfiguracja POSITION |

Kopie robocze najważniejszych plików referencyjnych leżą w `docs/ref/` (nazwy
zachowane; licencje jak wyżej).

## AutoEq / baza EQ (obliczenia i dane)

| Źródło | Licencja | Co wykorzystano |
|---|---|---|
| [jaakkopasanen/AutoEq](https://github.com/jaakkopasanen/AutoEq) | MIT (kod i targety) | biblioteka `autoeq` 4.1.2 (PyPI, Python 3.11 w `.venvs/autoeq`), API `FrequencyResponse` / `optimize_parametric_eq` / `PEQ_CONFIGS`; targety MIT w `dane/targety/` oraz wbudowany indeks nazw modeli i źródeł w `dane/autoeq-catalog.json` |
| [autoeq.app](https://autoeq.app) | — | webowy frontend + backend FastAPI (`webapp/main.py`, `POST /equalize`); eksport Equalizer APO — obsługiwany przez `moondrop_position.py import-eq` |
| [squig.link](https://squig.link) / REW | format wejściowy użytkownika | `skrypty/measurements.py` obsługuje lokalnie wskazane przez użytkownika pliki REW / `squig.link` `.txt` (nie są dołączone do repozytorium) |
| Specyfikacja MOONDROP Position | dane fabryczne producenta | `dane/pomiary/Moondrop Position (B&K 5128).csv` (opracowane na podstawie publicznej krzywej `POSITION (Original)`) |
| [docs/integracja-autoeq.md](integracja-autoeq.md) | — | opis pipeline'u i rekomendacja integracji (ten projekt) |

Uwaga: AutoEq ma własny config `MOONDROP_FREE_DSP` (9 pasm PK) dla starszego
modułu FreeDSP — dla Position zbudowany jest osobny config (8 pasm PK,
`fs = 96 kHz`) w `skrypty/eq_fit.py`, bo tyle pasm i taki zegar ma to
urządzenie.

## Sprzęt / produkt

| Źródło | Uwagi |
|---|---|
| [MOONDROP Position — Linsoul](https://www.linsoul.com/products/moondrop-position) | specyfikacja zestawu: IEM 10 mm Al-Mg, 18 Ω, 119 dB/Vrms, 15 Hz–38 kHz, adapter USB-C z DSP |
| [17173 — artykuł o premierze](https://news.17173.com/content/09182026/160610463.shtml) | 159 CNY, DSP/„AI 降噪”, 24-bit, <5 ms, strojenie HRTF, regulacja przez Web/App |
| [IEMRanking — Moondrop Position](https://www.iemranking.com/show/moondrop-position) | recenzje (m.in. Super* Review: „PEQ dongle, osiem pasm peaking, bez półek, działa z aplikacją web Moondrop”) |

## Warstwa systemowa (odczyt lokalny)

* `lsusb -v`, `/proc/asound/card0/{stream0,usbmixer,pcm*/info}`,
  `/sys/class/hidraw/*/device/report_descriptor`, `/run/udev/data/`,
  `/proc/bus/input/devices` (lokalny odczyt diagnostyczny podczas analizy sprzętu).
* Sterowniki jądra: `snd-usb-audio` (UAC2), `usbhid`/`hid-generic`, `hidraw`.

## Zależności uruchomieniowe i narzędzia deweloperskie

### Aplikacja GUI, i18n i Flatpak

| Komponent | Wersja / źródło | Licencja | Zastosowanie |
|---|---|---|---|
| **PySide6** (Qt for Python) | `6.11.3` (Flatpak) / `6.12.0` (host) | `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only` | Warstwa GUI (`QtWidgets`, `QtGui`, `QtCore`), zasobnik systemowy, wykresy `QPainter` |
| **org.kde.Platform / org.kde.Sdk / io.qt.PySide.BaseApp** | `6.11` (Flathub) | LGPL / GPL / MIT / BSD (komponenty KDE & Qt) | Środowisko uruchomieniowe i bazowe Flatpaka |
| **PipeWire** (`pw-metadata`) | narzędzie systemowe hosta | MIT | Odczyt i zmiana wymuszonej częstotliwości próbkowania (`clock.force-rate`) |
| **AutoEq HTTPS (`urllib.request` / `zlib`)** | biblioteka standardowa Pythona | PSF | Odświeżanie indeksu AutoEq przez Git Smart HTTP (`filter=blob:none`) i pobieranie krzywych z `raw.githubusercontent.com` bez limitów REST API GitHuba |

### Pipeline AutoEq wbudowany w Flatpak (`python3-autoeq`) i `.venvs/autoeq`

| Pakiet | Wersja (Flatpak) | Licencja | Rola |
|---|---|---|---|
| `autoeq` | `4.1.2` | MIT | Optymalizacja 8-pasmowego EQ parametrycznego |
| `scipy` | `1.18.1` | BSD-3-Clause | Optymalizacja numeryczna i filtry |
| `numpy` | `2.5.5` | BSD-3-Clause / 0BSD / MIT / Zlib / CC0-1.0 | Obliczenia macierzowe i interpolacja krzywych |
| `matplotlib` | `3.11.2` | Matplotlib License (PSF-based) | Zależność `autoeq` i opcjonalny eksport wykresów PNG (`eq_fit.py --plot`) |
| `pillow` | `13.0.0` | MIT-CMU | Obsługa obrazów dla `autoeq` / `matplotlib` |
| `pyyaml` | `6.0.3` | MIT | Parsowanie konfiguracji YAML w `autoeq` |
| `tabulate` | `0.10.0` | MIT | Formatowanie tabel w `autoeq.peq` |
| `contourpy` | `1.4.0` | BSD-3-Clause | Zależność `matplotlib` |
| `cycler` | `0.12.1` | BSD-3-Clause | Zależność `matplotlib` |
| `fonttools` | `4.68.0` | MIT | Zależność `matplotlib` |
| `kiwisolver` | `1.5.1` | BSD-3-Clause | Zależność `matplotlib` |
| `packaging` | `26.3` | Apache-2.0 OR BSD-2-Clause | Zależność `matplotlib` |
| `pyparsing` | `3.3.3` | MIT | Zależność `matplotlib` |
| `python-dateutil` | `4.0.0` | BSD-3-Clause | Zależność `matplotlib` |
| `tzdata` | `2026.6` | Apache-2.0 | Dane stref czasowych dla `python-dateutil` |

### Narzędzia jakości kodu i testów

| Narzędzie | Wersja | Licencja | Zastosowanie |
|---|---|---|---|
| `ruff` | `0.17.5` | MIT | Linter składni, importów i formatowania (`pyproject.toml`) |
| `pytest` | `9.2.0` | MIT | Testy jednostkowe protokołu, i18n, UAC2 i testy smoke GUI (`tests/`) |
| `pre-commit` | konfiguracja `.pre-commit-config.yaml` | MIT | Automatyzacja kontroli jakości przed commitem |
