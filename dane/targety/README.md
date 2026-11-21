# Targety (krzywe odniesienia)

| Plik | Źródło | Licencja / uwagi |
|---|---|---|
| `Harman in-ear 2019.csv` | [AutoEq `targets/`](https://github.com/jaakkopasanen/AutoEq/tree/master/targets) | MIT; `frequency,raw` (711) |
| `JM-1 with Harman filters.csv` | [AutoEq `targets/`](https://github.com/jaakkopasanen/AutoEq/tree/master/targets) | MIT; `frequency,raw` (B&K 5128) |

## Odświeżanie (AutoEq, MIT)

```bash
gh api repos/jaakkopasanen/AutoEq/contents/targets/Harman%20in-ear%202019.csv \
  -H "Accept: application/vnd.github.raw+json" > "dane/targety/Harman in-ear 2019.csv"
gh api repos/jaakkopasanen/AutoEq/contents/targets/JM-1%20with%20Harman%20filters.csv \
  -H "Accept: application/vnd.github.raw+json" > "dane/targety/JM-1 with Harman filters.csv"
```
