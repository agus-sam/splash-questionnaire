"""Heat pump scenario: hourly COP, bivalent sizing, electricity and fuel savings."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .params import Params
from .profiles import LEVELS


def cop_series(t_source_c: np.ndarray | float, t_sink_c: float, params: Params) -> np.ndarray:
    """COP = eta_c * T_sink / max(T_sink - T_source, min_lift), clipped to [cop_min, cop_max].

    Temperatures enter in kelvin. The minimum lift avoids unrealistic values when
    source and sink are close.
    """
    ts = np.asarray(t_source_c, dtype=float)
    lift = np.maximum(t_sink_c - ts, float(params.get("min_lift_k")))
    cop = float(params.get("eta_carnot")) * (t_sink_c + 273.15) / lift
    return np.clip(cop, float(params.get("cop_min")), float(params.get("cop_max")))


def source_temperature(t_air: np.ndarray, source: str, params: Params) -> np.ndarray:
    if source == "air":
        return t_air
    temps = params.central("source_temps_c")
    return np.full_like(t_air, float(temps.get(source, temps["ground"])), dtype=float)


@dataclass
class HeatPumpResult:
    capacity_kw_th: float
    capacity_auto_kw_th: float
    heat_hp_kwh: float                  # useful heat delivered by the heat pump
    elec_kwh: float
    scop: float
    coverage: float                     # share of the useful heat covered by the heat pump
    fuel_saved_kwh: dict[str, float]    # final energy saved per carrier
    served_levels: tuple[str, ...]
    hp_heat_hourly: np.ndarray
    hp_elec_hourly: np.ndarray
    # rule-based operation (SPLASH hysteresis rule): grid electricity holds T_min, curtailed power charges to T_max
    dispatch: str = "conventional"            # conventional | rule
    elec_grid_kwh: float = 0.0
    elec_curtailed_kwh: float = 0.0
    heat_curtailed_kwh: float = 0.0           # heat charged into the pool with curtailed power
    unmet_kwh_th: float = 0.0                 # demand the heat pump could not cover (existing system covers it)
    hp_curt_hourly: np.ndarray | None = None  # kW electric from curtailment
    hp_grid_hourly: np.ndarray | None = None  # kW electric from the grid
    hp_curt_heat_hourly: np.ndarray | None = None  # kW heat charged with curtailed power
    hp_soc_hourly: np.ndarray | None = None   # kWh stored above the lower limit
    hp_avail_hourly: np.ndarray | None = None # kW curtailed power available in the zone
    e_max_kwh: float = 0.0
    start_local: object = None


def run_heat_pump(
    levels: dict[str, np.ndarray],
    t_air: np.ndarray,
    q_use_kwh: float,
    e_fuel_kwh: dict[str, float],
    source: str,
    params: Params,
    capacity_kw: float | None = None,
    served: tuple[str, ...] | None = None,
) -> HeatPumpResult:
    served = tuple(served or params.central("hp_levels_default"))
    served = tuple(lv for lv in LEVELS if lv in served)
    n = len(t_air)
    load = np.zeros(n)
    for lv in served:
        load += levels[lv]

    positive = load[load > 0]
    q = float(params.get("hp_sizing_quantile"))
    auto = float(np.quantile(positive, q)) if positive.size else 0.0
    cap = float(capacity_kw) if capacity_kw and capacity_kw > 0 else auto

    with np.errstate(divide="ignore", invalid="ignore"):
        f = np.where(load > 0, np.minimum(1.0, cap / np.where(load > 0, load, 1.0)), 0.0)

    t_src = source_temperature(t_air, source, params)
    sink = params.central("sink_temps_c")
    heat = np.zeros(n)
    elec = np.zeros(n)
    for lv in served:
        h = levels[lv] * f
        heat += h
        elec += h / cop_series(t_src, float(sink[lv]), params)

    heat_total = float(heat.sum())
    elec_total = float(elec.sum())
    coverage = heat_total / q_use_kwh if q_use_kwh > 0 else 0.0
    coverage = min(coverage, 1.0)

    saved = {c: v * coverage for c, v in e_fuel_kwh.items()}
    return HeatPumpResult(
        capacity_kw_th=cap,
        capacity_auto_kw_th=auto,
        heat_hp_kwh=heat_total,
        elec_kwh=elec_total,
        scop=heat_total / elec_total if elec_total > 0 else 0.0,
        coverage=coverage,
        fuel_saved_kwh=saved,
        served_levels=served,
        hp_heat_hourly=heat,
        hp_elec_hourly=elec,
    )
