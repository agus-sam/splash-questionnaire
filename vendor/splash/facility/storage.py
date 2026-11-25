from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import OPT_SIZE
from .zone import BASE

MWH = 1.0e-3
COMP_IN = {"evaporation": "evap", "convection": "conv", "radiation": "rad", "conduction": "cond", "make-up water": "renov"}
COMP_OUT = {"evaporation": "eva", "convection": "conv", "radiation": "rad", "make-up water": "re"}
COMPS = ("evaporation", "convection", "radiation", "conduction", "make-up water")


def _size(R, mode) -> str:
    return OPT_SIZE if mode == "hysteresis_optimised" else R["primary"]


def _res(R, tech, mode, zone, fid):
    key = (BASE, BASE, zone, "baseline") if mode == "baseline" else (tech, _size(R, mode), zone, mode)
    return R["results"][key][fid]


def facility_storage(R, tech: str, mode: str) -> pd.DataFrame:
    t = R["tech"]
    t = t[(t.technology == tech) & (t.plant_size == _size(R, mode))].set_index("facility_id")
    f = R["flex"]
    f = f[(f.technology == tech) & (f["mode"] == mode) & (f.plant_size == _size(R, mode))].set_index("facility_id")
    rows = []
    for fm in R["fms"].values():
        vol = sum(b.volume_m3 for b in fm.basins)
        c_k = sum(b.c_kwh_per_k for b in fm.basins)
        cap = sum(b.cap_kwh for b in fm.basins)
        c_avg = sum(b.c_kwh_per_k * float(np.mean(b.active[:-1])) for b in fm.basins)
        rated, el = float(t.loc[fm.facility_id, "p2h_rated_kw_th"]), float(t.loc[fm.facility_id, "p2h_el_capacity_kw_e"])
        peak = float(f.loc[fm.facility_id, "peak_absorbed_kw_e"]) if fm.facility_id in f.index else np.nan
        rows.append(
            {
                "facility_id": fm.facility_id,
                "facility_name": fm.name,
                "zone": fm.zone,
                "model_type": fm.model_type,
                "n_basins": fm.n_basins,
                "water_volume_m3": vol,
                "water_area_m2": sum(b.area_m2 for b in fm.basins),
                "storage_mwh_th_per_k": c_k * MWH,
                "storage_mwh_th_per_k_time_weighted": c_avg * MWH,
                "storage_band_mwh_th": cap * MWH,
                "mean_band_width_k": cap / c_k if c_k > 0 else np.nan,
                "plant_rated_kw_th": rated,
                "plant_el_capacity_kw_e": el,
                "plant_w_el_per_m3": el * 1000.0 / vol if vol > 0 else np.nan,
                "peak_absorbed_kw_e": peak,
                "hours_to_fill_band_at_rated_power_h": cap / rated if rated > 0 else np.nan,
                "design_hold_load_kw_th": float(fm.design["q_design_kw"]),
            }
        )
    return pd.DataFrame(rows)


