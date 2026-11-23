# DSP Control

🌐 **Język:** [English](README.md) | Polski

[![Platforma: Linux](https://img.shields.io/badge/Platforma-Linux%20(Wayland%20%2F%20X11)-2ea44f?logo=linux&logoColor=white)](#szybki-start)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776ab?logo=python&logoColor=white)](#szybki-start)
[![UI: PySide6](https://img.shields.io/badge/GUI-PySide6%20(Qt6)-41cd52?logo=qt&logoColor=white)](#zrzuty-ekranu)
[![Licencja: MIT](https://img.shields.io/badge/Licencja-MIT-blue.svg)](LICENSE)

**Odblokuj pełne możliwości sprzętowego DSP w swoim MOONDROP:Gravity Position (`35d8:0123`) natywnie na Linuxie — bez przeglądarki, bez obciążania CPU i z wbudowaną bazą ponad 6800 pomiarów AutoEq.**

Niezależnie od tego, czy grasz na Steam/Proton, czy stroisz swoje słuchawki IEM pod krzywą Harmana albo własne pomiary REW — ta aplikacja przenosi **100% możliwości oficjalnego konfiguratora ([hub.moondroplab.tech](https://hub.moondroplab.tech/))** offline na pulpit Linuxa, dokładając odblokowane filtry półkowe (`LSQ` / `HSQ`), interaktywny edytor EQ i kontrolę PipeWire UAC2.

---

## Szybki start

**Wersja testowa ze źródeł:** Pokazany niżej interfejs DSP Control uruchomisz z tego repozytorium. Aktualny publiczny
Flatpak to [v0.3.8](https://github.com/tom3k5/moondrop-position-dac/releases/tag/v0.3.8).

Wersja ze źródeł zawiera wbudowany indeks modeli i źródeł AutoEq oraz główne targety MIT od pierwszego uruchomienia; odświeżanie indeksu i pobieranie wybranych pomiarów działa przez HTTPS bez logowania i bez limitów REST API GitHuba.

### 1. Instalacja z paczki Flatpak (Zalecane)
Pobierz plik `position-dac.flatpak` z zakładki [**GitHub Releases**](https://github.com/tom3k5/moondrop-position-dac/releases/latest) (zawiera PySide6 i pełny optymalizator AutoEq):

```bash
flatpak install --user position-dac.flatpak
flatpak run local.moondrop.Position
```

### 2. Dostęp USB HID na Linuxie (jednorazowa reguła `udev`)
Samo odtwarzanie audio działa od razu w PipeWire. Aby sterować DSP/EQ z konta zwykłego użytkownika przez `/dev/hidraw*` (wymagane zarówno dla Flatpaka, jak i uruchomienia ze źródeł):

```bash
sudo cp udev/70-dsp-control.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Podłącz ponownie DAC i sprawdź połączenie:

```bash
python3 scripts/dsp_control.py --diagnose
```

Raport JSON wypisze aktywny slot, pre-gain, parametry pasm oraz surowe współczynniki biquad Q2.30 zapisane szesnastkowo.
Jeśli podłączono więcej niż jeden obsługiwany DAC, uruchom polecenie `list` w CLI HID. Użyj właściwego węzła DSP jako
`--device /dev/hidrawN` w poleceniach takich jak `info` lub `eq_fit.py --apply`. W wersji uruchamianej
ze źródeł wybierz egzemplarz w zakładce **Urządzenie**. Jeden obsługiwany DAC jest wybierany automatycznie.

### 3. Wypróbuj bez sprzętu (symulator) lub uruchom ze źródeł
Przetestuj cały interfejs, wykresy, katalog AutoEq i edytor EQ bez podłączania DAC-a:

```bash
git clone https://github.com/tom3k5/moondrop-position-dac.git
cd moondrop-position-dac
python3 scripts/dsp_control.py --demo
```

Aby uruchomić wersję ze źródeł z fizycznym DAC-em, pomiń `--demo`:

```bash
python3 scripts/dsp_control.py
```

*(Opcjonalnie: do uruchamiania optymalizatora AutoEq ze źródeł skonfiguruj środowisko `.venvs/autoeq` z Pythonem 3.11 zgodnie z [`docs/autoeq-integration.md`](docs/autoeq-integration.md).)*

### 4. Lokalna budowa Flatpaka i uprawnienia
```bash
flatpak-builder --force-clean --disable-rofiles-fuse --repo=flatpak-repo flatpak-build pl.innovibe.DspControl.json
flatpak build-bundle flatpak-repo dsp-control.flatpak pl.innovibe.DspControl
```

Manifest Flatpak ([`pl.innovibe.DspControl.json`](pl.innovibe.DspControl.json)) używa `--device=all` (dostęp do `/dev/hidraw*` dla DSP), `--share=network` (pobieranie katalogu AutoEq na żądanie użytkownika), `--talk-name=org.kde.StatusNotifierWatcher` (ikona w zasobniku systemowym) oraz `--socket=wayland` / `--socket=fallback-x11` / `--share=ipc` (okno aplikacji).

Obecny transport HID otwiera bezpośrednio `/dev/hidraw*`. Portal USB Flatpaka przekazuje uchwyt do surowego urządzenia USB dla transportu takiego jak libusb. Do pracy z lokalnymi profilami i zapisanymi krzywymi możesz uruchomić sesję offline poleceniem `flatpak run --unshare=network pl.innovibe.DspControl`.

---

## Dlaczego wersja dla Linuxa?

- **Sprzętowe DSP, zero obciążenia CPU:** 8-pasmowy korektor parametryczny działa bezpośrednio na układzie DAC-a (`< 5 ms` opóźnienia) w każdej grze (Steam/Proton, natywne), na Discordzie i w odtwarzaczach — nawet po zamknięciu aplikacji lub przepięciu do innego komputera.
- **Odblokowane filtry półkowe `LSQ` i `HSQ`:** Podczas gdy `hub.moondroplab.tech` wyłącza półki dla Position (zostawiając tylko `PK / LP / HP`), ta aplikacja odblokowuje sprzętowe `LSQ` i `HSQ` (zweryfikowane na firmware `0.5`). AutoEq domyślnie używa układu `1× LSQ + 1× HSQ + 6× PK`, wielokrotnie zmniejszając błąd dopasowania (`0,47 dB` vs `2,20 dB` RMS dla Position → Harman In-Ear 2019).
- **Bezpieczna praca offline:** Przeglądanie, obliczenia AutoEq i zapis profili na dysku są całkowicie oddzielone od zapisu w pamięci DAC-a. Każde wgranie przechodzi weryfikację odczytem przed i po zapisie flash, a odsłuch na żywo automatycznie przywraca poprzedni stan DAC-a po anulowaniu.
- **Zasobnik systemowy i kontrola PipeWire:** Przełączaj profile dwoma kliknięciami z traya, sprawdzaj aktywną głębię bitową ALSA i w razie potrzeby wymuszaj próbkowanie w PipeWire (`44,1–384 kHz`).

| Funkcja | Oficjalny Web Hub | DSP Control |
|---|---|---|
| 8-pasmowy EQ parametryczny (`PK / LSQ / HSQ / LP / HP`) + Pre-gain | Tylko `PK / LP / HP` (półki wyłączone) | **Odblokowuje `LSQ / HSQ` (`1× LSQ + 1× HSQ + 6× PK`), natywny USB HID `0x4B`, offline** |
| Interaktywny wykres EQ i zapas do przesteru | Tylko suwaki | **Przeciąganie punktów `1–8` (Hz/dB/kółko Q) + automatyczny pre-gain i kontrola clippingu** |
| Odsłuch na żywo (`Live preview`) | Tak | **Tak — włącza się automatycznie i bezpiecznie przywraca stan po anulowaniu** |
| Wbudowany optymalizator AutoEq | Podstawowe presety | **Ponad 6800 modeli + podgląd celu przed obliczeniem + zakres dopasowania + Drag & Drop** |
| Porównanie z obecnym DSP i interaktywna legenda | Nie | **Krzywa `Obecnie w DSP` na obu wykresach, ukrywanie/solo pigułek, odczyt `Hz / dB / Δ dB`** |
| Wzmocnienie wyjścia (`-18…0 dB`) i mikrofonu | Tak | **Tak, z opcjonalnym zapisem w profilu** |
| Biblioteka lokalna vs flash DAC-a | Ograniczone | **Pełna biblioteka na dysku, Drag & Drop, import/eksport JSON i Equalizer APO (`.txt`)** |
| Monitor strumienia UAC2 i próbkowania PipeWire | Nie | **Tak (`44,1–384 kHz` + odczyt głębi bitowej ALSA)** |
| Weryfikacja zapisu i kopia zapasowa | Podstawowa | **Ścisła weryfikacja przed/po zapisie flash, Przywróć poprzedni i kopia EQ jednym kliknięciem** |
| Motywy, język i wbudowany Przewodnik | Tylko web | **Motywy InnoVibe Ciemny i Jasny, PL / EN, zakładka Przewodnik** |

---

## Zrzuty ekranu

DSP Control w trybie demonstracyjnym z motywem **Ciemny (InnoVibe)**.

### 1. Strojenie i podgląd charakterystyki
Po lewej przeglądasz **Moje profile**, a po prawej oglądasz przewidywany efekt bez zmieniania ustawień sprzętu — **Wybrany profil** i **Aktywny w DAC-u** są wyraźnie rozdzielone, dopóki nie klikniesz **Wgraj do DAC-a** (po zapisie przycisk zamienia się w **Przywróć poprzedni**, pozwalając jednym kliknięciem wrócić do poprzedniego stanu, albo pokazuje **Już aktywny w DAC-u**, gdy stan nie był zmieniany).

- **Charakterystyka słuchawek** porównuje krzywą **Fabryczną (B&K 5128)**, **Cel**, **Przewidywany wynik** oraz **Obecnie w DSP**; przycisk **Szczegóły…** obok RMS otwiera okno ze średnim przesunięciem celu i największą odchyłką w paśmie `20 Hz–10 kHz` (zakres powyżej `10 kHz` jest zacieniowany z powodu mniejszej wiarygodności akustycznej).
- **Korekcja EQ** pokazuje odpowiedź elektryczną filtrów przy `96 kHz` wraz z legendą **Obecnie w DSP** / **Korekcja profilu** i osobnym pre-gainem profilu i DSP po prawej stronie. Wysokość wykresów pozostaje stała między zakładkami przy dynamicznej skali osi Y; w mniejszym oknie pojawia się przełącznik wykresów. Najedź na skrócone podsumowanie dopasowania lub komunikat stanu, żeby odczytać pełny tekst.
- Gdy DAC potwierdzi zaokrąglony pre-gain, pasek akcji obok **Wgraj do DAC-a** pokazuje wartość potwierdzoną przez urządzenie i wartość z profilu.
- Klikaj pigułki legendy, aby ukrywać/pokazywać krzywe, najedź na pigułkę dla trybu **Solo**, lub najedź na wykres, by odczytać na żywo `Hz / dB / Δ dB`.

![Strojenie z dwoma wykresami oraz pre-gainem obok legendy korekcji EQ](docs/screenshots/pl/01-tuning-profiles.png)

<details>
<summary>Strojenie w małym oknie</summary>

![Kompaktowe Strojenie z przełącznikiem charakterystyki i korekcji EQ](docs/screenshots/pl/06-tuning-compact.png)

</details>

### 2. Wbudowany katalog AutoEq (ponad 6800 modeli)
W **Katalogu AutoEq** filtruj tysiące pomiarów według **Źródła**, **Typu słuchawek** i **Zakresu obliczeń**, a następnie wyszukaj model (**Pobierz katalog** i licznik **Wyniki: …** znajdują się na wspólnym dolnym pasku). Możesz też przeciągnąć na okno własną krzywą `.csv` / `.txt`.

- Wybierz zakres (`20 Hz–20 kHz` lub do `6 / 4 / 2 kHz`, aby zostawić wyższe pasma do ręcznego strojenia) i kliknij **Oblicz profil** — po obliczeniu pasek pokazuje wyłącznie gotowe akcje (**Zapisz profil**, **Edytuj EQ…**, **Wgraj do DAC-a**).
- Wyliczony profil zapamiętuje użyty zakres (również po zapisaniu na dysku); jeśli zmienisz go później, w miejscu prawego przycisku pojawia się **Przelicz profil**, zanim zapiszesz lub wgrasz wynik.

![Katalog AutoEq](docs/screenshots/pl/02-autoeq-catalog.png)

### 3. Edytor 8-pasmowego EQ i odsłuch na żywo
Kliknij **Edytuj EQ…**, aby otworzyć osobny edytor. Przy podłączonym DAC-u **Odsłuch na żywo** uruchamia się automatycznie, pozwala sprawdzać każdą zmianę w czasie rzeczywistym bez zapisu do flash i bezpiecznie przywraca wcześniejsze ustawienia DAC-a po wyłączeniu lub anulowaniu.

- Przeciągaj ponumerowane punkty `1–8` bezpośrednio na wykresie **Korekcja EQ** (częstotliwość / gain / kółko myszy dla Q), korzystaj z suwaków lub pól liczbowych i użyj **Ustaw automatycznie**, aby dobrać pre-gain bez ryzyka przesterowania.
- Edytor po otwarciu mieści osiem pasm, gdy pozwala na to wysokość ekranu. Rozwiń **Wzmocnienie wyjścia i mikrofonu w profilu** pod pasmami, aby dołączyć te ustawienia.
- Jeśli stroma półka `LSQ` lub `HSQ` przekracza zakres współczynników DAC-a, zmniejsz Q lub gain. Po zakończeniu odsłuch przywraca pierwotne współczynniki i pre-gain.
- Przełącz na zakładkę **Charakterystyka**, aby ocenić odpowiedź akustyczną, włącz **Porównaj z profilem wyjściowym**, a dolnym paskiem zapisz profil na dysku (**Zapisz profil**), wyeksportuj (**Eksportuj profil…** do `.txt` / `.json`) lub wgraj do pamięci DAC-a (**Wgraj do DAC-a**).

![Edytor EQ](docs/screenshots/pl/04-eq-editor.png)

### 4. Stan urządzenia, wzmocnienie i jakość PipeWire UAC2
Sprawdź od razu aktywny profil na DAC-u, slot (`0` fabryczny / `7` własny), pre-gain oraz wzmocnienie wyjścia i mikrofonu.

- Podglądaj aktywny strumień ALSA i ustaw **Próbkowanie PipeWire** dla całej sesji. Wybierz **Automatyczna (PipeWire)** lub stałą częstotliwość (`44,1–384 kHz`) i kliknij **Zastosuj**. W sekcji **Szczegóły USB i PipeWire** znajdziesz surowy format USB i wersję firmware.
- Wykonaj kopię zapasową slotu Custom do pliku JSON, przywróć **Ustawienia fabryczne…** oraz zmieniaj motyw (**InnoVibe Ciemny / Jasny**) i język (**PL / EN**).

![Ustawienia urządzenia z pełną etykietą Automatyczna (PipeWire)](docs/screenshots/pl/03-device-settings.png)

<details>
<summary>Urządzenie w małym oknie</summary>

![Kompaktowy widok Urządzenia z pełną etykietą próbkowania i przyciskami Zastosuj oraz Odśwież](docs/screenshots/pl/07-device-compact.png)

</details>

### 5. Wbudowany Przewodnik, skróty i diagnostyka
Wszystko pod ręką wewnątrz aplikacji: krótkie instrukcje wgrywania i odsłuchu, wyjaśnienie wykresów, obsługa Drag & Drop, skróty klawiszowe (`Ctrl+F` szukanie, `Ctrl+O` import, `Ctrl+Q` wyjście), kopiowanie diagnostyki jednym kliknięciem do zgłoszeń, informacja o wersji i licencji w prawym dolnym rogu oraz odnośniki do wsparcia.

![Zakładka Przewodnik](docs/screenshots/pl/05-guide-tab.png)

---

## Dokumentacja techniczna

- [`docs/hid-protocol.md`](docs/hid-protocol.md) — Pełna specyfikacja protokołu USB HID `0x4B` (współczynniki Q2.30, sloty, pre-gain, global/mic gain).
- [`docs/autoeq-integration.md`](docs/autoeq-integration.md) — Szczegóły integracji katalogu AutoEq i optymalizacji 8 pasm (`LSQ + HSQ + 6× PK` / `PK`).
- [`docs/sources.md`](docs/sources.md) — Deskryptory USB/UAC2 i pliki referencyjne.

---

## Wsparcie dla projektu

> [!TIP]
> **Podoba Ci się DSP Control?**
> Jeśli aplikacja pomaga Ci wycisnąć lepsze brzmienie ze swojego DAC-a na Linuxie, możesz wesprzeć jej dalszy rozwój — każda kawa pomaga w kolejnych aktualizacjach, testach sprzętowych i nowych funkcjach!

- ☕ **Postaw mi kawę:** Odwiedź [**stronę wsparcia InnoVibe**](https://innovibe.pl/ko-fi/) (wybierz kwotę i wygodną metodę płatności) albo kliknij **Postaw mi kawę…** w sekcji **Wsparcie projektu** w zakładce **Przewodnik**.
- 👤 **Autor:** [InnoVibe](https://www.innovibe.pl)
- 🐛 **Błędy i pomysły:** Użyj przycisku **Zgłoś błąd / Pomysł** w zakładce **Przewodnik** (z kopią diagnostyki jednym kliknięciem) albo otwórz zgłoszenie na [GitHub Issues](https://github.com/tom3k5/moondrop-position-dac/issues/new/choose).
