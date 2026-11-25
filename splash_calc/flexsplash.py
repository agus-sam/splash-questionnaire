"""Flexible heating KPIs from the SPLASH model run: one outcome per year and heater size."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .economics import Co2, Economics, co2, economics, investment_flex
from .params import Params
from .splash_engine import SIZES, YEARS, SizeResult, SplashRun


def flex_key(year: int, size: float) -> str:
    return f"{int(year)}_{int(round(size * 100))}"


def parse_key(key: str) -> tuple[int, float]:
    y, s = key.split("_")
    return int(y), int(s) / 100.0


ALL_KEYS = tuple(flex_key(y, s) for y in YEARS for s in SIZES)


@dataclass
class SplashFlex:
    """Result of one model run. Field names follow what the interface reads."""

    key: str
    year: int
    size: float
    capacity_kw_th: float
    capacity_kw_el: float
    absorbed_kwh_el: float
    displaced_kwh_th: float
    coverage: float
    fuel_saved_kwh: dict[str, float]
    curtail_hours: int              # hours with curtailed power in the zone during the window
    absorption_hours: int           # hours in which the heater took power
    window_hours: int
    full_year: bool
    zone_available_kwh: float
    share_of_zone: float
    utilisation: float
    peak_kw_el: float
    e_max_kwh: float                # storage capacity of all basins within their bands
    band_k: float                   # volume-weighted band width
    demand_kwh_th: float            # model demand of basins and hall in the window
    unmet_kwh_th: float
    above_threshold: bool
    flex_threshold_kw: float
    hourly_el: np.ndarray
    hourly_available: np.ndarray
    hourly_soc: np.ndarray
    hourly_demand: np.ndarray
    hourly_displaced: np.ndarray
    start_local: object
    max_residual: float = 0.0
    heat_kwh_th: float = 0.0        # heat delivered by the heater
    spill_kwh_th: float = 0.0       # heat above the upper limit that could not be stored
    hourly_available_kw: np.ndarray | None = None   # continuous curtailed power in the zone (kW)


@dataclass
class FlexOutcome:
    res: SplashFlex
    investment: float
    om: float
    price_eff: float
    econ: Economics
    co2: Co2


def build_flex(sr: SizeResult, run: SplashRun, e_fuel_kwh: dict[str, float], q_use_kwh: float, params: Params, eta: float) -> SplashFlex:
    heat_kwh = sr.p2h_heat_mwh * 1000.0
    displaced = sr.displaced_mwh_th * 1000.0
    window_demand = sr.demand_mwh_th * 1000.0
    coverage = min(displaced / window_demand, 1.0) if window_demand > 0 else 0.0
    saved_share = min(displaced / q_use_kwh, 1.0) if q_use_kwh > 0 else 0.0
    vol_w = [(m.volume_m3, m.t_max - m.t_min) for m in run.basins]
    tot_v = sum(v for v, _ in vol_w) or 1.0
    band = sum(v * w for v, w in vol_w) / tot_v
    cap_el = sr.q_rated_kw / eta
    thr = float(params.central("flex_threshold_kw"))
    return SplashFlex(
        key=flex_key(sr.year, sr.size),
        year=sr.year,
        size=sr.size,
        capacity_kw_th=sr.q_rated_kw,
        capacity_kw_el=cap_el,
        absorbed_kwh_el=heat_kwh / eta,
        displaced_kwh_th=displaced,
        coverage=coverage,
        fuel_saved_kwh={c: v * saved_share for c, v in e_fuel_kwh.items()},
        curtail_hours=int((sr.hourly_available_kw > 0).sum()),
        absorption_hours=sr.absorption_hours,
        window_hours=sr.window_hours,
        full_year=sr.full_year,
        zone_available_kwh=sr.zone_available_mwh * 1000.0,
        share_of_zone=sr.share_of_zone,
        utilisation=sr.utilisation,
        peak_kw_el=sr.peak_kw,
        e_max_kwh=run.storage_kwh,
        band_k=band,
        demand_kwh_th=sr.demand_mwh_th * 1000.0,
        unmet_kwh_th=sr.unmet_mwh_th * 1000.0,
        above_threshold=cap_el >= thr,
        flex_threshold_kw=thr,
        hourly_el=sr.hourly_el_kw,
        hourly_available=sr.hourly_available_kw > 0,
        hourly_available_kw=sr.hourly_available_kw,
        hourly_soc=sr.hourly_soc_kwh,
        hourly_demand=sr.hourly_demand_kw,
        hourly_displaced=sr.hourly_displaced_kw,
        start_local=sr.start_local,
        max_residual=sr.max_residual,
        heat_kwh_th=heat_kwh,
        spill_kwh_th=sr.spill_mwh_th * 1000.0,
    )


def flex_outcomes(
    run: SplashRun,
    e_fuel_kwh: dict[str, float],
    q_use_kwh: float,
    fuel_prices: dict[str, float],
    p_c: float,
    params: Params,
) -> dict[str, FlexOutcome]:
    eta = float(params.get("heater_efficiency"))
    out: dict[str, FlexOutcome] = {}
    for sr in run.results.values():
        fx = build_flex(sr, run, e_fuel_kwh, q_use_kwh, params, eta)
        inv, om = investment_flex("heater", fx.capacity_kw_th, fx.capacity_kw_el, params)
        ec = economics(inv, 0.0, fx.fuel_saved_kwh, fuel_prices, fx.absorbed_kwh_el, p_c, om, params)
        out[fx.key] = FlexOutcome(fx, inv, om, p_c, ec, co2(fx.fuel_saved_kwh, fx.absorbed_kwh_el, params, curtailed_share=1.0))
    return out
