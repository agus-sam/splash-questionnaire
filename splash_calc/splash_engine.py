"""Bridge from the questionnaire to the SPLASH facility model (v1.3.x, vendored in ``vendor/splash``).

One pool of the questionnaire becomes one SPLASH facility: every basin is mapped to a size class
and an environment, the hall gets its water area, floor area and archetype. The model then runs
hourly (basin heat balance, hall demand, hysteresis charging rule) on the operator curtailment of
2025 and 2026 for the zone T5 or T6. The electric resistive heater is sized as 100 %, 200 % and
300 % of the design load of the pool (coincident peak hold load of basins and hall).

Rule used here (SPLASH ``hysteresis_addon``): the heater runs on curtailed power only. While the
zone has curtailed power it covers the hall and the basins first and then charges the basin water
up to the upper band limit. Outside curtailment the basins cool down towards the lower limit; the
existing fuel plant covers the rest.

Hot water for showers: the visitors of the pool (annual figure, or daily figures times open days and
operating weeks) set the shower demand of the SPLASH model (v1.3, ``facility.dhw``). It is served by the same plant as the
hall, enters the design load and the heater size, and is part of the model demand. Without a visitor answer the model uses
its own occupancy profile. Pools whose showers are heated separately, or without showers, run without hot water.

The SPLASH package is imported from ``vendor/``. It is not modified.
"""
from __future__ import annotations

import dataclasses
import math
import sys
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

from splash.config import Settings  # noqa: E402
from splash.data_loader import SplashData, load_data  # noqa: E402
from splash.facility.kpis import heat_out  # noqa: E402
from splash.facility.model import build_facility_models, set_technology  # noqa: E402
from splash.facility.rules import simulate_rule  # noqa: E402
from splash.facility.verification import facility_checks  # noqa: E402
from splash.preprocessing import make_timeline  # noqa: E402

from .inputs import Basin, PoolInputs  # noqa: E402

MODEL_DIR = ROOT / "data" / "splash"
CURTAILMENT_FILE = ROOT / "data" / "real" / "curtailment_hourly_T5_T6.csv"

SIZES = (1.0, 2.0, 3.0)                    # resistive heater, share of design load
YEARS = (2025, 2026)
ZONES = ("T5", "T6")
OBSERVED_UNTIL = {2025: "2025-12-31", 2026: "2026-11-22"}
DEFAULT_SIZE = 2.0
DEFAULT_YEAR = 2025
MWH = 1e-3

# questionnaire basin type -> SPLASH size class (indoor or combined pool / open-air pool)
SIZE_CLASS = {
    "lap": ("Schwimmer", "Schwimmer"),
    "teaching": ("Kurs/Lehr", "Kurs/Lehr"),
    "therapy": ("Warm/Sprudel/Tret", "Nichtschwimmer"),
    "children": ("Kleinkind", "Kleinkind"),
    "leisure": ("Nichtschwimmer", "Wellen/Natur"),
    "diving": ("Sprung/Tauch", "Sprung/Tauch"),
    "outdoor": ("Schwimmer", "Schwimmer"),
}
DEFAULT_DEPTH_M = {"lap": 1.8, "teaching": 1.2, "therapy": 1.1, "children": 0.4, "leisure": 1.1, "diving": 4.0, "outdoor": 1.8}
BADTYP = {"indoor": "Hallenbad", "combined": "Kombibad", "open_air": "Freibad"}
FAC_ID = 1
HALL_ID = "H001"
HALL_HEIGHT_M = 6.0
HALL_FLOOR_PER_WATER = 2.5                 # model default ratio when the hall area is unknown (2.0 to 3.0)
MIN_BAND_K = 0.25


class SplashInputError(ValueError):
    """The questionnaire does not give enough pool data for the model."""


@dataclass
class BasinMap:
    index: int
    type: str
    size_class: str
    environment: str
    area_m2: float
    volume_m3: float
    perimeter_m: float
    t_min: float
    t_max: float
    notes: list[str] = field(default_factory=list)


