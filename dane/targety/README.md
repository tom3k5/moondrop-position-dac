# Targety (krzywe odniesienia)

Wszystkie dołączone poniżej krzywe docelowe pochodzą z katalogu [`targets/`](https://github.com/jaakkopasanen/AutoEq/tree/master/targets) repozytorium AutoEq (licencja **MIT**) i działają offline od pierwszego uruchomienia:

| Plik | Opis / rig |
|---|---|
| `AutoEq in-ear.csv` | Domyślny cel AutoEq dla słuchawek dokanałowych (711) |
| `Diffuse field 5128 -1dB per octave.csv` | Diffuse Field B&K 5128 z nachyleniem −1 dB/okt |
| `Diffuse field 5128.csv` | Diffuse Field B&K 5128 |
| `Diffuse field GRAS KEMAR.csv` | Diffuse Field GRAS KEMAR |
| `Harman in-ear 2019.csv` | Harman In-Ear 2019 (711) |
| `Harman over-ear 2018.csv` | Harman Over-Ear 2018 (GRAS) |
| `JM-1 with Harman filters.csv` | JM-1 z filtrami Harmana (B&K 5128) |
| `JM-1 with Harman treble filter.csv` | JM-1 z filtrem wysokich tonów Harmana (B&K 5128) |
| `zero.csv` | Płaski cel odniesienia (`0 dB`) |

## Odświeżanie (AutoEq, MIT, HTTPS bez REST API)

```bash
curl -sSL "https://raw.githubusercontent.com/jaakkopasanen/AutoEq/master/targets/Harman%20in-ear%202019.csv" \
  -o "dane/targety/Harman in-ear 2019.csv"
curl -sSL "https://raw.githubusercontent.com/jaakkopasanen/AutoEq/master/targets/JM-1%20with%20Harman%20filters.csv" \
  -o "dane/targety/JM-1 with Harman filters.csv"
```
