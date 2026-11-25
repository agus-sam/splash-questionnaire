from __future__ import annotations

import numpy as np
import pandas as pd

from .model import FacilityModel
from .results import FacResult


def facility_checks(fm: FacilityModel, r: FacResult, q_rated: float, depth: float = 1.0, mode: str = "hysteresis_replace", avail_kw=None) -> dict:
    res_basin = 0.0
    bound_viol = 0.0
    hp_waste = 0.0
    for i, b in enumerate(fm.basins):
        e = r.energy[i]
        lhs = e[1:] - e[:-1]
        rhs = -b.rate * e[:-1] + r.q_basin[i] + r.conv_basin[i] + r.short[i] - b.a_kw - r.spill[i]
        res_basin = max(res_basin, float(np.abs(lhs - rhs).max()))
        hi = depth * b.cap_kwh * b.active
        bound_viol = max(bound_viol, float(np.maximum(e - hi - 1e-6, 0).max()), float(np.maximum(-e - 1e-6, 0).max()))
        gain = np.maximum(-b.a_kw, 0.0)
        closing = (b.active[1:] < b.active[:-1]) * depth * b.cap_kwh

        hp_waste = max(hp_waste, float(np.maximum(r.spill[i] - gain - closing - 1e-6, 0).max()))
    cap_t = q_rated * fm.avail
    cap_viol = float(np.maximum(r.q_basin.sum(axis=0) + r.q_hall - cap_t - 1e-6, 0).max())
    el_ref = fm.electricity_for(r.q_basin, r.q_hall)
    el_res = float(np.abs(r.grid_el + r.curt_el - el_ref).max())
    hall_res = float(np.abs(r.q_hall + r.conv_hall + r.hall_short - fm.load_kw()).max())

    idle = float((r.el[(r.q_basin.sum(axis=0) + r.q_hall) <= 1e-9]).sum())

    no_grid = float(r.grid_el.max()) if mode in ("baseline", "hysteresis_addon", "hysteresis_optimised") else 0.0
    off = (np.asarray(avail_kw) <= 1e-9) if avail_kw is not None else np.zeros(fm.T, dtype=bool)
    p2h_off = (
        float((r.q_basin.sum(axis=0) + r.q_hall)[off].max())
        if mode in ("baseline", "hysteresis_addon", "hysteresis_optimised") and off.any()
        else 0.0
    )
    return {
        "facility_id": fm.facility_id,
        "basin_balance_resid_kw": res_basin,
        "bounds_violation_kwh": bound_viol,
        "capacity_violation_kw": cap_viol,
        "electricity_resid_kw": el_res,
        "hall_balance_resid_kw": hall_res,
        "p2h_heat_wasted_kw": hp_waste,
        "idle_electricity_kwh": idle,
        "grid_electricity_where_none_allowed_kw": no_grid,
        "p2h_heat_without_curtailment_kw": p2h_off,
        "storage_change_kwh": float(r.energy[:, -1].sum() - r.energy[:, 0].sum()),
    }


def zone_checks(zone_df: pd.DataFrame) -> dict:
    return {
        "max_absorbed_over_available_kw": float((zone_df["absorbed_kw_e"] - zone_df["available_kw_e"]).max()),
        "min_remaining_kw": float(zone_df["remaining_kw_e"].min()),
    }


def linearisation_check(fm: FacilityModel, r: FacResult) -> pd.DataFrame:
    rows = []
    for i, b in enumerate(fm.basins):
        e = r.energy[i, :-1]
        act = b.active[:-1] > 0
        if not act.any():
            continue
        temp = np.where(act, b.t_min + e / b.c_kwh_per_k, b.t_min)
        nl = b.phys.net_loss_kw_per_m2(temp, b.t_air) * b.area_m2 * b.active[:-1]
        lin = b.a_kw + b.rate * e
        d = (lin - nl)[act]
        ref_mean = max(float(np.abs(nl[act]).mean()), 1e-6)
        ref_peak = max(float(np.abs(nl[act]).max()), 1e-6)
        rows.append(
            {
                "facility_id": fm.facility_id,
                "basin_id": b.basin_id,
                "environment": b.environment,
                "mean_dev_kw": float(d.mean()),
                "max_abs_dev_kw": float(np.abs(d).max()),
                "mean_dev_pct_of_mean_abs_loss": float(d.mean() / ref_mean * 100),
                "max_abs_dev_pct_of_peak_loss": float(np.abs(d).max() / ref_peak * 100),
                "temp_min_c": float(temp[act].min()),
                "temp_max_c": float(temp[act].max()),
                "within_band": bool(temp[act].min() >= b.t_min - 1e-6 and temp[act].max() <= b.t_max + 1e-6),
            }
        )
    return pd.DataFrame(rows)
