# MOONDROP Position — Natywny kontroler DSP, AutoEq i Audio dla Linuxa

🌐 **Język:** [English](README.md) | Polski

[![Platforma: Linux](https://img.shields.io/badge/Platforma-Linux%20(Wayland%20%2F%20X11)-2ea44f?logo=linux&logoColor=white)](#szybki-start)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776ab?logo=python&logoColor=white)](#szybki-start)
[![UI: PySide6](https://img.shields.io/badge/GUI-PySide6%20(Qt6)-41cd52?logo=qt&logoColor=white)](#zrzuty-ekranu)
[![Licencja: MIT](https://img.shields.io/badge/Licencja-MIT-blue.svg)](LICENSE)

**Odblokuj pełne możliwości sprzętowego DSP w swoim MOONDROP Position (`35d8:0123`) natywnie na Linuxie — bez przeglądarki, bez obciążania CPU i z wbudowanym AutoEq.**

Niezależnie od tego, czy grasz w strzelanki na Steam/Proton, czy stroisz swoje IEM-y pod krzywą Harmana albo własne pomiary REW — ta aplikacja przenosi **100% możliwości oficjalnego konfiguratora webowego ([hub.moondroplab.tech](https://hub.moondroplab.tech/))** na pulpit Linuxa i dokłada tysiące profili AutoEq oraz kontrolę PipeWire UAC2.

---

## Dlaczego wersja dla Linuxa?

### 1. Granie na Linuxie i niskie opóźnienia
- **Sprzętowe DSP bez obciążania CPU:** 8-pasmowy korektor parametryczny działa bezpośrednio na układzie DAC-a (`< 5 ms` opóźnienia). Twój profil EQ działa w każdej grze (Steam/Proton, natywne), na Discordzie i w odtwarzaczu — nawet po zamknięciu aplikacji lub podłączeniu do innego komputera.
- **Kontrola jakości UAC2 / PipeWire:** Podgląd aktywnego strumienia ALSA (`S16_LE` / `S24_3LE` / `S32_LE`) i wymuszanie częstotliwości próbkowania (`44,1–384 kHz`) w PipeWire z poziomu zakładki **Urządzenie**.
- **Zasobnik systemowy (Tray):** Schowaj okno do traya i przełączaj profile EQ dwoma kliknięciami między graniem, muzyką a rozmowami.

### 2. Ogromna baza AutoEq w jednym miejscu
- **Tysiące pomiarów IEM i słuchawek nausznych:** Przeglądaj i filtruj katalog AutoEq (Crinacle, Oratory1990, Rtings i inni) albo wczytaj własną krzywą CSV/TXT (REW).
- **Optymalizacja pod 8 pasm sprzętowych:** Automatyczne dopasowanie wybranego celu dokładnie do limitów MOONDROP Position (`96 kHz` DSP, `PK / LP / HP`, `20–20 000 Hz`, `-18…+12 dB`) z podglądem na tle fabrycznej charakterystyki wg specyfikacji technicznej (B&K 5128).

### 3. Pełna funkcjonalność `hub.moondroplab.tech` + praca offline
| Funkcja | Oficjalny Web Hub | MOONDROP Position na Linux |
|---|---|---|
| 8-pasmowy EQ parametryczny (`PK / LP / HP`) + Pre-gain | Tak (WebHID / Chromium) | **Tak (natywny USB HID `0x4B`, działa offline)** |
| Odsłuch na żywo (`Live preview`) | Tak | **Tak, z automatycznym przywracaniem stanu przy anulowaniu** |
| Wbudowany optymalizator AutoEq | Podstawowe presety | **Pełny katalog AutoEq + własne CSV/TXT + wykresy** |
| Wzmocnienie wyjścia (`-18…0 dB`) i mikrofonu | Tak | **Tak, z opcjonalnym zapisem w profilu** |
| Oddzielna biblioteka na dysku vs pamięć flash DAC-a | Ograniczone | **Pełna biblioteka lokalna, import/eksport JSON i Equalizer APO** |
| Monitor strumienia UAC2 i próbkowania PipeWire | Nie | **Tak (`44,1–384 kHz` + odczyt głębi bitowej ALSA)** |
| Weryfikacja zapisu i kopia zapasowa | Podstawowa | **Weryfikacja przed/po zapisie flash + eksport kopii** |

---

## Zrzuty ekranu

### Strojenie i podgląd charakterystyki
![Strojenie i profile](docs/screenshots/01-tuning-profiles.png)

### Wbudowany katalog AutoEq
![Katalog AutoEq](docs/screenshots/02-autoeq-catalog.png)

### Edytor 8-pasmowego EQ (z odsłuchem na żywo)
![Edytor EQ](docs/screenshots/04-eq-editor.png)

### Stan urządzenia, wzmocnienie i jakość PipeWire UAC2
![Ustawienia urządzenia](docs/screenshots/03-device-settings.png)

---

## Szybki start

### 1. Wypróbuj symulator (bez podłączania sprzętu)
Możesz przetestować cały interfejs, wykresy, katalog AutoEq i edytor EQ bez fizycznego DAC-a:

```bash
git clone https://github.com/tom3k5/moondrop-position-dac.git
cd moondrop-position-dac
python3 skrypty/position_gui.py --demo
```

### 2. Dostęp USB HID na Linuxie (jednorazowa reguła `udev`)
Samo odtwarzanie audio działa od razu w PipeWire. Do sterowania DSP/EQ z konta zwykłego użytkownika potrzebna jest reguła `udev` dla `/dev/hidraw*`:

```bash
sudo cp udev/70-moondrop-position.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```
Podłącz ponownie MOONDROP Position i sprawdź połączenie:
```bash
python3 skrypty/position_gui.py --diagnose
```

### 3. Instalacja z paczki Flatpak (Zalecane)
Pobierz najnowszy plik `position-dac.flatpak` z zakładki [**GitHub Releases**](https://github.com/tom3k5/moondrop-position-dac/releases/latest) (zawiera PySide6 oraz pełny optymalizator AutoEq):

```bash
flatpak install --user position-dac.flatpak
flatpak run local.moondrop.Position
```

*(Uwaga: aby sterować fizycznym DAC-em przez USB HID zarówno z Flatpaka, jak i ze źródeł, zainstaluj regułę `udev` na hoście z kroku 2.)*

### 4. Lub uruchom bezpośrednio ze źródeł
```bash
python3 skrypty/position_gui.py
```
*(Opcjonalnie: do uruchamiania optymalizatora AutoEq ze źródeł skonfiguruj środowisko `.venvs/autoeq` z Pythonem 3.11 zgodnie z [`docs/integracja-autoeq.md`](docs/integracja-autoeq.md).)*

### 5. Lokalna budowa Flatpaka i uprawnienia
```bash
flatpak-builder --force-clean --disable-rofiles-fuse --repo=flatpak-repo flatpak-build local.moondrop.Position.json
flatpak build-bundle flatpak-repo position-dac.flatpak local.moondrop.Position
```
Manifest Flatpak ([`local.moondrop.Position.json`](local.moondrop.Position.json)) używa `--device=all` (dostęp do `/dev/hidraw*` dla DSP), `--share=network` (pobieranie katalogu AutoEq na żądanie użytkownika), `--talk-name=org.kde.StatusNotifierWatcher` (ikona w zasobniku systemowym) oraz `--socket=wayland` / `--socket=fallback-x11` / `--share=ipc` (okno aplikacji).

---

## Wsparcie, zgłoszenia i autor

- **Autor:** [InnoVibe](https://www.innovibe.pl)
- **Postaw mi kawę:** Podoba Ci się projekt? [Wesprzyj rozwój (płatności PL i EU)](https://www.innovibe.pl/kawa) — lub kliknij **☕ Postaw mi kawę** bezpośrednio w stopce aplikacji.
- **Znalazłeś błąd lub masz pomysł?** Użyj przycisku **Zgłoś błąd / Pomysł** w aplikacji (z kopią diagnostyki jednym kliknięciem) albo otwórz zgłoszenie na [GitHub Issues](https://github.com/tom3k5/moondrop-position-dac/issues/new/choose). Strukturyzowane formularze są automatycznie klasyfikowane przez triage AI.

---

## Dokumentacja techniczna

- [`docs/protokol-hid.md`](docs/protokol-hid.md) — Pełna specyfikacja protokołu USB HID `0x4B` (współczynniki Q2.30, sloty, pre-gain, global/mic gain).
- [`docs/integracja-autoeq.md`](docs/integracja-autoeq.md) — Szczegóły integracji katalogu AutoEq i optymalizacji 8 pasm PK.
- [`docs/zrodla.md`](docs/zrodla.md) — Deskryptory USB/UAC2 i pliki referencyjne.
