# Instrukcja dla testerów sprzętu (CHU II DSP i ECHO-A)

🌐 **Język:** [English](tester-guide.md) | Polski

Dziękujemy za pomoc w weryfikacji eksperymentalnych sterowników dla **MOONDROP CHU II DSP** (`31b2:0113`) oraz **MOONDROP ECHO-A** (`3302:12c5`) na Linuxie!

> [!IMPORTANT]
> Wszystkie testy wykonuj ze źródeł (gałąź `main`) w sesji zwykłego użytkownika — **nigdy jako `root`**.

## 1. Zainstaluj regułę `udev` (jednorazowo)

```bash
sudo cp udev/70-dsp-control.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Odłącz i podłącz ponownie przewód/adapter USB-C.

## 2. Uruchom raport diagnostyczny bez roota

```bash
python3 scripts/dsp_control.py --diagnose
```

Polecenie wypisze raport JSON **bez uprawnień roota**. Sprawdź:
- `hidraw_interfaces`: czy urządzenie jest widoczne z `readable: true` i `writable: true`,
- `matched_model`: `"moondrop-chu2-dsp"` lub `"moondrop-echo-a"`,
- `bands`: aktualnie odczytane pasma EQ.

## 3. Wykonaj kopię zapasową obecnego EQ

Uruchom aplikację ze źródeł:

```bash
python3 scripts/dsp_control.py
```

Przejdź do zakładki **Urządzenie** → **Kopia ustawień i przywracanie** → **Eksportuj EQ z DAC-a...** i zapisz kopię do pliku JSON przed wprowadzeniem zmian.

## 4. Przetestuj zapis, ponowne podłączenie i przywrócenie

1. W zakładce **Strojenie** wybierz profil testowy lub otwórz **Edytor EQ** i wprowadź drobną, wyraźnie słyszalną zmianę (np. `+3 dB` PK przy `1000 Hz`).
2. Zastosuj zmiany na DAC-u i sprawdź, czy weryfikacja odczytem zakończyła się powodzeniem.
   - **Uwaga dla CHU II DSP:** zapis do flash (`0x53`) celowo restartuje urządzenie USB na ok. 1–1,5 s. Odczekaj na ponowne wykrycie.
3. Odłącz i podłącz ponownie urządzenie USB-C, po czym ponownie uruchom `python3 scripts/dsp_control.py --diagnose`, aby potwierdzić trwałość zapisu.
4. Przywróć zapisaną kopię zapasową i potwierdź powrót do stanu wyjściowego.

## 5. Zgłoś wyniki

Otwórz formularz [**Hardware Test Report**](https://github.com/tom3k5/moondrop-position-dac/issues/new?template=hardware-test-report.yml) na GitHubie i wklej wynik JSON z `--diagnose` wraz z listą sprawdzonych funkcji.
