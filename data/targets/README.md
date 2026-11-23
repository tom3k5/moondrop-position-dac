# Targets (Reference Curves)

All bundled target curves below come from the [`targets/`](https://github.com/jaakkopasanen/AutoEq/tree/master/targets) directory of the AutoEq repository (**MIT** license) and work offline from first launch:

| File | Description / Rig |
|---|---|
| `AutoEq in-ear.csv` | Default AutoEq in-ear target (711) |
| `Diffuse field 5128 -1dB per octave.csv` | Diffuse Field B&K 5128 with −1 dB/octave tilt |
| `Diffuse field 5128.csv` | Diffuse Field B&K 5128 |
| `Diffuse field GRAS KEMAR.csv` | Diffuse Field GRAS KEMAR |
| `Harman in-ear 2019.csv` | Harman In-Ear 2019 (711) |
| `Harman over-ear 2018.csv` | Harman Over-Ear 2018 (GRAS) |
| `JM-1 with Harman filters.csv` | JM-1 with Harman filters (B&K 5128) |
| `JM-1 with Harman treble filter.csv` | JM-1 with Harman treble filter (B&K 5128) |
| `zero.csv` | Flat reference target (`0 dB`) |

## Refreshing (AutoEq, MIT, HTTPS Without REST API)

```bash
curl -sSL "https://raw.githubusercontent.com/jaakkopasanen/AutoEq/master/targets/Harman%20in-ear%202019.csv" \
  -o "data/targets/Harman in-ear 2019.csv"
curl -sSL "https://raw.githubusercontent.com/jaakkopasanen/AutoEq/master/targets/JM-1%20with%20Harman%20filters.csv" \
  -o "data/targets/JM-1 with Harman filters.csv"
```