def storage_potential(R, tech: str, mode: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    fac = facility_storage(R, tech, mode)
    rows = []
    for fm in R["fms"].values():
        for b in fm.basins:
            rows.append(
                {
                    "zone": fm.zone,
                    "environment": b.environment,
                    "facility_id": fm.facility_id,
                    "volume": b.volume_m3,
                    "area": b.area_m2,
                    "c_k": b.c_kwh_per_k * MWH,
                    "c_avg": b.c_kwh_per_k * float(np.mean(b.active[:-1])) * MWH,
                    "band": b.cap_kwh * MWH,
                }
            )
    b = pd.DataFrame(rows)

    def summ(d: pd.DataFrame, zone: str, env: str) -> dict:
        return {
            "zone": zone,
            "environment": env,
            "n_facilities": int(d.facility_id.nunique()),
            "n_basins": len(d),
            "water_volume_m3": d.volume.sum(),
            "water_area_m2": d.area.sum(),
            "storage_mwh_th_per_k": d.c_k.sum(),
            "storage_mwh_th_per_k_time_weighted": d.c_avg.sum(),
            "storage_band_mwh_th": d.band.sum(),
            "mean_band_width_k": d.band.sum() / d.c_k.sum() if d.c_k.sum() > 0 else np.nan,
        }

    out = []
    for z in [*sorted(b.zone.unique()), "SH"]:
        dz = b if z == "SH" else b[b.zone == z]
        for env in ("indoor", "outdoor", "all"):
            de = dz if env == "all" else dz[dz.environment == env]
            if len(de):
                out.append(summ(de, z, env))
    s = pd.DataFrame(out)

    for i, r in s.iterrows():
        if r.environment != "all":
            continue
        d = fac if r.zone == "SH" else fac[fac.zone == r.zone]
        s.loc[i, "plant_el_capacity_mw_e"] = d.plant_el_capacity_kw_e.sum() / 1e3
        key = (tech, _size(R, mode), r.zone, mode) if r.zone != "SH" else None
        peak = (R["zone_frames"][key]["absorbed_kw_e"].max() if key else R["sh_hourly"][(tech, _size(R, mode), mode)]["absorbed_kw_e"].max()) / 1e3
        s.loc[i, "peak_absorbed_mw_e_coincident"] = peak
        vol = r.water_volume_m3
        s.loc[i, "plant_kw_el_per_1000m3"] = d.plant_el_capacity_kw_e.sum() / vol * 1000.0
        s.loc[i, "peak_absorbed_kw_el_per_1000m3"] = peak * 1e3 / vol * 1000.0
        s.loc[i, "hours_to_fill_band_at_rated_power_h"] = d.storage_band_mwh_th.sum() * 1e3 / d.plant_rated_kw_th.sum()
    return fac, s


def _temps(b, e: np.ndarray) -> np.ndarray:
    t = b.t_min + e / b.c_kwh_per_k
    return np.where(b.active[: len(e)] > 0, t, b.t_min)


def _comp_kw(b, temp: np.ndarray) -> dict[str, np.ndarray]:
    c = b.phys.components(temp, b.t_air)
    names = COMP_IN if b.environment == "indoor" else COMP_OUT
    w = b.area_m2 * b.active[:-1]
    return {k: np.nan_to_num(np.asarray(c[v], float)) * w for k, v in names.items()}


def charging_balance(R, tech: str, mode: str) -> pd.DataFrame:
    rows = []
    for fm in R["fms"].values():
        r, r0 = _res(R, tech, mode, fm.zone, fm.facility_id), _res(R, BASE, "baseline", fm.zone, fm.facility_id)
        for i, b in enumerate(fm.basins):
            eA, eB = r.energy[i], r0.energy[i]
            comp_a, comp_b = _comp_kw(b, _temps(b, eA[:-1])), _comp_kw(b, _temps(b, eB[:-1]))
            d = {c: float(np.sum(comp_a.get(c, 0.0) - comp_b.get(c, 0.0))) * MWH for c in COMPS}
            rows.append(
                {
                    "zone": fm.zone,
                    "environment": b.environment,
                    "facility_id": fm.facility_id,
                    "extra_loss_secant": float((b.rate * (eA[:-1] - eB[:-1])).sum()) * MWH,
                    "spill": float(r.spill[i].sum() - r0.spill[i].sum()) * MWH,
                    "stored_end": float((eA[-1] - eA[0]) - (eB[-1] - eB[0])) * MWH,
                    "unmet": float(r.short[i].sum() - r0.short[i].sum()) * MWH,
                    "basin_heat_in": float((r.q_basin[i] + r.conv_basin[i]).sum() - (r0.q_basin[i] + r0.conv_basin[i]).sum()) * MWH,
                    **{f"nl_{c}": v for c, v in d.items()},
                }
            )
        h = pd.DataFrame([{"zone": fm.zone, "environment": "hall", "facility_id": fm.facility_id, "p2h_hall": float(r.q_hall.sum()) * MWH}])
        rows.append(h.iloc[0].to_dict())
    d = pd.DataFrame(rows).fillna(0.0)
    out = []
    for z in [*sorted(d.zone.unique()), "SH"]:
        dz = d if z == "SH" else d[d.zone == z]
        bz = dz[dz.environment != "hall"]
        for env in ("indoor", "outdoor", "all"):
            be = bz if env == "all" else bz[bz.environment == env]
            if be.empty:
                continue
            sec = be.extra_loss_secant.sum()
            nl = {c: be[f"nl_{c}"].sum() for c in COMPS}
            nl_tot = sum(nl.values())
            k = sec / nl_tot if abs(nl_tot) > 1e-9 else 0.0
            row = {
                "zone": z,
                "environment": env,
                "scenario": mode,
                "technology": tech,
                "p2h_heat_basins_minus_conv_displaced_basins": be.basin_heat_in.sum(),
                "extra_loss_total": sec,
                "nonlinear_loss_total": nl_tot,
                "nonlinear_over_secant": nl_tot / sec if abs(sec) > 1e-9 else np.nan,
                **{f"extra_loss_{c.replace(' ', '_').replace('-', '_')}": nl[c] * k for c in COMPS},
                "spill": be.spill.sum(),
                "stored_end_of_period": be.stored_end.sum(),
                "unmet_heat_change": -be.unmet.sum(),
            }
            row["balance_residual"] = row["p2h_heat_basins_minus_conv_displaced_basins"] - (
                sec + row["spill"] + row["stored_end_of_period"] + row["unmet_heat_change"]
            )
            out.append(row)
    res = pd.DataFrame(out)

    tot = []
    for z in res.zone.unique():
        fz = [fm for fm in R["fms"].values() if z == "SH" or fm.zone == z]
        p2h = (
            sum(
                float((_res(R, tech, mode, fm.zone, fm.facility_id).q_basin.sum() + _res(R, tech, mode, fm.zone, fm.facility_id).q_hall.sum()))
                for fm in fz
            )
            * MWH
        )
        cur_a = sum(float(_res(R, tech, mode, fm.zone, fm.facility_id).conv_heat.sum()) for fm in fz) * MWH
        cur_b = sum(float(_res(R, BASE, "baseline", fm.zone, fm.facility_id).conv_heat.sum()) for fm in fz) * MWH
        el = sum(float(_res(R, tech, mode, fm.zone, fm.facility_id).el.sum()) for fm in fz) * MWH
        curt = sum(float(_res(R, tech, mode, fm.zone, fm.facility_id).curt_el.sum()) for fm in fz) * MWH
        tot.append(
            {
                "zone": z,
                "p2h_heat_mwh_th": p2h,
                "p2h_electricity_mwh_e": el,
                "curtailed_electricity_mwh_e": curt,
                "current_heat_displaced_mwh_th": cur_b - cur_a,
            }
        )
    res = res.merge(pd.DataFrame(tot), on="zone", how="left")
    cols = ["p2h_heat_mwh_th", "p2h_electricity_mwh_e", "curtailed_electricity_mwh_e", "current_heat_displaced_mwh_th"]
    res.loc[res.environment != "all", cols] = np.nan
    return res


def compute(R) -> dict:
    out: dict = {"facility": [], "summary": [], "balance": []}
    for tech in R["technologies"]:
        for mode in R["modes"]:
            fac, s = storage_potential(R, tech, mode)
            out["facility"].append(fac.assign(technology=tech, scenario=mode))
            out["summary"].append(s.assign(technology=tech, scenario=mode))
            out["balance"].append(charging_balance(R, tech, mode))
    return {k: pd.concat(v, ignore_index=True) for k, v in out.items()}
