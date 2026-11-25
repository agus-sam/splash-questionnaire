from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass, field

import numpy as np

from .config import Settings
from .data_loader import SplashData
from .physics import hall_air as ha
from .physics import indoor_delgado as idg
from .physics import outdoor_buscemi as ob
from .physics.pool_models import IndoorPoolModel, OutdoorPoolModel
from .preprocessing import Timeline, UnitSpec, heat_capacity_kwh_per_k, monthly_series, occupancy_array, weather_arrays

log = logging.getLogger(__name__)

HALL_REF_FLOOR_PER_WATER = 2.0
RATE_MAX = 0.9


@dataclass
class StorageUnit:
    uid: str
    hall_key: str | None
    c_kwh_per_k: float
    active_frac: np.ndarray
    a_kw: np.ndarray
    rate: np.ndarray
    phys: object


@dataclass
class HallInfo:
    archetype: str
    area_m2: float
    t_ext: np.ndarray
    rh_ext: np.ndarray
    p_tot: np.ndarray
    air_sens_kw_per_k: np.ndarray
    t_air_a: float
    rh_air_pct: float
    arch: object


@dataclass
class Problem:
    units: list[StorageUnit]
    halls: dict[str, HallInfo] = field(default_factory=dict)


def _archetypes(data: SplashData, s: Settings) -> dict[str, ha.HallArchetype]:
    out = {}
    for _, r in data.hall_archetypes.iterrows():
        out[str(r["hall_archetype"])] = ha.HallArchetype(
            name=str(r["hall_archetype"]),
            ua_kw_per_k_per_m2=float(r["envelope_UA_kw_per_k_per_m2_water"]),
            tau_fa=float(r["tau_fa"]),
            air_changes_per_h=float(r["air_changes_per_h"]),
            hru_effectiveness=float(r["hru_effectiveness"]),
            air_temp_c=float(r["hall_air_temp_c"]),
            rh_pct=float(r["hall_rh_pct"]),
            t_wall_c=float(r["T_wall_c"]),
            t_rs_c=float(r["T_rs_c"]),
            t_g_c=float(r["T_g_c"]),
            volume_m3_per_m2=s.hall_air.hall_volume_m3_per_m2_water,
        )
    return out


def _hall_scaling(data: SplashData, s: Settings, hall_key: str, zone: str, badtyp: str) -> tuple[float, float]:
    h = data.halls
    rows = h[h["hall_id"] == hall_key]
    if rows.empty:
        rows = h[(h["curtail_zone_id"] == zone) & (h["badtyp"] == badtyp)]
    water = float(rows["water_area_m2"].sum())
    if "hall_floor_area_m2" in rows.columns and rows["hall_floor_area_m2"].notna().all() and len(rows):
        floor = float(rows["hall_floor_area_m2"].sum())
        height = rows["hall_height_m"].fillna(6.0)
        volume = float((rows["hall_floor_area_m2"] * height).sum())
    else:
        floor = HALL_REF_FLOOR_PER_WATER * water
        volume = s.hall_air.hall_volume_m3_per_m2_water * water
    if water <= 0:
        return HALL_REF_FLOOR_PER_WATER, s.hall_air.hall_volume_m3_per_m2_water
    return floor / water, volume / water


