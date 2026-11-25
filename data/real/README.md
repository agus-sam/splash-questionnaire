# Real data

| File | Content |
|---|---|
| `curtailment_hourly_T5_T6.csv` | Hourly curtailed power (MW) of zones T5 and T6, 2025 and 2026, with a quality flag. Built from the operator file by `scripts/build_curtailment.py`. |
| `zones.csv` | Optional. Columns `plz_prefix`, `zone`. The longest matching prefix wins. Without it every pool maps to T5 and the user can choose the zone. See `zones.example.csv`. |

Check everything with `python scripts/validate_data.py`.

## Curtailment and model data (new)

Rebuild the curtailment file from a new operator download with `python scripts/build_curtailment.py <operator.csv> --observed-until 2026-11-22`.
The SPLASH data (weather, occupancy, bands, parameters) is in `data/splash/`. Calendars: `python scripts/build_calendars.py` (needs the `holidays` package, development only).
