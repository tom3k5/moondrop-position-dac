# Integracja AutoEq + bazy EQ z DSP MOONDROP Position — rekomendacja

Dokument opisuje, **jak najlepiej zintegrować funkcjonalność autoeq.app** (baza
pomiarów, targety, optymalizator EQ parametrycznego) z **sprzętowym DSP**
modułu MOONDROP Position (`35d8:0123`, report HID `0x4B`). Protokół sterowania:
[`protokol-hid.md`](protokol-hid.md).

## 1. Czego dostarcza AutoEq i czego nie

[autoeq.app](https://autoeq.app) i biblioteka [AutoEq](https://github.com/jaakkopasanen/AutoEq)
(MIT) to **nie jest** aplikacja do sterowania urządzeniami. To:

| Element | Co daje |
|---|---|
| baza pomiarów (`measurements/`) | krzywe FR od oratory1990, crinacle, Rtings, Innerfidelity itd. |
| baza targetów (`targets/`) | Harman in-ear 2016/2017/2019, AutoEq in-ear, diffuse field… |
| biblioteka `autoeq` (PyPI 4.1.2) | wczytywanie CSV, interpolacja, centrowanie, kompensacja targetu, wygładzanie, limitowanie wzmocnienia, **optymalizator EQ parametrycznego** (`PEQ_CONFIGS`, `optimize_parametric_eq`) |
| autoeq.app (web) | UI do wyboru modelu/targetu, upload własnego pomiaru, eksport do Equalizer APO / Wavelet / itd. Backend to FastAPI (`webapp/main.py`, endpoint `POST /equalize`), więc można go też self-hostować |
| wyniki (`results/`) | gotowe pliki `ParametricEQ.txt` / `GraphicEQ.txt` dla setek modeli |

**Czego brakuje:** AutoEq nie zna protokołu `0x4B` i nie zapisze nic do DAC-a.
To ogniwo trzeba dostarczyć samemu — i to już jest w tym projekcie.

Uwaga o modelu: **Moondrop Position nie ma jeszcze pomiaru w bazie AutoEq**
(AutoEq korzysta tylko z wybranych źródeł). Projekt dołącza natomiast krzywą
odniesienia `dane/pomiary/Moondrop Position (B&K 5128).csv` opracowaną
na podstawie publicznej specyfikacji technicznej producenta (`POSITION (Original)`,
B&K 5128). Dla innych słuchawek można korzystać wprost z bazy AutoEq lub własnych
plików REW / `squig.link` (L/R `.txt`).

## 2. Co już działa w projekcie (zweryfikowane)

| Element | Plik | Status |
|---|---|---|
| protokół HID + zapis/odczyt EQ, pre-gain, slot | `skrypty/moondrop_position.py` | Odczyt na firmware 0.5 potwierdzony. Wyniki i zakres dalszych prób w README §7. |
| pipeline AutoEq: pomiar + target → 8 pasm → profil JSON | `skrypty/eq_fit.py` | **przetestowany** na prawdziwym pomiarze Position |
| import EQ z autoeq.app (Equalizer APO) | `moondrop_position.py import-eq` | przetestowany na przykładowym eksporcie |
| venv z AutoEq (Python 3.11, numpy/scipy) | `.venvs/autoeq/` | działa, skrypt sam się przełącza |
| reguła udev | `udev/70-moondrop-position.rules` | gotowa, wymaga `sudo` |
| dane: krzywa fabryczna + targety | `dane/pomiary/`, `dane/targety/` | opracowana ze specyfikacji + targety MIT z AutoEq |
| przykładowy profil | `dane/profile/moondrop-position-harman.json` | wygenerowany dla Harman In-Ear 2019 |

Wynik testu (pomiar Position vs Harman in-ear 2019, 8 pasm PK, fs = 96 kHz):

```
błąd RMS: 2,01 dB (przed EQ) → 0,34 dB (po EQ), max 2,75 dB
preamp: −2,65 dB
```

## 3. Architektura rekomendowana

```
                 ┌─────────────────────────── baza EQ (lokalna) ───────────────────────────┐
                 │  pomiary: squig.link (L/R .txt), AutoEq measurements/, własne REW      │
                 │  targety: AutoEq targets/, squig targets, własne                        │
                 │  presety: sloty fabryczne Moondrop (odczyt z urządzenia), eqcaps limity │
                 └───────────────────────────────┬─────────────────────────────────────────┘
                                                 │
                                    ┌────────────▼────────────┐
                                    │  obliczenia (AutoEq)    │
                                    │  compensate → smoothen  │
                                    │  → equalize → optimize  │
                                    │  z limitami urządzenia  │
                                    └────────────┬────────────┘
                                                 │ profil JSON
                                    ┌────────────▼────────────┐
                                    │  transport HID 0x4B     │
                                    │  hidraw (native)        │
                                    │  albo WebHID (Chrome)   │
                                    └────────────┬────────────┘
                                                 │
                                    ┌────────────▼────────────┐
                                    │  DSP MOONDROP Position  │
                                    │  slot 7 „Custom”, flash │
                                    └─────────────────────────┘
```

**Pierwsza wersja to PySide6 + hidraw, dystrybuowana jako Flatpak na Linux.**
Python współdzieli obsługę profili i zapis DAC-a między GUI i CLI. HIDAPI
pozostaje opcją, gdy projekt obejmie inne systemy. AutoEq jest osobnym
modułem obliczeniowym. Przegląd i stosowanie profili działają offline.

Źródła: [Qt for Python — dystrybucja](https://doc.qt.io/qtforpython-6/deployment/index.html),
[HIDAPI — backendy i udev](https://github.com/libusb/hidapi#about),
[MDN — dostępność WebHID](https://developer.mozilla.org/en-US/docs/Web/API/WebHID_API).

## 4. Warianty integracji — porównanie

| Wariant | Jak | Zalety | Wady | Kiedy wybrać |
|---|---|---|---|---|
| **A. CLI** | `eq_fit.py` → JSON → `write-eq`/`--apply`; hidraw + udev | offline, automat, profile w repo, każdy target/pomiar, brak Chromium | brak wykresu „na żywo” poza PNG; trzeba znać terminal | codzienne używanie, skrypty, auto-apply po podłączeniu |
| **B. autoeq.app + import** | pomiar CSV → autoeq.app (target) → eksport Equalizer APO → `import-eq` → `write-eq` | wygodne UI, własny pomiar | ręczne przenoszenie pliku, generowanie profilu online | jednorazowe strojenie, gdy nie chcesz uruchamiać venv |
| **C. modernGraphTool / devicePEQ (WebHID)** | po udev: strona → połącz → auto-fit → zapis | GUI z wykresem, AutoEq w przeglądarce, profil Position już w eqcaps | zależność od strony, WebHID + Chrome, mniej kontroli, dane nie w repo | szybki podgląd i ręczne poprawki |
| **D. FreeDSP Studio** | natywny Rust, .deb/.rpm, auto-fit + profil rodziny gen-2 | natywne GUI, działa bez przeglądarki | profil Position niezweryfikowany (scheme 13), Linux „untested with cable” | gdy wolisz gotową aplikację desktopową |
| **E. EasyEffects / JamesDSP (software)** | import AutoEq `ParametricEQ` do PipeWire | nieograniczona liczba pasm/półek, natychmiastowe | tylko ten komputer, nie w DAC-u, łamie „DSP w urządzeniu” | gdy 8 pasm PK nie wystarcza (np. treble) |
| **F. PySide6 + hidraw (pierwsze GUI)** | Linux, Flatpak z runtime Qt | offline, wspólna logika CLI i GUI, bez zależności od powłoki pulpitu | wymaga uprawnień udev na hoście i widoczności hidraw w Flatpaku | codzienne sterowanie Position i edycja profili |

## 5. Baza EQ — struktura i źródła

Proponowany układ (zgodny z zasadą „projekt samowystarczalny”):

```
dane/
├── pomiary/          # krzywa fabryczna Position (B&K 5128) + opcjonalne własne pliki REW/squig.link
├── targety/          # targety MIT z AutoEq (Harman in-ear 2019, JM-1)
└── profile/          # gotowe profile JSON
```

Źródła i sposób odświeżania (opisane też w `dane/pomiary/README.md`):

* **MOONDROP Position (specyfikacja techniczna)** — `dane/pomiary/Moondrop Position (B&K 5128).csv`
  opracowany na podstawie publicznych materiałów producenta (`POSITION (Original)`).
* **Własne pomiary użytkownika (REW / squig.link)** — parser (`skrypty/measurements.py`) obsługuje formaty CSV oraz eksporty `.txt` (REW 1/48 oct, pojedyncze lub L/R) dostarczone lokalnie przez użytkownika.
* **AutoEq** — `measurements/<źródło>/data/in-ear/*.csv` i `targets/*.csv`
  (MIT; dane pomiarowe od oratory1990/crinacle/Rtings itd.).
* **oficjalne Moondrop** — dwa kanały:
  1. sloty fabryczne w urządzeniu (slot 0 „Default”) — można je **odczytać
     przez HID** i zapisać jako „oficjalny preset”; to dosłownie fabryczne
     strojenie z pamięci DAC-a,
  2. tabela urządzeń/limitów z oficjalnej apki `hub.mondroplab.com`
     (zebrana w eqcaps: profil `moondrop-position`).
* **eqcaps** — limity EQ dla urządzenia (8 pasm, PK/LP/HP, zakresy), baza
  publiczna (dane CC0).

`dump-slots` odczytuje aktywny slot. Opcja `--switch` odczytuje sloty 0
i 7, po czym wraca do początkowego slotu i sprawdza jego gain. Zrzut
sprzętowy nadal czeka na weryfikację.

## 6. Integracja z systemem Linux

1. Sprawdzić istniejącą regułę `udev/70-moondrop-position.rules` w aktywnej
   sesji KDE. Potwierdzić otwarcie interfejsu DSP przez użytkownika po
   ponownym podłączeniu DAC-a. Interfejs klawiszy konsumenckich pomijamy.
2. Sprawdzić start GUI na Wayland poza sandboxem. Pierwszą wersję uruchomić
   z lokalnego Pythona i dodać wpis w menu KDE po teście na sprzęcie.
3. Auto-apply zostawić wyłączone domyślnie. Rozważyć je po teście trwałości
   ustawień. Przy ponownym podłączeniu najpierw odczytać stan i pominąć
   zapis flash, jeśli żądany profil jest już aktywny.

## 7. Ograniczenia sprzętu i obejścia

* **8 pasm, AutoEq generuje PK** (apka wyłącza półki) → największy problem to treble
  > 10 kHz (wąskie piki) i szerokie pułapki basu. Obejścia:
  * targety „łagodniejsze” (`--tilt`, `--bass-boost`, target AutoEq in-ear),
  * `--eq-max-gain` mniejsze (mniej agresywna korekcja góry),
  * **sprawdzić eksperymentalnie, czy firmware przyjmuje LS/HS** (bajty typu
    1/3 są w protokole) — jeśli tak, można użyć `8_PEAKING_WITH_SHELVES`;
  * hybryda: sprzętowo 8 pasm + EasyEffects na treble (fallback).
* **Stałe 96 kHz** w DSP — optymalizator wywołujemy z `fs=96000`, żeby
  przewidywana odpowiedź zgadzała się z tym, co policzy urządzenie.
* **Preamp** — AutoEq liczy `−max_gain − 0.1 dB`; zapisujemy go do rejestru
  `0x23` (zakres −128…0 dB, krok 1/256).
* **Flash** — każdy zapis zużywa pamięć; zapisuj tylko po zmianie profilu.

## 8. Ryzyka i pułapki

1. **Pomiar a fabryczny DSP.** Krzywa fabryczna `POSITION (Original)` obejmuje
   brzmienie zestawu z aktywnym slotem 0 („Default”). Dlatego przy optymalizacji
   AutoEq odejmujemy odpowiedź slotu 0 od krzywej odniesienia przed wyliczeniem 8 pasm Custom.
2. **Kolejność zapisu** — pasmo, latch `0x0A`, preamp, save `0x01`; tempo
   ~25/50/200 ms (patrz `protokol-hid.md` §10).
3. **`LEN` i echo slotu** — różne aplikacje wysyłają różne `LEN`; trzeba
   opróżniać kolejkę przed każdym żądaniem i sprawdzać echo indeksu.
4. **Prawa** — AutoEq oraz targety w `dane/targety/` są na licencji MIT;
   `dane/pomiary/Moondrop Position (B&K 5128).csv` pochodzi z publicznej specyfikacji
   producenta; dane `eqcaps` są na CC0. Ewentualne własne pomiary ze `squig.link`
   dostarcza wyłącznie użytkownik lokalnie.

## 9. Plan wdrożenia

| Etap | Zakres | Kryterium odbioru |
|---|---|---|
| 1. Sprzęt na Linuksie | Reguła udev, odczyt firmware, slotów i pre-gainu. Kopia Custom, zapis Harman, odłączenie, weryfikacja i przywrócenie. Porównanie z aplikacją Moondrop w razie rozbieżności. | EndeavourOS/KDE Wayland, zwykły użytkownik. Wyniki odczytu i ponownego podłączenia zapisane w projekcie. |
| 2. Wspólny moduł | CLI i GUI używają wspólnej walidacji, zapisu i weryfikacji profili. Transport Linux wybiera interfejs DSP na podstawie VID/PID i deskryptora z raportem `0x4B`. | Ten sam firmware, bank EQ i gain odczytane z CLI na hoście i z GUI w Flatpaku. |
| 3. Pierwsze GUI | Ekran główny z wykrywaniem DAC-a, odczytem stanu, wyborem profilu i jego zastosowaniem. Operacje HID w jednym wątku roboczym; obsługa podłączania i odłączania. | Po podłączeniu użytkownik wybiera Harman i klika „Zastosuj”. GUI potwierdza profil odczytem. Odłączenie w trakcie pokazuje błąd i pozwala wrócić do odczytu po podłączeniu. |
| 4. Edytor i funkcje DAC-a | Wykres, osiem pasm, pre-gain, JSON i import Equalizer APO. AutoEq z lokalnego pomiaru i targetu. Każde ustawienie sprzętowe sprawdzane osobno na Position. | Każda udostępniona funkcja ma potwierdzony zakres i wynik odczytu na Position. |
| 5. Dystrybucja | Lokalna paczka Flatpak. KDE/Wayland jako pierwsze środowisko odbiorowe, potem drugi pulpit Linuksa. | W Flatpaku działa połączenie, odczyt, zastosowanie profilu, ponowne podłączenie i przywrócenie kopii. |

### Układ aplikacji

| Widok | Obsługa |
|---|---|
| **Strojenie** | Moje profile i Katalog AutoEq korzystają ze wspólnego podglądu charakterystyki i korekcji EQ. „Wgraj do DAC-a” sprawdza wynik odczytem. „Więcej → Usuń profil…” usuwa wpis użytkownika z biblioteki po potwierdzeniu. |
| **Edytor EQ** | Osiem pasm z suwakami gainu, częstotliwością, typem, Q i pre-gainem. Odsłuch włącza się domyślnie przy otwarciu edytora z podłączonym DAC-em i zmienia jego ustawienia bez zapisu do flash. Wyłączenie lub zamknięcie przywraca poprzedni stan. „Wgraj do DAC-a” i „Zapisz profil” są osobnymi akcjami. |
| **Urządzenie** | Odczyt firmware, aktywnego slotu i wzmocnień, regulacja wyjścia i mikrofonu, eksport kopii oraz przywracanie ustawień fabrycznych. Zakres prób dodatkowych funkcji opisuje README §7. |

Default i Custom to sloty sprzętowe. Biblioteka może mieć dowolną liczbę
profili, a zastosowanie profilu użytkownika aktualizuje Custom. Przy
ponownym połączeniu GUI odczytuje stan. „EQ off” wymaga potwierdzonego
bypassu lub neutralnego ustawienia. Sama nazwa Default tego nie oznacza.

### Stan weryfikacji

Na EndeavourOS/KDE Wayland potwierdzono odczyt sprzętowy firmware 0.5,
aktywnego slotu i ośmiu pasm przez `hidraw`. W Qt offscreen sprawdzono
edycję z odsłuchem, przywrócenie stanu, zapis i usuwanie profili w
symulatorze. Na sprzęcie pozostaje potwierdzić słyszalność zmian i
trwałość wgranego profilu po ponownym podłączeniu.

Bieżące testy uruchamiamy ze źródeł. Tryb demonstracyjny uruchamia
`python3 skrypty/position_gui.py --demo`, a odczyt fizycznego DAC-a
`python3 skrypty/position_gui.py --diagnose`. Manifest pozostaje w
projekcie na etap dystrybucji Flatpaka.

## 10. Szybki start (to, co już można uruchomić)

```bash
cd 02_System-Linux/moondrop-position-dac

# 1) profil z pomiaru i targetu (bez urządzenia; sam się przełączy na venv)
skrypty/eq_fit.py \
  -m "dane/pomiary/Moondrop Position L.txt" \
  -t "dane/targety/Harman in-ear 2019.csv" \
  -o dane/profile/moondrop-position-harman.json \
  --plot dane/profile/moondrop-position-harman.png

# 2) albo: EQ wygenerowany w autoeq.app (eksport Equalizer APO)
skrypty/moondrop_position.py import-eq --file eqapo.txt --out dane/profile/profil.json

# 3) zapis do DAC-a (po regule udev)
skrypty/moondrop_position.py write-eq --file dane/profile/profil.json --dry-run
skrypty/moondrop_position.py write-eq --file dane/profile/profil.json --yes
# albo od razu: skrypty/eq_fit.py ... --apply
```
