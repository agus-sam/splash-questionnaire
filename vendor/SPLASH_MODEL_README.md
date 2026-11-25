# SPLASH

SPLASH (Swimming Pools as Thermal Storage for Power-to-Heat) is an hourly model of the Schleswig-Holstein public swimming pools as thermal storage for curtailed electricity. It computes how much curtailed wind power the pools can absorb as heat if their water is allowed to move inside a temperature band, and what this does to heat supply, electricity use, cost and CO2.

Version 1.3.0 adds optional hot water for bathers (showers), proportional to the number of visitors (`facility.dhw`, off by default, `docs/MODEL.md` section 3b). Version 1.2.0 was v1.1.0 inputs with the user-supplied temperature bands in `data/config/bands.csv`. The bundled data package contains synthetic and assumed inputs. Results are for method development until the inputs are replaced (see `docs/DATA.md`).

## Model in short

The hierarchy is basin, facility (136), curtailment zone (T5 with 40 facilities, T6 with 96) and Schleswig-Holstein (T5 plus T6). Every basin is a separate thermal storage. Its heat loss follows a physical model (Delgado Marin and Garcia-Cascales for indoor basins, Buscemi et al. for outdoor basins) and is linearised between the lower and upper temperature limit. A facility has one shared power-to-heat plant for all of its basins and its hall. The model runs a full year at hourly resolution.

Scenarios (`facility.zone_modes`), each compared with the baseline, which is the current heating system holding the lower temperature limit:

| Scenario | Meaning |
|---|---|
| `hysteresis_addon` | The new technology is added to the current system and runs on curtailed power only. It charges the basins to the upper limit while curtailed power exists. Afterwards the basins cool to the lower limit and the current system takes over. |
| `hysteresis_replace` | The new technology replaces the current system. Grid electricity holds the lower limit, curtailed power charges the basins. |
| `hysteresis_optimised` | The add-on with a plant size per facility from an investment model (oemof.solph, HiGHS). A size of zero means no investment. |

Technologies (`facility.technologies`): `heat_pump` (hourly COP from the Carnot fraction, the sink temperature and the outdoor air) and `resistive` (constant efficiency `system.p2h_efficiency`, default 1). Plant sizes are HP75, HP100 and HP125, as shares of the coincident design load. HP100 is the default.

The operation is always a rule (explicit in time). The optimiser only chooses the plant size of `hysteresis_optimised`. The equations are in `docs/MODEL.md`.

## Installation

    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt

Python 3.10 or newer. The optimised scenario needs `oemof.solph`, `pyomo` and `highspy`.

## Run

    python3 run_splash.py
    python3 run_splash.py --tech resistive --scenarios hysteresis_addon
    python3 run_splash.py --quick
    python3 run_splash.py --set run.time_window.start=2026-03-01 --set run.time_window.end=2026-03-31
    python3 run_splash.py --set output.figures=false

All options are in `settings.yaml` and documented in `docs/SETTINGS.md`. `--set key=value` overrides any option. `--quick` runs one week.

Results are written to `results/<run_id>/`:

    settings_used.yaml, settings_resolved.json, run_info.json
    tables/    facility, zone and Schleswig-Holstein tables, verification tables, input provenance
    figures/   1_schleswig_holstein/ and 2_facility/

`docs/OUTPUTS.md` lists every table and figure.

## Data

`data/` holds the input package: clean master tables, hourly inputs, configuration tables, a provenance table and a register of every real, assumed and synthetic input (`data/SYNTHETIC_DATA_REGISTER.csv`). The model fails closed: a missing or unknown flag counts as synthetic and the synthetic inputs are listed in every result. See `docs/DATA.md`.

## Tests

    python3 -m pytest

The default tests cover the physics, the data package, the settings and the facility model with the resistive add-on. Tests of the heat pump, replacement and optimised scenarios are marked `extended` and run with `python3 -m pytest -m extended` (about 40 s).

## Layout

    src/splash/
      config.py  data_loader.py  preprocessing.py  builder.py  economics.py  viz.py
      physics/   properties, indoor_delgado, outdoor_buscemi, hall_air, pool_models
      facility/  model, rules, zone, sizing, kpis, econ, verification, storage, pipeline, figures, demand, demand_plots, results, viz_helpers, dhw
    data/  docs/  tests/  settings.yaml  run_splash.py

## Documentation

`docs/MODEL.md` equations and sources. `docs/SETTINGS.md` options. `docs/DATA.md` data package. `docs/OUTPUTS.md` tables and figures. `docs/AUDIT.md` scientific audit and verification of this release.