def build_problem(data: SplashData, s: Settings, tl: Timeline, units: list[UnitSpec]) -> Problem:
    T = tl.n
    out_p = ob.OutdoorParams.from_mapping(data.outdoor_params, **s.physics.outdoor)
    in_p = idg.IndoorParams.from_mapping(data.indoor_params, **{**s.physics.indoor, "evaporation_variant": s.facility.indoor_evaporation})
    archs = _archetypes(data, s)
    t_re = monthly_series(data, "T_re_outdoor_c", tl)
    t_wn = monthly_series(data, "T_wn_indoor_c", tl)

    hall_units: dict[str, list[int]] = {}
    for i, u in enumerate(units):
        if u.hall_key is not None:
            hall_units.setdefault(u.hall_key, []).append(i)

    storage: list[StorageUnit] = []
    hall_rh: dict[str, float] = {}
    clip_count = 0
    for u in units:
        wx = weather_arrays(data, u.wzone, tl)
        occ = occupancy_array(data, u.typology_key, tl, s.physics.occupancy_scale)
        mid = 0.5 * (u.t_min + u.t_max)
        c_kwh = heat_capacity_kwh_per_k(u.volume_m3, mid)
        frac = u.active_frac
        frac_ext = np.concatenate([frac, frac[-1:]])

        if u.environment == "outdoor":
            forcing = ob.OutdoorForcing(
                t_a=wx["t_a"],
                rh=wx["rh"],
                ghi=wx["ghi"],
                ws10=wx["ws10"],
                sp=wx["sp"],
                t_re=t_re,
                occ_per_m2=occ,
                cloud=wx["cloud"],
                ir=wx["ir"],
                month=tl.month,
                hour_local=tl.hour_local,
            )
            phys = OutdoorPoolModel(forcing, ob.OutdoorGeometry(u.depth_m, u.l_ch_m), out_p)
            q_lo = phys.net_loss_kw_per_m2(u.t_min)
            q_hi = phys.net_loss_kw_per_m2(u.t_max)
        else:
            arch = archs[u.archetype]
            rh = s.hall_air.rh_pct if s.hall_air.rh_pct is not None else arch.rh_pct
            forcing = idg.IndoorForcing(p_tot=wx["sp"], occ_per_m2=occ, t_wn=t_wn)
            phys = IndoorPoolModel(
                forcing,
                idg.IndoorGeometry(u.depth_m, u.side_area_per_m2, u.f_act),
                in_p,
                rh_pct=rh,
                t_rs=arch.t_rs_c,
                t_g=arch.t_g_c,
                wall_mode=s.hall_air.wall_mode,
                wall_offset_k=arch.wall_offset_k(),
                t_wall_fixed=arch.t_wall_c,
            )
            t_air = s.hall_air.air_temp_c if s.hall_air.air_temp_c is not None else arch.air_temp_c
            q_lo = phys.net_loss_kw_per_m2(u.t_min, t_air)
            q_hi = phys.net_loss_kw_per_m2(u.t_max, t_air)
            hall_rh.setdefault(u.hall_key, float(rh))
        a_m2 = q_lo
        k_m2 = (q_hi - q_lo) / (u.t_max - u.t_min)

        c_m2 = c_kwh / u.area_m2
        rate = k_m2 / c_m2
        if (rate < 0).any() or (rate > RATE_MAX).any():
            clip_count += int(((rate < 0) | (rate > RATE_MAX)).sum())
        rate = np.clip(rate, 0.0, RATE_MAX)
        storage.append(
            StorageUnit(
                uid=u.uid,
                hall_key=u.hall_key,
                c_kwh_per_k=c_kwh,
                active_frac=frac_ext,
                a_kw=a_m2 * u.area_m2 * frac,
                rate=rate,
                phys=phys,
            )
        )
    if clip_count:
        log.warning("loss slope was clipped to [0, %.1f] per hour in %d unit hours", RATE_MAX, clip_count)

    halls: dict[str, HallInfo] = {}
    for key, idx in hall_units.items():
        u0 = units[idx[0]]
        arch = archs[u0.archetype]
        k_floor, v_per_water = _hall_scaling(data, s, key, u0.zone, u0.badtyp)
        arch = dataclasses.replace(
            arch, ua_kw_per_k_per_m2=arch.ua_kw_per_k_per_m2 * k_floor / HALL_REF_FLOOR_PER_WATER, volume_m3_per_m2=v_per_water
        )
        wx = weather_arrays(data, u0.wzone, tl)
        area_act = np.sum([units[j].area_m2 * storage[j].active_frac[:T] for j in idx], axis=0)
        sens = arch.sensitivity_kw_per_k_per_m2() * area_act
        t_a = s.hall_air.air_temp_c if s.hall_air.air_temp_c is not None else arch.air_temp_c
        halls[key] = HallInfo(
            archetype=u0.archetype,
            area_m2=float(sum(units[j].area_m2 for j in idx)),
            t_ext=wx["t_a"],
            rh_ext=wx["rh"],
            p_tot=wx["sp"],
            air_sens_kw_per_k=sens,
            t_air_a=t_a,
            rh_air_pct=hall_rh[key],
            arch=arch,
        )
    return Problem(units=storage, halls=halls)
