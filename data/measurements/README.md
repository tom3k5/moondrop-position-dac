# Measurements (Data Sources)

## MOONDROP Position

| File | Source | Notes |
|---|---|---|
| `Moondrop Position (B&K 5128).csv` | Derived from the manufacturer's public specification (`POSITION (Original)`, `60 dB @ 500 Hz`, B&K 5128) | AutoEq `frequency,raw` format, 1/48-octave grid (`20 Hz – 20 kHz`) |

## AutoEq Model Catalog (Index Without Third-Party Curve Redistribution)

The repository bundles the model and source index in `data/autoeq-catalog.json` so the catalog list is available from first launch. Third-party measurement CSVs (`measurements/<source>/data/<type>/*.csv` from `oratory1990`, `crinacle`, `Rtings`, `Innerfidelity`, and `squig.link` contributors) do not carry a uniform redistribution grant in AutoEq for binary packages, so the application fetches each selected curve on demand over HTTPS and caches it locally.