@dataclass
class SizeResult:
    year: int
    size: float
    q_rated_kw: float                 # thermal rating of the resistive heater
    el_capacity_kw: float
    window_hours: int
    zone_available_mwh: float         # curtailed energy in the zone during the window
    absorbed_mwh_el: float
    p2h_heat_mwh: float
    displaced_mwh_th: float           # conventional heat replaced
    baseline_conv_mwh_th: float
    demand_mwh_th: float
    unmet_mwh_th: float
    spill_mwh_th: float
    absorption_hours: int
    peak_kw: float
    utilisation: float                # mean heater load in absorption hours, share of rating
    share_of_zone: float              # absorbed energy as share of the zone curtailment
    hourly_el_kw: np.ndarray
    hourly_available_kw: np.ndarray
    hourly_soc_kwh: np.ndarray
    hourly_demand_kw: np.ndarray
    hourly_displaced_kw: np.ndarray
    start_local: pd.Timestamp
    checks: dict[str, float]          # model verification residuals (kW or kWh), all should be ~0
    hourly_dhw_kw: np.ndarray | None = None   # hourly hot water demand (part of hourly_demand_kw), None without hot water

    @property
    def max_residual(self) -> float:
        keys = ("basin_balance_resid_kw", "hall_balance_resid_kw", "electricity_resid_kw", "capacity_violation_kw",
                "bounds_violation_kwh", "grid_electricity_where_none_allowed_kw", "p2h_heat_without_curtailment_kw")
        return max(float(self.checks[k]) for k in keys)

    @property
    def full_year(self) -> bool:
        return self.window_hours >= 8760


@dataclass
class SplashRun:
    zone: str
    share: float
    eta: float
    design_kw: float
    design_basins_kw: float
    design_hall_kw: float
    storage_kwh: float
    storage_per_k_kwh: float
    basins: list[BasinMap]
    model_demand_mwh: dict[int, float]
    results: dict[tuple[int, float], SizeResult]
    flags: dict[str, bool]
    notes: list[str]
    version: str
    calibration: dict = field(default_factory=dict)
    demand_basins_kw: np.ndarray | None = None     # hourly heat demand of all basins, reference year 2025
    demand_hall_kw: np.ndarray | None = None       # hourly sensible heat demand of the hall, reference year 2025
    demand_split_mwh: dict[int, tuple[float, float]] | None = None   # year -> (basins, hall) in the model window
    bundle: dict | None = field(default=None, repr=False, compare=False)   # live model of the reference year (not pickled)
    demand_dhw_kw: np.ndarray | None = None        # hourly hot water demand (showers), reference year 2025, None without hot water
    design_dhw_kw: float = 0.0                     # hot water share of the design load (kW, instantaneous peak in the coincident hour)
    demand_dhw_mwh: dict[int, float] = field(default_factory=dict)   # year -> hot water demand in the model window
    dhw: dict = field(default_factory=dict)        # facts about the hot water input (visitors, source, litres, supply)

    def __getstate__(self) -> dict:
        d = dict(self.__dict__)
        d["bundle"] = None
        return d

    def get(self, year: int, size: float) -> SizeResult:
        return self.results[(year, float(size))]


# --------------------------------------------------------------------------- data
@lru_cache(maxsize=1)
def static_data() -> SplashData:
    """Static SPLASH package (weather, occupancy, bands, parameters). Loaded once."""
    return load_data(MODEL_DIR)


@lru_cache(maxsize=1)
def curtailment_table() -> pd.DataFrame:
    if not CURTAILMENT_FILE.exists():
        raise FileNotFoundError(f"{CURTAILMENT_FILE} is missing. Run scripts/build_curtailment.py.")
    df = pd.read_csv(CURTAILMENT_FILE, parse_dates=["ts_utc"])
    return df


