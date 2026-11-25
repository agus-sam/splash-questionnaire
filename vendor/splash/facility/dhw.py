"""Hot water for bathers (showers), proportional to the number of visitors.

Visitors per hour come from the occupancy profiles: the persons in the water of all basins of a facility, divided by the mean time a
visitor spends in the water (Little's law, lambda = N / tau). If a facility has annual visitors in `inputs/dhw_facility.csv`, the hourly
series is scaled so that a full year adds up to that number. The heat follows from the shower water per visitor, the mixed shower
temperature and the monthly mains water temperature.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..config import Settings
from ..data_loader import SplashData
from ..physics import properties as pr
from ..preprocessing import Timeline, _month_masks, make_timeline, monthly_series, occupancy_array

log = logging.getLogger(__name__)


@dataclass
class DhwModel:
    facility_id: int
    visitors_per_h: np.ndarray
    demand_kw: np.ndarray
    shower_water_m3_per_visitor: float
    hot_shower_share: float
    sink_c: float
    tank_m3: float
    tank_known: bool
    visitor_scale: float
    visitors_from_data: bool


def persons_in_water(data: SplashData, s: Settings, tl: Timeline) -> dict[int, np.ndarray]:
    """Persons in the water of all basins of a facility, per hour (occupancy x area, only in the season of the basin)."""
    basins = data.basins.reset_index(drop=True)
    masks = _month_masks(data.facilities, basins, s.facility.exclude_temporarily_closed)
    out: dict[int, np.ndarray] = {}
    for i, b in basins.iterrows():
        if b["model_status"] != "ok":
            continue
        occ = occupancy_array(data, b["typology_key"], tl, s.physics.occupancy_scale)
        n = occ * float(b["area_m2"]) * masks[i, tl.month - 1]
        fid = int(b["facility_id"])
        out[fid] = out.get(fid, 0.0) + n
    return out


def mains_to_shower_kwh_per_m3(t_cold_c: np.ndarray, t_mix_c: float) -> np.ndarray:
    """Heat to bring 1 m3 of mains water to the shower temperature, kWh/m3 (zero if the mains water is warmer)."""
    t_mean = 0.5 * (t_cold_c + t_mix_c)
    return pr.rho_water(t_mean) * pr.cp_water(t_mean) * np.maximum(t_mix_c - t_cold_c, 0.0) / 3.6e6


def _table(data: SplashData) -> pd.DataFrame:
    if data.dhw_facility is None:
        return pd.DataFrame(columns=["annual_visitors", "shower_water_m3_per_visitor", "hot_shower_share", "dhw_tank_m3"])
    g = data.dhw_facility.copy()
    for c in ("annual_visitors", "shower_water_m3_per_visitor", "hot_shower_share", "dhw_tank_m3"):
        g[c] = pd.to_numeric(g[c], errors="coerce")
    return g.set_index("facility_id")


def build_dhw(data: SplashData, s: Settings, tl: Timeline, facility_ids) -> dict[int, DhwModel]:
    cfg = s.facility.dhw
    tab = _table(data)
    n_win = persons_in_water(data, s, tl)
    need_year = [int(f) for f in facility_ids if f in tab.index and pd.notna(tab.loc[f, "annual_visitors"])]
    n_year: dict[int, np.ndarray] = {}
    if need_year:
        n_year = persons_in_water(data, s, make_timeline(data, None, None))
    t_cold = monthly_series(data, "T_wn_indoor_c", tl)
    kwh_per_m3 = mains_to_shower_kwh_per_m3(t_cold, cfg.t_mix_c)
    out: dict[int, DhwModel] = {}
    for fid in facility_ids:
        fid = int(fid)
        row = tab.loc[fid] if fid in tab.index else None

        def pick(col: str, default: float) -> float:
            return default if row is None or pd.isna(row[col]) else float(row[col])

        lam = n_win.get(fid, np.zeros(tl.n)) / cfg.stay_in_water_h
        scale, from_data = 1.0, False
        annual = pick("annual_visitors", float("nan"))
        if not np.isnan(annual):
            year_total = float(n_year[fid].sum() / cfg.stay_in_water_h) if fid in n_year else 0.0
            if year_total > 0.0:
                scale, from_data = annual / year_total, True
            else:
                log.warning("facility %d has annual_visitors but no occupancy in the model: the value is ignored", fid)
        lam = lam * scale
        v = pick("shower_water_m3_per_visitor", cfg.shower_water_m3_per_visitor)
        share = pick("hot_shower_share", cfg.hot_shower_share)
        tank = pick("dhw_tank_m3", float("nan"))
        q = lam * v * share * kwh_per_m3 * (1.0 + cfg.loss_share)
        out[fid] = DhwModel(
            facility_id=fid,
            visitors_per_h=lam,
            demand_kw=q,
            shower_water_m3_per_visitor=v,
            hot_shower_share=share,
            sink_c=cfg.sink_c,
            tank_m3=0.0 if np.isnan(tank) else tank,
            tank_known=not np.isnan(tank),
            visitor_scale=scale,
            visitors_from_data=from_data,
        )
    return out
