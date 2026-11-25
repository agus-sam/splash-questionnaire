from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import Settings
from .data_loader import SplashData
from .physics import properties as pr

log = logging.getLogger(__name__)

DAY_TYPES = ("weekday", "saturday", "sunday_holiday")


@dataclass
class Timeline:
    pos: np.ndarray
    hour_of_year: np.ndarray
    index_utc: pd.DatetimeIndex
    index_local: pd.DatetimeIndex
    month: np.ndarray
    hour_local: np.ndarray
    day_type: np.ndarray

    @property
    def n(self) -> int:
        return len(self.pos)


def make_timeline(data: SplashData, start: str | None, end: str | None) -> Timeline:
    cal = data.calendar
    mask = np.ones(len(cal), dtype=bool)
    dates = cal["date_local"].astype(str).to_numpy()
    if start:
        mask &= dates >= str(start)
    if end:
        mask &= dates <= str(end)
    pos = np.flatnonzero(mask)
    if len(pos) == 0:
        raise ValueError(f"time window {start} to {end} selects no hours")
    if len(pos) > 1 and not np.all(np.diff(pos) == 1):
        raise ValueError("time window must be contiguous")
    sub = cal.iloc[pos]
    utc = pd.DatetimeIndex(pd.to_datetime(sub["ts_utc"], utc=True).dt.tz_localize(None))
    local = pd.DatetimeIndex(pd.to_datetime(sub["ts_utc"], utc=True)).tz_convert("Europe/Berlin")
    local.name = "ts_local"
    dt_code = sub["day_type"].map({k: i for i, k in enumerate(DAY_TYPES)}).to_numpy()
    return Timeline(
        pos=pos,
        hour_of_year=sub["hour_of_year"].to_numpy(),
        index_utc=utc,
        index_local=local,
        month=sub["month"].to_numpy().astype(int),
        hour_local=sub["hour_local"].to_numpy().astype(int),
        day_type=dt_code.astype(int),
    )


def report_dates(index_local: pd.DatetimeIndex) -> pd.DatetimeIndex:
    day = index_local.tz_localize(None).normalize()
    year = day[0].year
    last = pd.Timestamp(year=year, month=12, day=31)
    return pd.DatetimeIndex(np.where(day > last, last, day))


def report_months(index_local: pd.DatetimeIndex) -> np.ndarray:
    return np.asarray(report_dates(index_local).month, dtype=int)


@dataclass
class UnitSpec:
    uid: str
    zone: str
    wzone: str
    badtyp: str
    size_class: str
    environment: str
    typology_key: str
    area_m2: float
    volume_m3: float
    perimeter_m: float
    side_area_per_m2: float
    f_act: float
    t_min: float
    t_max: float
    hall_key: str | None
    archetype: str | None
    active_frac: np.ndarray

    @property
    def depth_m(self) -> float:
        return self.volume_m3 / self.area_m2

    @property
    def l_ch_m(self) -> float:
        return self.area_m2 / self.perimeter_m


def _month_masks(fac: pd.DataFrame, basins: pd.DataFrame, exclude_closed: bool) -> np.ndarray:
    f = fac.set_index("facility_id")
    start = basins["facility_id"].map(f["season_start_month"]).fillna(1).astype(int).to_numpy()
    end = basins["facility_id"].map(f["season_end_month"]).fillna(12).astype(int).to_numpy()
    applies = basins["facility_id"].map(f["season_applies_to"]).fillna("all").to_numpy()
    closed = basins["facility_id"].map(f["temporarily_closed_flag"]).fillna(0).astype(int).to_numpy()
    months = np.arange(1, 13)[None, :]
    normal = (months >= start[:, None]) & (months <= end[:, None])
    wrap = (months >= start[:, None]) | (months <= end[:, None])
    mask = np.where((start <= end)[:, None], normal, wrap)
    indoor = basins["environment"].to_numpy() == "indoor"
    year_round = (applies == "outdoor_basins") & indoor
    mask[year_round, :] = True
    if exclude_closed:
        mask[closed == 1, :] = False
    return mask


def _bands(data: SplashData, size_class: str, env: str, shift: float, override=None, width: float | None = None):
    b = data.bands[(data.bands["size_class"] == size_class) & (data.bands["environment"] == env)]
    if b.empty:
        raise ValueError(f"no band for size class {size_class!r} and environment {env!r} in config/bands.csv")
    r = b.iloc[0]
    t_min, t_max = float(r["T_min_c"]), float(r["T_max_c"])
    if override is not None and not any(pd.isna(o) for o in override):
        t_min, t_max = float(override[0]), float(override[1])
    if width is not None:
        t_max = t_min + float(width)
    return t_min + shift, t_max + shift


