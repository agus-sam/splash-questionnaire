"""Tables for download: all heater sizes and years, and the hourly profile of one run."""
from __future__ import annotations

import numpy as np
import pandas as pd

from splash_calc.flexsplash import ALL_KEYS, parse_key
from splash_calc.scenarios import Result


def results_table(res: Result) -> pd.DataFrame:
    """One row per year and heater size, central case with the pessimistic and optimistic NPV."""
    rows = []
    for k in ALL_KEYS:
        year, size = parse_key(k)
        fo = res.cases["central"].flex[k]
        r = fo.res
        npv = [res.cases[c].flex[k].econ.npv_eur for c in ("pessimistic", "central", "optimistic")]
        rows.append({
            "year": year,
            "window_hours": r.window_hours,
            "hot_water_demand_mwh_th": round(res.context.splash.demand_dhw_mwh.get(year, 0.0), 2),
            "full_year": r.full_year,
            "heater_size_pct_of_design_load": int(round(size * 100)),
            "heater_kw_el": round(r.capacity_kw_el, 1),
            "absorbed_mwh_el": round(r.absorbed_kwh_el / 1000, 2),
            "displaced_heat_mwh_th": round(r.displaced_kwh_th / 1000, 2),
            "zone_curtailment_mwh": round(r.zone_available_kwh / 1000, 0),
            "share_of_zone_pct": round(r.share_of_zone * 100, 3),
            "hours_with_intake": r.absorption_hours,
            "load_while_absorbing_pct": round(r.utilisation * 100, 1),
            "investment_eur": round(fo.investment, 0),
            "net_saving_eur_y1": round(fo.econ.net_saving_eur_y1, 0),
            "npv_pessimistic_eur": round(npv[0], 0),
            "npv_central_eur": round(npv[1], 0),
            "npv_optimistic_eur": round(npv[2], 0),
            "break_even_price_eur_per_kwh": None if fo.econ.break_even_price is None else round(fo.econ.break_even_price, 4),
            "co2_t_y1_curtailed_zero": round(fo.co2.net_curtailed_zero_t_y1, 1),
            "co2_t_y1_grid_mix": round(fo.co2.net_t_y1, 1),
        })
    return pd.DataFrame(rows)


def hourly_table(res: Result, key: str) -> pd.DataFrame:
    r = res.central.flex[key].res
    idx = pd.date_range(r.start_local, periods=len(r.hourly_el), freq="h")
    dhw = res.context.splash.get(r.year, r.size).hourly_dhw_kw
    return pd.DataFrame({
        "time_local": idx.strftime("%Y-%m-%d %H:%M"),
        "zone_curtailment_kw": res.context.splash.get(r.year, r.size).hourly_available_kw.round(1),
        "heater_power_kw": r.hourly_el.round(2),
        "heat_demand_total_kw": r.hourly_demand.round(2),
        "heat_demand_hot_water_kw": (dhw if dhw is not None else np.zeros(len(r.hourly_el))).round(2),
        "stored_heat_kwh": r.hourly_soc.round(2),
        "conventional_heat_displaced_kw": r.hourly_displaced.round(2),
    })