@lru_cache(maxsize=2)
def calendar(year: int) -> pd.DataFrame:
    return pd.read_csv(MODEL_DIR / "weather" / f"calendar_{year}.csv")


def curtailment_mw(year: int) -> pd.DataFrame:
    """Hourly curtailed power (MW) per zone, indexed by hour_of_year 1..8760, plus the flag column."""
    cur = curtailment_table()
    cal = calendar(year)
    utc = pd.to_datetime(cal["ts_utc"], utc=True).dt.tz_localize(None)
    sub = cur.set_index("ts_utc").reindex(utc)
    out = pd.DataFrame({z: sub[f"{z}_mw"].fillna(0.0).to_numpy() for z in ZONES}, index=pd.Index(cal["hour_of_year"].to_numpy(), name="hour_of_year"))
    out["flag"] = sub["flag"].fillna("not_observed").to_numpy()
    return out


def settings(eta: float, air_temp_c: float | None, dhw: bool = False, shower_m3: float | None = None,
             t_mix_c: float | None = None, stay_h: float | None = None, smooth_h: int = 1) -> Settings:
    ov = [f"system.p2h_efficiency={eta}", "facility.technologies=[resistive]", "facility.zone_modes=[hysteresis_addon]"]
    if air_temp_c is not None:
        ov.append(f"hall_air.air_temp_c={air_temp_c}")
    if dhw:
        ov.append("facility.dhw.enabled=true")
        if shower_m3 is not None:
            ov.append(f"facility.dhw.shower_water_m3_per_visitor={shower_m3}")
        if t_mix_c is not None:
            ov.append(f"facility.dhw.t_mix_c={t_mix_c}")
        if stay_h is not None:
            ov.append(f"facility.dhw.stay_in_water_h={stay_h}")
        if smooth_h > 1:
            ov.append(f"facility.dhw.sizing_smooth_h={int(smooth_h)}")
    return Settings.from_yaml(MODEL_DIR / "settings.yaml", ov)


# ---------------------------------------------------------------- questionnaire map
def _geometry(b: Basin) -> tuple[float, float, float, list[str]]:
    """Return (area, volume, perimeter, notes) of one basin."""
    notes: list[str] = []
    area = b.area_m2()
    vol, vol_est = b.volume_m3()
    depth_default = DEFAULT_DEPTH_M.get(b.type, 1.5)
    if area <= 0 and vol > 0:
        area = vol / depth_default
        notes.append("area_from_volume")
    if area <= 0:
        raise SplashInputError("basin without area or volume")
    if vol <= 0:
        vol = area * depth_default
        notes.append("volume_from_default_depth")
    if b.length_m and b.width_m:
        per = 2.0 * (float(b.length_m) + float(b.width_m))
    else:
        per = 6.0 * math.sqrt(area / 2.0)
        notes.append("perimeter_from_aspect_ratio")
    return float(area), float(vol), float(per), notes


def map_pool(inp: PoolInputs, band_factor: float = 1.0, band_k: float | None = None) -> tuple[list[BasinMap], dict]:
    """Translate the questionnaire pool into SPLASH basin descriptions."""
    data = static_data()
    ptype = inp.pool_type if inp.pool_type in BADTYP else "indoor"
    bands = data.bands.set_index(["size_class", "environment"])
    maps: list[BasinMap] = []
    for i, b in enumerate(inp.basins):
        try:
            area, vol, per, notes = _geometry(b)
        except SplashInputError:
            continue
        btype = b.type if b.type in SIZE_CLASS else "lap"
        outdoor = ptype == "open_air" or btype == "outdoor" or (ptype == "combined" and b.environment == "outdoor")
        env = "outdoor" if outdoor else "indoor"
        sc = SIZE_CLASS[btype][1 if ptype == "open_air" else 0]
        if (sc, env) not in bands.index:
            sc = "Schwimmer"
        lo_d, hi_d = float(bands.loc[(sc, env), "T_min_c"]), float(bands.loc[(sc, env), "T_max_c"])
        t_min = float(b.setpoint_c) if b.setpoint_c else lo_d
        if not b.setpoint_c:
            notes.append("setpoint_class_default")
        if band_k is not None:
            width = float(band_k)
        elif inp.allowed_change_k is not None:
            width = float(inp.allowed_change_k)
        else:
            width = hi_d - lo_d
            notes.append("band_class_default")
        width = max(width * band_factor, MIN_BAND_K)
        maps.append(BasinMap(i, btype, sc, env, area, vol, per, t_min, t_min + width, notes))
    if not maps:
        raise SplashInputError("no basin with area or volume")
    meta = {"pool_type": ptype}
    return maps, meta