def build_units(data: SplashData, s: Settings, tl: Timeline) -> list[UnitSpec]:
    basins = data.basins.copy()
    masks = _month_masks(data.facilities, basins, s.facility.exclude_temporarily_closed)
    active_b = masks[:, tl.month - 1]
    basins = basins.reset_index(drop=True)
    shift = s.system.band_shift_k
    halls = data.halls.set_index("hall_id")
    units: list[UnitSpec] = []
    for i, b in basins.iterrows():
        if b["model_status"] != "ok":
            continue
        indoor = b["environment"] == "indoor"
        t_min, t_max = _bands(
            data,
            b["size_class"],
            b["environment"],
            shift,
            override=(b["band_override_min_c"], b["band_override_max_c"]),
            width=s.system.band_width_k,
        )
        hall = b["hall_id"] if indoor and isinstance(b["hall_id"], str) else None
        arche = str(halls.loc[hall, "hall_archetype"]) if hall in halls.index else (str(b["badtyp"]) if indoor else None)
        units.append(
            UnitSpec(
                uid=f"B{int(b['basin_id'])}",
                zone=b["curtail_zone_id"],
                wzone=b["weather_zone_id"],
                badtyp=b["badtyp"],
                size_class=b["size_class"],
                environment=b["environment"],
                typology_key=b["typology_key"],
                area_m2=float(b["area_m2"]),
                volume_m3=float(b["volume_m3"]),
                perimeter_m=float(b["perimeter_m"]),
                side_area_per_m2=float(b["side_area_m2"] / b["area_m2"]),
                f_act=float(b["f_act_value"]) if pd.notna(b["f_act_value"]) else 1.0,
                t_min=t_min,
                t_max=t_max,
                hall_key=hall,
                archetype=arche,
                active_frac=active_b[i].astype(float),
            )
        )
    live = [u for u in units if u.active_frac.max() > 0.0]
    if len(live) < len(units):
        log.info("%d of %d units are inactive in the chosen time window and are dropped", len(units) - len(live), len(units))
    if not live:
        raise ValueError("no active units for the chosen time window")
    return live


def occupancy_array(data: SplashData, typology_key: str, tl: Timeline, scale: float) -> np.ndarray:
    o = data.occupancy[data.occupancy["typology_key"] == typology_key]
    cube = np.zeros((len(DAY_TYPES), 12, 24))
    di = o["day_type"].map({k: i for i, k in enumerate(DAY_TYPES)}).to_numpy()
    cube[di, o["month"].to_numpy() - 1, o["hour"].to_numpy()] = o["occupancy"].to_numpy()
    return cube[tl.day_type, tl.month - 1, tl.hour_local] / 100.0 * scale


def monthly_series(data: SplashData, column: str, tl: Timeline) -> np.ndarray:
    nw = data.network_water.set_index("month")[column]
    return nw.reindex(range(1, 13)).to_numpy()[tl.month - 1]


def weather_arrays(data: SplashData, wzone: str, tl: Timeline) -> dict[str, np.ndarray]:
    w = data.weather[wzone].iloc[tl.pos]
    return {
        "t_a": w["T2m_c"].to_numpy(float),
        "rh": w["RH_pct"].to_numpy(float),
        "ghi": w["G_h_wm2"].to_numpy(float),
        "ws10": w["WS10m_ms"].to_numpy(float),
        "sp": w["SP_pa"].to_numpy(float),
        "ir": w["IR_h_wm2"].to_numpy(float) if "IR_h_wm2" in w else np.full(len(w), np.nan),
        "cloud": w["cloud_total"].to_numpy(float) if "cloud_total" in w else np.full(len(w), np.nan),
    }


def curtailment_kw(data: SplashData, zone: str, tl: Timeline, share: float = 1.0) -> np.ndarray:
    return data.curtailment[zone].reindex(tl.hour_of_year).to_numpy(float) * 1000.0 * share


def heat_capacity_kwh_per_k(volume_m3: float, t_ref: float) -> float:
    return float(pr.rho_water(t_ref) * pr.cp_water(t_ref) * volume_m3 / 3.6e6)
