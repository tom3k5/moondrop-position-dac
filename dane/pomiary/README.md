# Pomiary (źródła danych)

## MOONDROP Position

| Plik | Źródło | Uwagi |
|---|---|---|
| `Moondrop Position (B&K 5128).csv` | Krzywa opracowana na podstawie publicznych materiałów producenta (`POSITION (Original)`, `60 dB @ 500 Hz`, B&K 5128) | Format AutoEq `frequency,raw`, siatka 1/48 oktawy (`20 Hz – 20 kHz`) |

## Katalog modeli AutoEq (indeks bez dystrybucji krzywych stron trzecich)

Repozytorium dołącza indeks nazw modeli i źródeł w `dane/autoeq-catalog.json`, dzięki czemu lista jest dostępna od pierwszego uruchomienia. Pliki CSV poszczególnych pomiarów stron trzecich (`measurements/<źródło>/data/<typ>/*.csv` od `oratory1990`, `crinacle`, `Rtings`, `Innerfidelity` i autorów `squig.link`) nie mają w AutoEq jednolitego potwierdzenia praw do dalszej dystrybucji w paczkach binarnych, więc aplikacja pobiera wybraną krzywą na żądanie użytkownika przez HTTPS i zachowuje ją w pamięci podręcznej.