def _tables(inp: PoolInputs, maps: list[BasinMap], zone: str, ptype: str) -> dict[str, pd.DataFrame]:
    badtyp = BADTYP[ptype]
    indoor = [m for m in maps if m.environment == "indoor"]
    hall_water = sum(m.area_m2 for m in indoor)
    rows = []
    for k, m in enumerate(maps):
        rows.append(
            {
                "basin_id": 1000 + k,
                "facility_id": FAC_ID,
                "facility_name": inp.name or "Pool",
                "badtyp": badtyp,
                "size_class": m.size_class,
                "typology_key": f"{badtyp}|{m.size_class}",
                "environment": m.environment,
                "environment_source": "questionnaire",
                "area_m2": m.area_m2,
                "volume_m3": m.volume_m3,
                "perimeter_m": m.perimeter_m,
                "side_area_m2": m.perimeter_m * m.volume_m3 / m.area_m2,
                "area_source": "questionnaire",
                "depth_source": "questionnaire",
                "perimeter_source": "questionnaire",
                "hall_id": HALL_ID if m.environment == "indoor" else np.nan,
                "f_act_value": 1.0,
                "band_override_min_c": m.t_min,
                "band_override_max_c": m.t_max,
                "model_status": "ok",
                "curtail_zone_id": zone,
                "weather_zone_id": zone,
            }
        )
    basins = pd.DataFrame(rows)
    start, end, applies = _season(inp, ptype)
    fac = pd.DataFrame(
        [
            {
                "facility_id": FAC_ID,
                "name": inp.name or "Pool",
                "badtyp": badtyp,
                "weather_zone_id": zone,
                "curtail_zone_id": zone,
                "season_start_month": start,
                "season_end_month": end,
                "temporarily_closed_flag": 0,
                "n_basins": len(maps),
                "season_applies_to": applies,
            }
        ]
    )
    cols = ["hall_id", "facility_id", "badtyp", "curtail_zone_id", "weather_zone_id", "water_area_m2", "hall_archetype", "hall_floor_area_m2", "hall_height_m"]
    if indoor:
        floor = float(inp.hall_area_m2) if inp.hall_area_m2 else hall_water * HALL_FLOOR_PER_WATER
        halls = pd.DataFrame(
            [[HALL_ID, FAC_ID, badtyp, zone, zone, hall_water, badtyp, floor, HALL_HEIGHT_M]],
            columns=cols,
        )
    else:
        halls = pd.DataFrame(columns=cols)
    annual, _ = inp.annual_visitors()
    dhw = pd.DataFrame(
        [{
            "facility_id": FAC_ID,
            "facility_name": inp.name or "Pool",
            "badtyp": badtyp,
            "annual_visitors": annual if annual else np.nan,
            "shower_water_m3_per_visitor": np.nan,
            "hot_shower_share": np.nan,
            "dhw_tank_m3": inp.dhw_tank_m3 if inp.dhw_tank_m3 else np.nan,
            "source": "questionnaire" if annual else "model occupancy profile",
            "is_synthetic": 0 if annual else 1,
        }]
    )
    return {"basins": basins, "facilities": fac, "halls": halls, "dhw_facility": dhw}


