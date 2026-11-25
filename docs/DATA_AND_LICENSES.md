# Data, licences and provenance

This page lists what has to be settled before the repository is published or the survey goes out. The code does not decide it.

| Item | Where | Status | Action |
|---|---|---|---|
| App code | repository | MIT (`LICENSE`) | none |
| SPLASH facility model v1.3 | `vendor/splash` | no licence file shipped by upstream; file hashes in `vendor/MANIFEST.sha256` (checked by a test) | add upstream licence and commit id, or confirm in writing that redistribution is allowed |
| SPLASH data (facility register, typology, weather) | `data/splash` | derived from the Bäderleben SH survey and PVGIS, see `data/splash/PROVENANCE.csv` | confirm redistribution rights; fill the PVGIS version in PROVENANCE.csv |
| Operator curtailment | `data/real` | hourly means of 15 minute operator values (2025 full, 2026 to 22 Nov) | confirm licence; confirm whether the signal is potential or realised curtailment (decides whether the avoided energy is real) |
| Zone map (postcode to T5/T6) | `data/real/zones.csv` | placeholder; unmapped postcodes use T6 | replace with the SPLASH assignment per postcode |
| Economic defaults | `data/parameters.yaml` | WACC, inflation, price changes marked illustrative or sourced per entry | project team signs off, then set `meta.status: validated` |
| KfW grant 522 / 422 | `data/parameters.yaml` | verified against the KfW page (30 %, caps, dates) | re-check at each release |

Reference values behind the German defaults (checked 23 Nov 2026): Destatis inflation 2.2 % (2025 average) and 2.8 % (October
2026); ECB target 2 %; BDEW average electricity price for small and medium industry 17.2 ct/kWh (2026 so far); UBA grid mix
344 g CO2/kWh for 2025.
