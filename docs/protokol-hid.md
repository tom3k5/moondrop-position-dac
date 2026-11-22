# Protokół HID MOONDROP Position (35d8:0123)

Dokument opisuje kanał sterowania DSP/EQ w module USB-C „MOONDROP Position”.
Opis ramek opiera się na otwartych implementacjach (patrz `zrodla.md`).
Wyniki prób na tym modelu są opisane przy poszczególnych poleceniach
oraz w [README](../README.md#7-wyniki-prób-sprzętowych).

## 1. Warstwa transportowa

| Element | Wartość |
|---|---|
| Interfejs USB | interface 3 (`bInterfaceClass=3`, HID 1.11) |
| Węzeł | `/dev/hidraw0` (przy `input3`), ewentualnie `input/by-id/usb-MOONDROP_MOONDROP_Position_<SERIAL>-if03-hidraw` |
| Report ID | **`0x4B`** (75) — 63 B danych + 1 B ID = 64 B ramka |
| Endpointy | OUT `0x05` (interrupt, 64 B), IN `0x86` (interrupt, 64 B) |
| Drugi report | `0x54` — input+output 63 B, nieużywany przez publiczną aplikację (patrz §9) |
| Sterowanie | zwykły zapis/odczyt raportu (`hid_write`/`hid_read`, WebHID `sendReport`/`inputreport`); **nie** używa control pipe (`GET_REPORT`), więc działa z przeglądarki |

Interface 4 to osobny HID konsumencki (`report 0x03`) — klawisze głośności,
play/pauza i mute (szczegóły w §8).

## 2. Format ramki

```
[0x4B] [OP] [CMD] [LEN] [payload ...]        (64 B, brakujące bajty = 0)
```

* `OP` = `0x01` zapis, `0x80` odczyt
* `CMD` — numer polecenia (§3)
* `LEN` — w praktyce urządzenie toleruje różne wartości; aplikacje używają
  `0x18` (24) dla poleceń EQ i `0x00`/długości payloadu dla reszty.
  FreeDSP Studio wysyła tu długość payloadu, devicePEQ/Moondrop — `0x18`.
  Nasz skrypt używa wartości z handlera Moondrop.
* Odpowiedź wraca jako input report na tym samym `0x4B`; w payloadzie
  `[0x80] [CMD] [...]` (czyli pierwsze dwa bajty po ID to OP i CMD).

Przykład — odczyt wersji:

```
→ 4b 80 0c 00 00 ...
← 4b 80 0c 01 30 2e 37 ...      # "0.7"
```

## 3. Polecenia

| CMD | Nazwa | Kierunek | Payload / odpowiedź |
|---|---|---|---|
| `0x01` | SAVE_EQ (flash) | W | pusty — zapisuje EQ do flash |
| `0x02` | MIC_GAIN | R/W | int16 LE, skala `32767/15` na dB, zakres ±15 dB |
| `0x03` | GLOBAL_GAIN | R/W | 1 B signed (całe dB); odczyt: bajt `p[4]` |
| `0x04` | SAVE_OFFSET | W | pusty — zapis pre-gain/offsetu do flash |
| `0x05` | RESET / memory refresh | W | `[0x05, 0x04, 0x00]` itp. (używane przed commitem) |
| `0x09` | EQ_UPDATE | R/W | odczyt/zapis pasma (§4, §5) |
| `0x0A` | EQ_COEFF (latch) | W | `[0x0A, idx, 0x00, 0xFF, 0xFF, 0xFF]` — zatrzaskuje współczynniki pasma |
| `0x0C` | VERSION | R | odpowiedź: ASCII „x.y.z” na `p[3..5]` |
| `0x0F` | ACTIVE_SLOT | R/W | odczyt `p[3]`; po OP zapisu `[0x0F, slot]` (devicePEQ) lub `[0x0F, 0x01, slot]` (FreeDSP) |
| `0x11` | DAC_FILTER | R/W | filtr DAC (1..5: FAST-LL/FAST-PC/SLOW-LL/SLOW-PC/NON-OS) |
| `0x16` | CHANNEL_BALANCE | R/W | balans L/P (0–127) |
| `0x18` | LED_SWITCH | R/W | dioda |
| `0x19` | DAC_GAIN | R/W | wzmocnienie DAC |
| `0x1D` | DAC_WORK_MODE | R/W | 0 = normalny, 1 = alternatywny |
| `0x23` | PRE_GAIN | R/W | int16 LE, krok 1/256 dB, zakres −128…0 dB |
| `0xFF` | UPGRADE | W | tryb aktualizacji firmware (nieużywane) |

Polecenia spoza handlera Moondrop (z katalogu Walkplay): `0x17` ENC refresh,
`0x25` SOUND_SOURCE_ANGLE (3D/reverb), `0x60` ENABLE_DISABLE, `0xD3` MODE_VALUE,
`0x0D` EXTENDED_EQ, `0x0E` READ_VERSION_ALT. Nie były testowane na tym modelu.

## 4. Odczyt pasma (CMD 0x09)

```
→ [0x80, 0x09, 0x18, 0x00, idx, 0x00]     idx = 0..7 (lub 0..9)
← [0x80, 0x09, ..., ...]
```

Układ odpowiedzi (indeksy w payloadzie **bez** bajtu report ID):

| Offset | Pole | Kodowanie |
|---|---|---|
| 4 | indeks pasma | 0-based, echo żądania |
| 7..26 | współczynniki IIR | 5 × int32 LE, Q2.30 (b0,b1,b2,−a1,−a2) |
| 27..28 | częstotliwość | uint16 LE, Hz |
| 29..30 | Q | int16 LE, 8.8 fixed (÷256) |
| 31..32 | gain | int16 LE, 8.8 fixed (÷256), dB |
| 33 | typ filtra | 1 = LS, 2 = PK, 3 = HS, 4 = LP, 5 = HP |
| 35 | aktywny slot | np. 0 lub 7 |

Odpowiedź „nieprawidłowa” (freq poza 10..24000 Hz) oznacza pasmo nieużywane
lub odczyt z innego polecenia.

## 5. Zapis pasma (CMD 0x09) + commit

Payload zapisu (63 B):

| Offset | Pole |
|---|---|
| 0 | `0x01` (OP write) |
| 1 | `0x09` |
| 2 | `0x18` |
| 3 | `0x00` |
| 4 | indeks pasma |
| 5–6 | `0x00` |
| 7..26 | 20 B współczynników (jak wyżej) |
| 27..28 | freq uint16 LE |
| 29..30 | Q 8.8 |
| 31..32 | gain 8.8 |
| 33 | typ |
| 34 | `0x00` |
| 35 | slot docelowy (7 = Custom w rodzinie Moondrop) |

Po każdym paśmie trzeba je zatrzasnąć (`0x0A`), inaczej współczynniki siedzą
w rejestrach staging i nic nie słychać:

```
→ [0x01, 0x0A, idx, 0x00, 0xFF, 0xFF, 0xFF]
```

Sekwencja zapisu całego banku (kolejność z handlera Moondrop):

1. Przełącz na slot Custom, jeśli jest nieaktywny. Jeżeli odczyt po ramce
   `[0x01, 0x0F, slot]` nie potwierdzi zmiany, spróbuj
   `[0x01, 0x0F, 0x01, slot]`. Zapis pasm zaczyna się po odczytaniu slotu 7.
2. dla każdego pasma: zapis `0x09` → `0x0A`,
3. (opcjonalnie) pre-gain: `[0x01, 0x23, 0x00, lo, hi]` (devicePEQ).
   Jeśli odczyt nie potwierdzi ustawienia, spróbuj
   `[0x01, 0x23, 0x02, lo, hi]` (FreeDSP Studio) i ponownie sprawdź wartość.
4. Przy trwałym wgraniu zweryfikuj slot, pasma i potwierdzoną wartość
   pre-gainu. Wyślij `[0x01, 0x01]` (SAVE_EQ) i powtórz odczyt.

Po wgraniu profilu GUI odświeża krzywą DSP na podstawie pięciu
współczynników Q2.30 każdego pasma zwróconych przez `0x09`. Przy wyliczaniu
krzywej uwzględnia częstotliwość 96 kHz i pokazuje odczytany pre-gain osobno.
Weryfikacja przed zapisem do flash i po nim nadal sprawdza odczytane
parametry pasm, aktywny slot i potwierdzoną wartość pre-gainu.

Odstępy: ~25 ms między pasmami, ~50 ms między operacjami, ~150 ms po zmianie
slotu, ~200 ms po zapisie do flash. Urządzenie gubi ramki wysyłane szybciej.

### Odsłuch i odczyt pre-gainu

Odsłuch korzysta z tych samych poleceń zapisu i zatrzaskiwania pasm
oraz z odczytu kontrolnego. Pomija SAVE_EQ. Aplikacja przed odsłuchem
odczytuje aktywny slot, jego pre-gain i osiem pasm Custom. Po zakończeniu
przywraca pasma Custom, poprzedni slot i potwierdza pre-gain z kopii.

Format transportowy 8.8 koduje pre-gain z krokiem 1/256 dB. W próbie na
firmware 0.5 żądanie −2,6484375 dB (profil −2,65 dB) dało odczyt
−2,50 dB. Dla wgrywania profilu i odsłuchu aplikacja najpierw próbuje
dokładnej wartości. Alternatywnie dopuszcza najbliższą wartość na siatce
0,5 dB, gdy DAC ją potwierdzi. Odczyt dalszy od oczekiwanej wartości
pozostaje błędem. Potwierdzona wartość służy do kontroli przed zapisem
flash i po nim. Pojedyncza obserwacja nie ustala rozdzielczości firmware
w całym zakresie.

## 6. Współczynniki biquada

Urządzenie liczy filtry przy **stałej częstotliwości 96 kHz** i przechowuje
współczynniki jako **Q2.30** (×2³⁰, int32 LE). Wzory RBJ (a0 znormalizowane do 1):

```
w0 = 2π·f / 96000
PK:  A = 10^(gain/40); α = sin(w0)/(2Q)
     b = [1+αA, -2cos w0, 1-αA]
     a = [1+α/A, -2cos w0, 1-α/A]
LS/HS: A = 10^(gain/40); α = sin(w0)/2 · √((A+1/A)(1/Q-1)+2); S = 2√A·α
     (wzory jak w RBJ cookbook)
LP/HP: α = sin(w0)/(2Q)
     b = [(1∓cos w0)/2, 1∓cos w0, (1∓cos w0)/2] / (1+α)  (znak zależnie od typu)
     a = [1, -2cos w0/(1+α), (1-α)/(1+α)]
```

Zapis: `[b0, b1, b2, −a1, −a2] / a0`, każdy ×2³⁰, `int32 LE`.
Przy 0 dB współczynniki nie są trywialne (b0=1, b1=−a1, b2=−a2), ale filtr
jest przezroczysty.

Uwaga: niektóre implementacje (devicePEQ) mają dodatkowe poprawki
`freqCompensation`/`qCompensation` dla wybranych scheme'ów; dla Position
z oficjalnej apki wynika brak korekt (scheme 13 wg katalogu Walkplay, ale
apka Moondrop traktuje to urządzenie jako 8-pasmowe, patrz §7).

## 7. Limity EQ (oficjalna aplikacja Moondrop)

Źródło: `hub.mondroplab.com` — Custom EQ web app 1.8.0 build 26B1107,
tabela urządzeń, konfiguracja POSITION (zebrane w bazie `eqcaps`):

| Parametr | Wartość |
|---|---|
| Liczba pasm | 8 |
| Typy filtrów | PK, LPQ, HPQ — **półki wyłączone** w oficjalnej apce, ale **potwierdzone** na firmware 0.5 (slot 0 używa `HSQ`, a slot 7 przyjmuje i zwraca `LSQ`/`HSQ` z dokładnymi współczynnikami Q2.30) |
| Częstotliwość | 20–20 000 Hz, krok 1 Hz |
| Gain | −18…+12 dB (siatka 1/256 dB; apka wpisuje 0,1 dB) |
| Q | 0,1015625…10 (siatka 1/256; apka wpisuje 0,01) |
| Pre-gain | −128…0 dB (apka liczy go z krzywej i zapisuje) |
| Global gain | osobny offset DAC −18…0 dB, całe dB |
| Sloty | 0 = „Default” (fabryczny), 7 = „Custom” (zapisywalny) |
| Zachowanie apki | wybór presetu ustawia też pre-gain i global gain na 0; zapis = wybór slotu → pasma → pre-gain → save |

**Rozbieżność do zweryfikowania:** katalog chipu Walkplay (devicePEQ,
`usbDeviceConfig.js`) klasyfikuje PID `0x0123` jako *scheme 13*
(10 pasm, ±10 dB, pełne półki), a część tabel podaje 8 pasm z wyłączonym HS.
Oficjalna apka Moondrop mówi 8 pasm PK/LP/HP. Dlatego skrypt domyślnie czyta
8 pasm, a `--bands` pozwala sprawdzić, ile faktycznie odpowiada.

## 8. Klawisze konsumenckie (interface 4, hidraw1)

Deskryptor: report ID `0x03`, 4 bity (usage page Consumer):
`0xE9` Volume Increment, `0xEA` Volume Decrement, `0xCD` Play/Pause,
`0xCF` Mute. System widzi to jako klawiaturę (`event3`), więc klawisze
działają przez PipeWire/desktop bez żadnego sterownika.

## 9. Report 0x54 — kanał nieznany

Deskryptor interface 3 deklaruje **dwa** raporty vendor: `0x4B` (EQ/DSP,
używany przez publiczną apkę web) oraz `0x54` (input+output 63 B). Publiczna
aplikacja Moondrop (Custom EQ) i wszystkie znane implementacje open-source
używają wyłącznie `0x4B`. Przypuszczalnie `0x54` obsługuje funkcje mobilnej
aplikacji (HRTF/gaming, ENC, niskie opóźnienie) — **brak dokumentacji**,
nie należy zgadywać zapisu.

## 10. Pułapki przy implementacji

1. **CMD 0x09 jest współdzielone** — odczyt pasma i odczyt aktywnego slotu
   używają tego samego numeru; odpowiedź nie ma numeru korelacji. Trzeba
   opróżniać kolejkę przed każdym żądaniem i sprawdzać echo indeksu pasma,
   inaczej odpowiedzi przesuwają się o jeden.
2. **Odpowiedzi przychodzą asynchronicznie** — filtruj po `payload[1] == CMD`;
   na tym samym interfejsie mogą pojawić się inne raporty.
3. **Tempo** — patrz §5; przy zbyt szybkim zapisie część ramek ginie.
4. **`LEN`** — różne aplikacje wpisują różne wartości (24, 0, długość
   payloadu); urządzenie wydaje się to tolerować. Skrypt używa `0x18`.
5. **Slot** — zapis musi nieść aktualny slot (echo w odpowiedzi); przy
   preselektach fabrycznych bank jest tylko do odczytu.
6. **Flash** — każdy zapis zużywa pamięć; używaj `--dry-run` i nie zapisuj
   w pętli.
7. **Dostęp** — bez reguły udev (uaccess) `/dev/hidraw*` jest root-only;
   dotyczy też Chrome/WebHID i FreeDSP Studio.
