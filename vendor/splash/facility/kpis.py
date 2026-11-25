from __future__ import annotations

import numpy as np
import pandas as pd

from .model import FacilityModel
from .results import FacResult

MWH = 1.0e-3


def heat_out(r: FacResult) -> np.ndarray:
    return r.q_basin.sum(axis=0) + r.q_hall


def hall_el(fm: FacilityModel, r: FacResult) -> np.ndarray:
    """Electricity of the load block next to the basins: hall air plus hot water for bathers (if switched on)."""
    return r.q_hall / fm.cop_load() if fm.has_load else np.zeros(fm.T)


def dhw_heat(fm: FacilityModel, r: FacResult) -> np.ndarray:
    """Plant heat that goes to the hot water. The load block is served pro rata, so this is the block heat times the DHW share."""
    if fm.dhw is None:
        return np.zeros(fm.T)
    tot = fm.load_kw()
    return np.where(tot > 1e-12, r.q_hall * fm.dhw_kw() / np.maximum(tot, 1e-12), 0.0)


def load_split(fm: FacilityModel, r: FacResult, mode: str) -> dict[str, np.ndarray]:
    h = hall_el(fm, r)
    h_curt = h if mode in ("hysteresis_addon", "hysteresis_optimised") else np.zeros_like(h)
    return {"basins_curt": r.curt_el - h_curt, "hall_curt": h_curt, "basins_grid": r.grid_el - (h - h_curt), "hall_grid": h - h_curt}


def hourly(fm: FacilityModel, r: FacResult, avail_kw: np.ndarray | None = None) -> pd.DataFrame:
    d = {
        "basin_demand_kw": fm.basin_demand_kw(),
        "hall_demand_kw": fm.hall_kw(),
        "total_demand_kw": fm.total_demand_kw(),
        "p2h_heat_kw": heat_out(r),
        "p2h_heat_basins_kw": r.q_basin.sum(axis=0),
        "p2h_heat_hall_kw": r.q_hall,
        "conv_heat_kw": r.conv_heat,
        "conv_heat_basins_kw": r.conv_basin.sum(axis=0),
        "conv_heat_hall_kw": r.conv_hall,
        "p2h_el_kw": r.el,
        "grid_el_kw": r.grid_el,
        "curt_el_kw": r.curt_el,
        "hall_p2h_el_kw": hall_el(fm, r),
        "unmet_kw": r.short.sum(axis=0) + r.hall_short,
        "spill_kw": r.spill.sum(axis=0),
        "stored_heat_kwh": r.energy[:, :-1].sum(axis=0),
        "t_ext_c": fm.t_ext,
    }
    if fm.dhw is not None:
        d["dhw_visitors_per_h"] = fm.dhw.visitors_per_h
        d["dhw_demand_kw"] = fm.dhw_kw()
        d["dhw_p2h_heat_kw"] = dhw_heat(fm, r)
    if avail_kw is not None:
        d["zone_avail_kw"] = avail_kw
    return pd.DataFrame(d)