def _season(inp: PoolInputs, ptype: str) -> tuple[int, int, str]:
    """Model months of operation from the opening and closing dates (whole months, a date after the 15th rounds up).

    Without an answer, open-air and combined pools get a default season of about 21 weeks around July.
    """
    applies = "outdoor_basins" if ptype == "combined" else "all"
    year_round, s_from, s_to = inp.season_year_round, inp.season_from, inp.season_to
    if ptype == "combined":
        # Combined pool: the halls run all year, the season is the opening window of the outdoor basins.
        # Without an answer the default of about 21 weeks around July applies (May to September), as for the SPLASH facility.
        year_round, s_from, s_to = inp.outdoor_year_round, inp.outdoor_from, inp.outdoor_to
    if year_round:
        return 1, 12, applies
    if s_from and s_to:
        (d0, m0), (d1, m1) = s_from, s_to
        start = m0 + (1 if d0 > 15 else 0)
        end = m1 - (1 if d1 < 15 else 0)
        start = (start - 1) % 12 + 1
        end = (end - 1) % 12 + 1
        if (m0, d0) <= (m1, d1) and start > end:        # a short season inside one or two months
            start = end = m0
        return start, end, applies
    if ptype in ("open_air", "combined"):
        weeks = (inp.outdoor_weeks if ptype == "combined" else inp.operating_weeks) or 21.0
        n = int(min(12, max(1, round(weeks / 4.345))))
        start = int(round(7.0 - (n - 1) / 2.0))
        return start, min(12, start + n - 1), applies
    return 1, 12, "all"


def _archetypes(base: pd.DataFrame, heat_recovery: bool | None) -> pd.DataFrame:
    """Hall archetypes as in the SPLASH model.

    The ventilation answer does not change them: the heat recovery of the SPLASH archetype (0.5 for the Kombibad) applies to every
    answer, so that the questionnaire and the SPLASH model give the same hall demand.
    """
    return base.copy()


def _data_for(year: int, tabs: dict[str, pd.DataFrame], heat_recovery: bool | None) -> SplashData:
    d = static_data()
    cal = calendar(year)
    cur = curtailment_mw(year)[list(ZONES)]
    return dataclasses.replace(
        d,
        basins=tabs["basins"],
        facilities=tabs["facilities"],
        halls=tabs["halls"],
        hall_archetypes=_archetypes(d.hall_archetypes, heat_recovery),
        dhw_facility=tabs["dhw_facility"],
        calendar=cal,
        curtailment=cur,
    )


