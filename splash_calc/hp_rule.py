"""Heat pump operated with the SPLASH rule logic.

Same hourly pool model, same temperature band and the same hysteresis rule as the resistive heater, with one
addition that covers the baseline demand: the heat pump runs on normal grid electricity and holds the pool at its
lower limit T_min (supply "replace"). In hours with curtailed power in the zone it charges the pool up to the upper
limit T_max with that power. The COP is hourly from the heat pump parameters (source, sink, Carnot fraction), the same
as in ``heatpump.cop_series``. Demand the heat pump cannot cover (capacity) stays with the existing system.
"""
from __future__ import annotations

import dataclasses

import numpy as np

from .heatpump import HeatPumpResult, cop_series, source_temperature
from .params import Params
from .splash_engine import FAC_ID, SplashRun, simulate_rule

SERVED = ("pool_water", "hall_air", "dhw")


def available(run: SplashRun) -> bool:
    return bool(run.bundle) and run.bundle.get("fm") is not None


def _cop_key(source: str, params: Params, capacity_kw: float | None) -> tuple:
    names = ("eta_carnot", "cop_min", "cop_max", "min_lift_k", "hp_sizing_quantile")
    sink = params.central("sink_temps_c")
    src = params.central("source_temps_c")
    return (source, capacity_kw or 0.0, tuple(float(params.get(n)) for n in names),
            tuple(sorted((k, float(v)) for k, v in sink.items())), tuple(sorted((k, float(v)) for k, v in src.items())))


def run_heat_pump_rule(
    run: SplashRun,
    e_fuel_kwh: dict[str, float],
    source: str,
    params: Params,
    capacity_kw: float | None = None,
) -> HeatPumpResult:
    """Simulation is memoised on the COP-relevant inputs: tornado runs that change only prices reuse it."""
    memo = run.bundle.setdefault("memo", {})
    key = _cop_key(source, params, capacity_kw)
    sim = memo.get(key)
    if sim is None:
        sim = _simulate(run, source, params, capacity_kw)
        memo[key] = sim
    cap, auto, r, demand = sim
    return _result(run, e_fuel_kwh, cap, auto, r, demand)


def _simulate(run: SplashRun, source: str, params: Params, capacity_kw: float | None):
    b = run.bundle
    fm = b["fm"]
    avail = np.asarray(b["avail"], float)
    t_src = source_temperature(np.asarray(fm.t_ext, float), source, params)
    sink = params.central("sink_temps_c")
    circuits = {}
    for name in fm.circuits:
        lv = "hall_air" if name == "hall_coil" else ("dhw" if name == fm.dhw_circuit else "pool_water")
        circuits[name] = cop_series(t_src, float(sink[lv]), params)
    fmh = dataclasses.replace(fm, circuits=circuits, flags=dict(fm.flags))

    demand = np.asarray(fm.total_demand_kw(), float)
    positive = demand[demand > 0]
    auto = float(np.quantile(positive, float(params.get("hp_sizing_quantile")))) if positive.size else 0.0
    cap = float(capacity_kw) if capacity_kw and capacity_kw > 0 else auto

    r = simulate_rule([fmh], {FAC_ID: cap}, avail, "hysteresis", supply="replace", depth=b["depth"],
                      hold_margin_k=b["hold"], priority=b["priority"])[FAC_ID]
    return cap, auto, r, demand


def _result(run: SplashRun, e_fuel_kwh: dict[str, float], cap: float, auto: float, r, demand: np.ndarray) -> HeatPumpResult:
    b = run.bundle
    fm = b["fm"]
    avail = np.asarray(b["avail"], float)
    heat_h = r.q_basin.sum(axis=0) + r.q_hall
    curt_el = np.asarray(r.curt_el, float)
    grid_el = np.asarray(r.grid_el, float)
    el_total = float(curt_el.sum() + grid_el.sum())
    unmet = float(r.short.sum() + r.hall_short.sum())
    dem_total = float(demand.sum())
    coverage = min(max(1.0 - unmet / dem_total, 0.0), 1.0) if dem_total > 0 else 0.0
    # heat charged with curtailed power, share of the delivered heat by electricity source
    heat_total = float(heat_h.sum())
    cop_h = np.where(curt_el + grid_el > 1e-12, heat_h / np.maximum(curt_el + grid_el, 1e-12), 0.0)
    heat_curt_h = curt_el * cop_h
    heat_curt = float(heat_curt_h.sum())
    soc = r.energy[:, :-1].sum(axis=0)
    return HeatPumpResult(
        capacity_kw_th=cap,
        capacity_auto_kw_th=auto,
        heat_hp_kwh=heat_total,
        elec_kwh=el_total,
        scop=heat_total / el_total if el_total > 0 else 0.0,
        coverage=coverage,
        fuel_saved_kwh={c: v * coverage for c, v in e_fuel_kwh.items()},
        served_levels=SERVED,
        hp_heat_hourly=heat_h,
        hp_elec_hourly=curt_el + grid_el,
        dispatch="rule",
        elec_grid_kwh=float(grid_el.sum()),
        elec_curtailed_kwh=float(curt_el.sum()),
        heat_curtailed_kwh=heat_curt,
        unmet_kwh_th=unmet,
        hp_curt_hourly=curt_el,
        hp_grid_hourly=grid_el,
        hp_curt_heat_hourly=heat_curt_h,
        hp_soc_hourly=soc,
        hp_avail_hourly=avail,
        e_max_kwh=float(sum(bm.cap_kwh for bm in fm.basins)),
        start_local=b["start_local"],
    )