def technical_row(fm: FacilityModel, tech: str, scen: str, q_rated: float, el_rated: float, n_h: int) -> dict:
    bd, hd, dd = fm.basin_demand_kw(), fm.hall_kw(), fm.dhw_kw()
    act = np.any([b.active[:-1] > 0 for b in fm.basins], axis=0)
    dhw_cols = (
        {
            "annual_dhw_demand_mwh_th": dd.sum() * MWH,
            "dhw_visitors_per_year": float(fm.dhw.visitors_per_h.sum()) * 8760.0 / max(fm.T, 1),
            "dhw_visitors_from_data": int(fm.dhw.visitors_from_data),
            "dhw_tank_m3": fm.dhw.tank_m3,
            "dhw_tank_known": int(fm.dhw.tank_known),
            "dhw_peak_kw_th": float(dd.max()),
        }
        if fm.dhw is not None
        else {}
    )
    return {
        "facility_id": fm.facility_id,
        "facility_name": fm.name,
        "badtyp": fm.badtyp,
        "model_type": fm.model_type,
        "zone": fm.zone,
        "technology": tech,
        "plant_size": scen,
        "n_basins": fm.n_basins,
        "n_indoor": sum(b.environment == "indoor" for b in fm.basins),
        "n_outdoor": sum(b.environment == "outdoor" for b in fm.basins),
        "water_volume_m3": sum(b.volume_m3 for b in fm.basins),
        "water_area_m2": sum(b.area_m2 for b in fm.basins),
        "annual_basin_heat_demand_mwh_th": bd.sum() * MWH,
        "annual_hall_sensible_demand_mwh_th": hd.sum() * MWH,
        "annual_facility_heat_demand_mwh_th": (bd + hd + dd).sum() * MWH,
        "q_design_kw_th": fm.design["q_design_kw"],
        "p2h_rated_kw_th": q_rated,
        "p2h_el_capacity_kw_e": el_rated,
        "cop_design": fm.design["cop_design"],
        "max_thermal_demand_kw": float((bd + hd + dd).max()),
        "thermal_storage_capacity_mwh_th": sum(b.cap_kwh for b in fm.basins) * MWH,
        "max_demand_over_rated": float((bd + hd + dd).max() / q_rated) if q_rated > 0 else np.nan,
        "operating_hours_h": int(act.sum()),
        "hall_fan_el_mwh_e": (fm.hall.fan_kw.sum() * MWH if fm.hall is not None and fm.hall.fan_kw is not None else np.nan),
        "hall_latent_memo_mwh_th": (fm.hall.latent_diag_kw.sum() * MWH if fm.hall is not None else 0.0),
        "w_per_m3_diagnostic": q_rated * 1000.0 / max(sum(b.volume_m3 for b in fm.basins), 1e-9),
        "w_per_m2_diagnostic": q_rated * 1000.0 / max(sum(b.area_m2 for b in fm.basins), 1e-9),
        **dhw_cols,
    }


def flex_row(
    fm: FacilityModel,
    tech: str,
    scen: str,
    mode: str,
    r: FacResult,
    base: FacResult,
    avail_kw: np.ndarray,
    q_rated: float,
    econ=None,
    k_year: float = 1.0,
) -> dict:
    curt = r.curt_el
    on = curt > 1e-6
    heat = heat_out(r)
    cap_tot = sum(b.cap_kwh for b in fm.basins)
    head = cap_tot - r.energy[:, :-1].sum(axis=0)
    conv_b, conv_s = base.conv_heat.sum() * MWH, r.conv_heat.sum() * MWH
    p2h = heat.sum() * MWH
    row = {
        "facility_id": fm.facility_id,
        "zone": fm.zone,
        "technology": tech,
        "plant_size": scen,
        "mode": mode,
        "demand_mwh_th": fm.total_demand_kw().sum() * MWH,
        "p2h_heat_mwh_th": p2h,
        "conv_heat_mwh_th": conv_s,
        "conv_heat_displaced_mwh_th": conv_b - conv_s,
        "p2h_share_of_heat": p2h / max(p2h + conv_s, 1e-9),
        "available_zone_mwh_e": avail_kw.sum() * MWH,
        "absorbed_mwh_e": curt.sum() * MWH,
        "p2h_el_total_mwh_e": r.el.sum() * MWH,
        "grid_el_mwh_e": r.grid_el.sum() * MWH,
        "seasonal_cop": heat.sum() / r.el.sum() if r.el.sum() > 0 else np.nan,
        "curtailed_share_of_p2h_el": curt.sum() / max(r.el.sum(), 1e-9),
        "absorption_hours_h": int(on.sum()),
        "peak_absorbed_kw_e": float(curt.max()),
        "storage_headroom_mean_at_curtailment_hours_mwh_th": float(head[on].mean() * MWH) if on.any() else np.nan,
        "utilisation_during_curtailment_hours": float(heat[on].mean() / q_rated) if on.any() and q_rated > 0 else np.nan,
        "unabsorbed_single_facility_view_mwh_e": (avail_kw.sum() - curt.sum()) * MWH,
        "unmet_heat_mwh_th": (r.short.sum() + r.hall_short.sum()) * MWH,
        "spill_mwh_th": r.spill.sum() * MWH,
    }
    if econ is not None:
        from .econ import econ_row

        row.update(econ_row(econ, fm.facility_id, tech, mode, conv_s, p2h, r.grid_el.sum() * MWH, curt.sum() * MWH, q_rated, k_year, conv_b))
    return row