# ------------------------------------------------------------------------- run
def _run_splash_uncached(
    inp: PoolInputs,
    zone: str,
    *,
    eta: float = 0.99,
    band_factor: float = 1.0,
    band_k: float | None = None,
    share: float = 1.0,
    target_heat_kwh: float | None = None,
    sizes: tuple[float, ...] = SIZES,
    years: tuple[int, ...] = YEARS,
    dhw: tuple[float, float, float] | None = None,
) -> SplashRun:
    """Run the hysteresis add-on rule for every year and heater size. Returns a ``SplashRun``.

    ``dhw`` is (litres of shower water per visitor, shower temperature in degC, mean stay in the water in h) from the
    parameter file. The operator's litres per visitor, if given, replace the first value. ``None`` uses the model defaults.

    ``target_heat_kwh`` is the useful heat per year that the operator reports for the pool
    (basins and hall). The physical demand of basins and hall in the SPLASH model is scaled by one factor so that its
    full-year 2025 demand matches that value. Hot water for showers is not scaled. Storage capacity and temperature band stay fixed, so
    the storage is relatively larger for a smaller demand. The factor is reported in ``SplashRun.calibration``."""
    if zone not in ZONES:
        raise SplashInputError(f"zone {zone!r} is not in the SPLASH data (T5, T6)")
    maps, meta = map_pool(inp, band_factor, band_k)
    ptype = meta["pool_type"]
    tabs = _tables(inp, maps, zone, ptype)
    use_dhw = inp.dhw_supply == "central"
    litres = inp.shower_litres or (dhw[0] if dhw else None)
    s = settings(eta, inp.air_setpoint_c, dhw=use_dhw, shower_m3=(litres / 1000.0) if litres else None,
                 t_mix_c=dhw[1] if dhw else None, stay_h=dhw[2] if dhw else None)
    fc = s.facility
    static = static_data()

    # design load once, on the full year 2025, so that all years share the same heater size
    d_ref = _data_for(2025, tabs, inp.heat_recovery)
    tl_ref = make_timeline(d_ref, "2025-01-01", "2025-12-31")
    fms_ref = build_facility_models(d_ref, s, tl_ref)
    set_technology(fms_ref, s, "resistive")
    fm_ref = fms_ref[FAC_ID]
    tank = _tank_smoothing(fm_ref, inp, d_ref, tl_ref, dhw[1] if dhw else 40.0) if use_dhw else {}
    if tank.get("window_h", 1) > 1:
        # the tank averages the shower peak over its window in the design load: rebuild the reference with that setting
        s = settings(eta, inp.air_setpoint_c, dhw=True, shower_m3=(litres / 1000.0) if litres else None,
                     t_mix_c=dhw[1] if dhw else None, stay_h=dhw[2] if dhw else None, smooth_h=tank["window_h"])
        fc = s.facility
        fms_ref = build_facility_models(d_ref, s, tl_ref)
        set_technology(fms_ref, s, "resistive")
        fm_ref = fms_ref[FAC_ID]
    raw_demand = float((fm_ref.basin_demand_kw().sum() + fm_ref.hall_kw().sum()) * MWH)    # basins and hall, hot water follows the visitors
    scale, calib = 1.0, {"applied": False, "raw_model_mwh": raw_demand, "target_mwh": None, "factor": 1.0, "clipped": False}
    if target_heat_kwh and target_heat_kwh > 0 and raw_demand > 0:
        wanted = float(target_heat_kwh) / 1000.0 / raw_demand
        scale = min(max(wanted, CALIB_MIN), CALIB_MAX)
        calib.update(applied=True, target_mwh=float(target_heat_kwh) / 1000.0, factor=scale, clipped=abs(scale - wanted) > 1e-12)
    _scale_demand(fm_ref, scale)
    design = dict(fm_ref.design)

    results: dict[tuple[int, float], SizeResult] = {}
    demand: dict[int, float] = {}
    split: dict[int, tuple[float, float]] = {}
    dhw_mwh: dict[int, float] = {}
    bundle: dict | None = None
    for year in years:
        d = _data_for(year, tabs, inp.heat_recovery)
        tl = make_timeline(d, f"{year}-01-01", OBSERVED_UNTIL[year])
        fms = build_facility_models(d, s, tl)
        set_technology(fms, s, "resistive")
        fm = fms[FAC_ID]
        _scale_demand(fm, scale)
        fm.design = dict(design)
        cur = curtailment_mw(year)
        avail = cur.loc[tl.hour_of_year, zone].to_numpy(float) * 1000.0 * share
        zero = {FAC_ID: 0.0}
        base = simulate_rule([fm], zero, avail, "floor", supply="conv", depth=fc.charge_depth, hold_margin_k=fc.hold_margin_k, priority=fc.plant.shortage_priority)[FAC_ID]
        demand[year] = float(fm.total_demand_kw().sum() * MWH)
        split[year] = (float(fm.basin_demand_kw().sum() * MWH), float(fm.hall_kw().sum() * MWH))
        dhw_mwh[year] = float(fm.dhw_kw().sum() * MWH) if fm.dhw is not None else 0.0
        local0 = tl.index_local[0]
        if year == DEFAULT_YEAR:
            bundle = {"fm": fm, "avail": avail.copy(), "depth": fc.charge_depth, "hold": fc.hold_margin_k,
                      "priority": fc.plant.shortage_priority, "start_local": local0, "year": year}
        for x in sizes:
            q = x * design["q_design_kw"]
            r = simulate_rule([fm], {FAC_ID: q}, avail, "hysteresis", supply="addon", depth=fc.charge_depth, hold_margin_k=fc.hold_margin_k, priority=fc.plant.shortage_priority)[FAC_ID]
            heat = heat_out(r)
            on = r.curt_el > 1e-6
            conv_b, conv_s = float(base.conv_heat.sum()), float(r.conv_heat.sum())
            soc = r.energy[:, :-1].sum(axis=0)
            hours = int(len(avail))
            chk = facility_checks(fm, r, q, fc.charge_depth, "hysteresis_addon", avail)
            results[(year, float(x))] = SizeResult(
                year=year,
                size=float(x),
                q_rated_kw=float(q),
                el_capacity_kw=float(q / eta),
                window_hours=hours,
                zone_available_mwh=float(avail.sum() * MWH),
                absorbed_mwh_el=float(r.curt_el.sum() * MWH),
                p2h_heat_mwh=float(heat.sum() * MWH),
                displaced_mwh_th=(conv_b - conv_s) * MWH,
                baseline_conv_mwh_th=conv_b * MWH,
                demand_mwh_th=demand[year],
                unmet_mwh_th=float((r.short.sum() + r.hall_short.sum()) * MWH),
                spill_mwh_th=float(r.spill.sum() * MWH),
                absorption_hours=int(on.sum()),
                peak_kw=float(r.curt_el.max()),
                utilisation=float(heat[on].mean() / q) if on.any() and q > 0 else 0.0,
                share_of_zone=float(r.curt_el.sum() / max(avail.sum(), 1e-9)),
                hourly_el_kw=r.curt_el.copy(),
                hourly_available_kw=avail.copy(),
                hourly_soc_kwh=soc,
                hourly_demand_kw=fm.total_demand_kw().copy(),
                hourly_displaced_kw=base.conv_heat - r.conv_heat,
                start_local=local0,
                checks=chk,
                hourly_dhw_kw=fm.dhw_kw().copy() if fm.dhw is not None else None,
            )
    notes = sorted({n for m in maps for n in m.notes})
    flags = {k: bool(v) for k, v in static.synthetic_flags.items()}
    dhw_info = _dhw_info(fm_ref, inp, use_dhw)
    dhw_info.update(tank)
    return SplashRun(
        zone=zone,
        share=share,
        eta=eta,
        design_kw=float(design["q_design_kw"]),
        design_basins_kw=float(design["q_design_basins_kw"]),
        design_hall_kw=float(design["q_design_hall_kw"]),
        storage_kwh=float(sum(b.cap_kwh for b in fm_ref.basins)),
        storage_per_k_kwh=float(sum(b.c_kwh_per_k for b in fm_ref.basins)),
        basins=maps,
        model_demand_mwh=demand,
        results=results,
        flags=flags,
        notes=notes,
        version=_model_version(),
        calibration=calib,
        demand_basins_kw=np.asarray(fm_ref.basin_demand_kw(), dtype=float),
        demand_hall_kw=np.asarray(fm_ref.hall_kw(), dtype=float),
        demand_split_mwh=split,
        bundle=bundle,
        demand_dhw_kw=np.asarray(fm_ref.dhw_kw(), dtype=float) if fm_ref.dhw is not None else None,
        design_dhw_kw=float(design.get("q_design_dhw_kw", 0.0)) if fm_ref.dhw is not None else 0.0,
        demand_dhw_mwh=dhw_mwh,
        dhw=dhw_info,
    )