def monthly(fm: FacilityModel, r: FacResult, months: np.ndarray) -> pd.DataFrame:
    df = hourly(fm, r)
    df["month"] = months
    g = df.groupby("month")
    out = pd.DataFrame(
        {
            "t_ext_mean_c": g["t_ext_c"].mean(),
            "thermal_demand_mwh_th": g["total_demand_kw"].sum() * MWH,
            "basin_demand_mwh_th": g["basin_demand_kw"].sum() * MWH,
            "hall_demand_mwh_th": g["hall_demand_kw"].sum() * MWH,
            "p2h_heat_mwh_th": g["p2h_heat_kw"].sum() * MWH,
            "conv_heat_mwh_th": g["conv_heat_kw"].sum() * MWH,
            "p2h_el_mwh_e": g["p2h_el_kw"].sum() * MWH,
            "grid_el_mwh_e": g["grid_el_kw"].sum() * MWH,
            "curtailed_absorbed_mwh_e": g["curt_el_kw"].sum() * MWH,
            "p2h_operating_hours_h": g["p2h_heat_kw"].apply(lambda x: int((x > 1e-6).sum())),
        }
    )
    if fm.dhw is not None:
        out["dhw_demand_mwh_th"] = g["dhw_demand_kw"].sum() * MWH
        out["dhw_p2h_heat_mwh_th"] = g["dhw_p2h_heat_kw"].sum() * MWH
    out.insert(0, "facility_id", fm.facility_id)
    return out


def month_flags(mt: pd.DataFrame) -> dict:
    return {
        "coldest_month": int(mt["t_ext_mean_c"].idxmin()),
        "warmest_month": int(mt["t_ext_mean_c"].idxmax()),
        "month_max_heat_demand": int(mt["thermal_demand_mwh_th"].idxmax()),
        "month_max_curtailed_absorption": int(mt["curtailed_absorbed_mwh_e"].idxmax()) if mt["curtailed_absorbed_mwh_e"].max() > 0 else None,
    }


def zone_hourly(fms: list[FacilityModel], res: dict[int, FacResult], avail_kw: np.ndarray) -> pd.DataFrame:
    heat = sum(heat_out(res[f.facility_id]) for f in fms)
    conv = sum(res[f.facility_id].conv_heat for f in fms)
    curt = sum(res[f.facility_id].curt_el for f in fms)
    grid = sum(res[f.facility_id].grid_el for f in fms)
    hall = sum(hall_el(f, res[f.facility_id]) for f in fms)
    dhw_cols = (
        {"dhw_demand_kw_th": sum(f.dhw_kw() for f in fms), "dhw_p2h_heat_kw_th": sum(dhw_heat(f, res[f.facility_id]) for f in fms)}
        if any(f.dhw is not None for f in fms)
        else {}
    )
    return pd.DataFrame(
        {
            "hall_p2h_el_kw_e": hall,
            "hall_p2h_heat_kw_th": sum(res[f.facility_id].q_hall for f in fms),
            "available_kw_e": avail_kw,
            "absorbed_kw_e": curt,
            "remaining_kw_e": avail_kw - curt,
            "grid_el_kw_e": grid,
            "p2h_el_kw_e": grid + curt,
            "p2h_heat_kw_th": heat,
            "conv_heat_kw_th": conv,
            "demand_kw_th": sum(f.total_demand_kw() for f in fms),
            "unmet_kw_th": sum(res[f.facility_id].short.sum(axis=0) + res[f.facility_id].hall_short for f in fms),
            **dhw_cols,
        }
    )


def aggregate(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    out = None
    for f in frames.values():
        out = f.copy() if out is None else out.add(f)
    return out


def period_table(df: pd.DataFrame, index_local, freq: str) -> pd.DataFrame:
    d = df.copy()
    from ..preprocessing import report_dates

    day = report_dates(index_local)
    key = {"D": day, "M": day.to_period("M"), "A": day.year}[freq]
    t = d.groupby(key).sum() * MWH
    t.columns = [c.replace("_kw_e", "_mwh_e").replace("_kw_th", "_mwh_th") for c in t.columns]
    t["hours"] = d.groupby(key).size()
    t["seasonal_cop"] = t["p2h_heat_mwh_th"] / t["p2h_el_mwh_e"].where(t["p2h_el_mwh_e"] > 0)
    return t