CALIB_MIN, CALIB_MAX = 0.15, 2.0

_CACHE: dict[str, SplashRun] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 8


def run_splash(inp: PoolInputs, zone: str, **kw) -> SplashRun:
    """Cached ``_run_splash_uncached``. Prices, discount rate and other economics do not enter the
    SPLASH run, so changing them reuses the result (the run takes several seconds)."""
    key = repr((inp, zone, sorted(kw.items())))
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
    if hit is not None:
        return hit
    out = _run_splash_uncached(inp, zone, **kw)
    with _CACHE_LOCK:
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = out
    return out


def _scale_demand(fm, k: float) -> None:
    """Scale the heat demand of basins and hall and their share of the design load by ``k``.

    Hot water for showers is not scaled: it follows the visitor numbers, not the reported consumption.
    Storage capacity per kelvin is not touched."""
    if abs(k - 1.0) < 1e-12:
        return
    for b in fm.basins:
        b.a_kw = b.a_kw * k
        b.rate = b.rate * k
    if fm.hall is not None:
        fm.hall.sensible_kw = fm.hall.sensible_kw * k
    d = fm.design
    if "q_design_kw" in d:
        d["q_design_kw"] = d["q_design_kw"] + (k - 1.0) * (d.get("q_design_basins_kw", 0.0) + d.get("q_design_hall_kw", 0.0))
    for key in ("q_design_basins_kw", "q_design_hall_kw", "sum_individual_basin_peaks_kw"):
        if key in d:
            d[key] = d[key] * k
    if "basin_peaks_kw" in d:
        d["basin_peaks_kw"] = [x * k for x in d["basin_peaks_kw"]]


TANK_WINDOW_MAX_H = 12
RHO_CP_WATER = 1.163                       # kWh per m3 and K


def _tank_smoothing(fm, inp: PoolInputs, data: SplashData, tl, sink_c: float) -> dict:
    """Averaging window (hours) of the shower peak in the design load that a hot water tank allows.

    Heat in the tank = volume x 1.163 kWh/(m3 K) x (tank temperature - mean mains water temperature). The window is that
    heat divided by the hot water peak of the model, rounded to whole hours, 1 to 12. The tank is assumed to be fully usable
    (upper bound). Only the design load and so the heater size use it; the hourly operation is unchanged."""
    if not inp.dhw_tank_m3 or fm.dhw is None:
        return {}
    from splash.preprocessing import monthly_series

    t_cold = float(np.mean(monthly_series(data, "T_wn_indoor_c", tl)))
    energy = float(inp.dhw_tank_m3) * RHO_CP_WATER * max(sink_c_or(fm, sink_c) - t_cold, 0.0)
    peak = float(np.max(fm.dhw.demand_kw))
    window = 1 if peak <= 0 else int(min(max(round(energy / peak), 1), TANK_WINDOW_MAX_H))
    return {"tank_m3": float(inp.dhw_tank_m3), "tank_kwh": energy, "window_h": window, "window_capped": peak > 0 and energy / peak > TANK_WINDOW_MAX_H + 0.5}


def sink_c_or(fm, default: float) -> float:
    return float(fm.dhw.sink_c) if fm.dhw is not None else float(default)


def _dhw_info(fm, inp: PoolInputs, enabled: bool) -> dict:
    """Facts about the hot water input, for the results page and the stored record."""
    annual, src = inp.annual_visitors()
    out = {"enabled": bool(enabled), "supply": inp.dhw_supply, "visitor_source": src}
    if enabled and fm.dhw is not None:
        d = fm.dhw
        out.update(
            visitors_per_year=float(d.visitors_per_h.sum()),   # fm_ref covers the full year 2025
            visitors_from_data=bool(d.visitors_from_data),
            litres_per_visitor=float(d.shower_water_m3_per_visitor) * 1000.0,
            peak_kw=float(d.demand_kw.max()),
            sink_c=float(d.sink_c),
        )
    return out


def _model_version() -> str:
    import splash

    return str(getattr(splash, "__version__", "unknown"))
