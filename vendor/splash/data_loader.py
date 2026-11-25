from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

HOURS_PER_YEAR = 8760


REAL_WEATHER_SOURCES = ("PVGIS_TMY", "PVGIS_SARAH", "PVGIS_ERA5", "ERA5", "DWD", "EPW", "CERRA_TMY", "MEASURED")
TMY_MARKERS = ("TMY", "EPW")


class DataError(RuntimeError):
    pass


@dataclass
class SplashData:
    root: Path
    basins: pd.DataFrame
    facilities: pd.DataFrame
    halls: pd.DataFrame
    hall_archetypes: pd.DataFrame
    calendar: pd.DataFrame
    weather: dict[str, pd.DataFrame]
    curtailment: pd.DataFrame
    occupancy: pd.DataFrame
    bands: pd.DataFrame
    network_water: pd.DataFrame
    outdoor_params: dict[str, object]
    indoor_params: dict[str, object]
    coordinator: dict[str, object]
    synthetic_flags: dict[str, bool]
    heat_sources: pd.DataFrame | None = None
    facility_heat_sources: pd.DataFrame | None = None
    provenance: pd.DataFrame | None = None
    dhw_facility: pd.DataFrame | None = None


def _read(root: Path, rel: str, required: bool = True) -> pd.DataFrame | None:
    p = root / rel
    if not p.exists():
        if required:
            raise DataError(f"required file missing: {p}")
        return None
    return pd.read_csv(p)


def _kv(df: pd.DataFrame) -> dict[str, object]:
    out: dict[str, object] = {}
    for k, v in zip(df["parameter"], df["value"]):
        try:
            out[k] = float(v)
        except (TypeError, ValueError):
            out[k] = v
    return out


def load_data(root: str | Path) -> SplashData:
    root = Path(root)
    if not root.exists():
        raise DataError(f"data root does not exist: {root}")
    log.info("Reading data package from %s", root)

    basins = _read(root, "clean/basins.csv")
    facilities = _read(root, "clean/facilities.csv")
    halls = _read(root, "clean/halls.csv")
    hg = _read(root, "inputs/hall_geometry.csv", required=False)
    if hg is not None:
        keep = [c for c in ("hall_id", "hall_floor_area_m2", "hall_height_m", "source", "is_synthetic") if c in hg.columns]
        hg = hg[keep].rename(columns={"source": "hall_geometry_source", "is_synthetic": "hall_geometry_is_synthetic"})
        halls = halls.merge(hg, on="hall_id", how="left")
    arche = _read(root, "inputs/hall_archetypes.csv")
    cal = _read(root, "weather/calendar_hourly.csv")
    w = _read(root, "weather/weather_hourly.csv")
    cur = _read(root, "inputs/curtailment_signal.csv")
    occ = _read(root, "inputs/occupancy_profiles.csv")
    bands = _read(root, "config/bands.csv")
    net = _read(root, "config/network_water_temp_monthly.csv")
    out_p = _kv(_read(root, "config/outdoor_buscemi_params.csv"))
    in_p = _kv(_read(root, "config/indoor_delgado_params.csv"))
    coord = _kv(_read(root, "config/coordinator_params.csv"))
    hs = _read(root, "config/heat_sources.csv", required=False)
    fhs = _read(root, "config/facility_heat_sources.csv", required=False)
    dhw = _read(root, "inputs/dhw_facility.csv", required=False)

    cal = cal.sort_values("hour_of_year").reset_index(drop=True)
    weather = {z: g.sort_values("hour_of_year").set_index("hour_of_year") for z, g in w.groupby("zone_id")}
    curtailment = cur.pivot(index="hour_of_year", columns="zone_id", values="available_mw").sort_index().fillna(0.0)

    flags = {
        "weather": _weather_is_synthetic(w),
        "curtailment": _flag(cur, "is_synthetic"),
        "occupancy": _flag(occ, "is_synthetic"),
        "heat_sources": hs is not None and _flag(hs, "is_synthetic"),
        "facility_heat_sources": fhs is not None and _flag(fhs, "is_synthetic"),
        "dhw_facility": dhw is not None and _flag(dhw, "is_synthetic"),
        "hall_geometry": "hall_geometry_is_synthetic" not in halls.columns or bool(halls["hall_geometry_is_synthetic"].fillna(1).astype(int).any()),
    }
    data = SplashData(
        root=root,
        basins=basins,
        facilities=facilities,
        halls=halls,
        hall_archetypes=arche,
        calendar=cal,
        weather=weather,
        curtailment=curtailment,
        occupancy=occ,
        bands=bands,
        network_water=net,
        outdoor_params=out_p,
        indoor_params=in_p,
        coordinator=coord,
        synthetic_flags=flags,
        heat_sources=hs,
        facility_heat_sources=fhs,
        dhw_facility=dhw,
    )
    data.provenance = build_provenance(root, data, w, cur)
    validate_data(data)
    return data


def _flag(df: pd.DataFrame, col: str) -> bool:
    if col not in df.columns:
        return True
    vals = pd.to_numeric(df[col], errors="coerce")
    return bool(vals.isna().any() or (vals != 0).any())


def _weather_is_synthetic(w: pd.DataFrame) -> bool:
    if "source" not in w.columns:
        return True
    src = w["source"].astype(str).str.strip()
    known = src.str.upper().apply(lambda x: any(x == r or x.startswith(r) for r in REAL_WEATHER_SOURCES))
    return bool((~known).any() or src.str.contains("synthetic", case=False).any())


def build_provenance(root: Path, d: SplashData, w: pd.DataFrame, cur: pd.DataFrame) -> pd.DataFrame:
    meta = {}
    pp = root / "PROVENANCE.csv"
    if pp.exists():
        pm = pd.read_csv(pp)
        meta = {str(r["item"]): r for _, r in pm.iterrows()}
    rows = []

    def add(item, synthetic, basis, assumed=False, note=""):
        m = meta.get(item)
        year = "" if m is None else str(m.get("year", "") if pd.notna(m.get("year", "")) else "")
        src = "" if m is None else str(m.get("source", "") if pd.notna(m.get("source", "")) else "")
        status = "synthetic" if synthetic else ("assumed" if assumed else "real")
        rows.append({"item": item, "status": status, "basis": basis, "source": src, "year": year, "note": note})

    wsrc = ", ".join(sorted(set(w["source"].astype(str)))) if "source" in w.columns else "unknown"
    add("weather", d.synthetic_flags["weather"], wsrc)
    add("curtailment", d.synthetic_flags["curtailment"], "is_synthetic column of curtailment_signal.csv")
    add("occupancy", d.synthetic_flags["occupancy"], "is_synthetic column of occupancy_profiles.csv")
    add("hall_geometry", d.synthetic_flags["hall_geometry"], "is_synthetic column of hall_geometry.csv")
    add("heat_sources", d.synthetic_flags["heat_sources"], "prices, capex and efficiencies of config/heat_sources.csv")
    add("facility_heat_sources", d.synthetic_flags["facility_heat_sources"], "heat sources per facility")
    if d.dhw_facility is not None:
        add("dhw_facility", d.synthetic_flags["dhw_facility"], "per facility visitors, shower water, hot share and buffer tank (inputs/dhw_facility.csv)")
    for item in ("bands", "hall_archetypes", "heat pump COP", "indoor and outdoor model parameters", "network water temperature"):
        add(item, False, "engineering assumption, see SYNTHETIC_DATA_REGISTER.csv", assumed=True)
    prov = pd.DataFrame(rows)
    tmy = any(m in wsrc.upper() for m in TMY_MARKERS)
    if tmy and not d.synthetic_flags["curtailment"]:
        prov.loc[prov["item"] == "weather", "note"] = (
            "TMY: typical year composed of months from different historical years. Not the year of the curtailment series, so wind, heating "
            "demand and curtailment are not coincident. Use same year weather for coincident analyses."
        )
        log.warning("weather is a TMY and curtailment is a real series of one year: the two do not coincide in time")
    cy = meta.get("curtailment")
    undocumented = (
        cy is None
        or pd.isna(cy.get("year", np.nan))
        or str(cy.get("year", "")).strip() == ""
        or str(cy.get("year", "")).upper().startswith("TO BE FILLED")
    )
    if not d.synthetic_flags["curtailment"] and undocumented:
        prov.loc[prov["item"] == "curtailment", "note"] = "source year of the real curtailment series is not documented (PROVENANCE.csv)"
        log.warning("source year of the curtailment series is not documented in PROVENANCE.csv")
    return prov


def validate_data(d: SplashData) -> None:
    errors: list[str] = []
    cal_idx = d.calendar["hour_of_year"].to_numpy()
    if len(cal_idx) != HOURS_PER_YEAR or not np.array_equal(cal_idx, np.arange(1, HOURS_PER_YEAR + 1)):
        errors.append("calendar must hold hour_of_year 1..8760")
    for z, w in d.weather.items():
        if len(w) != HOURS_PER_YEAR:
            errors.append(f"weather zone {z} has {len(w)} rows, expected {HOURS_PER_YEAR}")
        for col in ("T2m_c", "RH_pct", "G_h_wm2", "WS10m_ms", "SP_pa"):
            if w[col].isna().any():
                errors.append(f"weather zone {z} column {col} has missing values")
        if ((w["RH_pct"] < 0) | (w["RH_pct"] > 100)).any():
            errors.append(f"weather zone {z} has RH outside 0 to 100")
        if (w["G_h_wm2"] < 0).any():
            errors.append(f"weather zone {z} has negative irradiance")
    if len(d.curtailment) != HOURS_PER_YEAR:
        errors.append("curtailment must hold 8760 hours per zone")
    if (d.curtailment < 0).any().any():
        errors.append("curtailment has negative values")
    active = d.basins[d.basins["model_status"] == "ok"]
    missing_w = set(active["weather_zone_id"]) - set(d.weather)
    missing_c = set(active["curtail_zone_id"]) - set(d.curtailment.columns)
    if missing_w:
        errors.append(f"weather missing for zones {sorted(missing_w)}")
    if missing_c:
        errors.append(f"curtailment missing for zones {sorted(missing_c)}")
    keys_needed = set(active["typology_key"])
    keys_have = set(d.occupancy["typology_key"])
    if keys_needed - keys_have:
        errors.append(f"occupancy profile missing for {sorted(keys_needed - keys_have)}")
    bad = d.basins[d.basins["model_status"] != "ok"]
    if len(bad):
        log.warning("%d basins have model_status other than ok and are skipped", len(bad))
    if d.heat_sources is not None:
        hs = d.heat_sources
        if hs["source_id"].duplicated().any():
            errors.append("heat_sources: duplicate source_id")
        if (hs["price_eur_per_mwh_input"] < 0).any() or (hs["conversion_efficiency"] <= 0).any():
            errors.append("heat_sources: prices must be >= 0 and efficiencies > 0")
        need_cols = {
            "row_role",
            "needs_installation",
            "capex",
            "capex_unit",
            "fixed_om",
            "fixed_om_unit",
            "variable_om_eur_per_mwh_th",
            "lifetime_years",
        }
        if need_cols - set(hs.columns):
            errors.append(f"heat_sources: missing columns {sorted(need_cols - set(hs.columns))}")
        else:
            if not set(hs["needs_installation"]) <= {0, 1}:
                errors.append("heat_sources: needs_installation must be 0 or 1")
            if (hs["lifetime_years"] <= 0).any() or (hs["capex"] < 0).any() or (hs["fixed_om"] < 0).any():
                errors.append("heat_sources: lifetime must be positive, capex and fixed_om not negative")
            for sid in ("heat_pump_plant", "electric_boiler_plant", "flex_controller"):
                if sid not in set(hs["source_id"]):
                    errors.append(f"heat_sources must contain {sid}")
        for sid in ("grid_electricity", "curtailed_electricity"):
            if sid not in set(hs["source_id"]):
                errors.append(f"heat_sources must contain {sid}")
        if d.facility_heat_sources is not None:
            f = d.facility_heat_sources
            unknown = set(f["source_id"]) - set(hs["source_id"])
            if unknown:
                errors.append(f"facility_heat_sources: unknown source_id {sorted(unknown)}")
            tot = f.groupby("facility_id")["share_of_heat"].sum()
            if ((tot - 1.0).abs() > 1e-3).any():
                errors.append(f"facility_heat_sources: shares must sum to 1, facilities {sorted(tot[(tot - 1.0).abs() > 1e-3].index)[:5]}")
            miss = set(d.facilities["facility_id"]) - set(f["facility_id"])
            if miss:
                errors.append(f"facility_heat_sources: no heat source for {len(miss)} facilities")
    if d.dhw_facility is not None:
        g = d.dhw_facility
        need_cols = {"facility_id", "annual_visitors", "shower_water_m3_per_visitor", "hot_shower_share", "dhw_tank_m3", "is_synthetic"}
        if need_cols - set(g.columns):
            errors.append(f"dhw_facility: missing columns {sorted(need_cols - set(g.columns))}")
        else:
            if g["facility_id"].duplicated().any():
                errors.append("dhw_facility: duplicate facility_id")
            unknown = set(g["facility_id"]) - set(d.facilities["facility_id"])
            if unknown:
                errors.append(f"dhw_facility: unknown facility_id {sorted(unknown)[:5]}")
            for col in ("annual_visitors", "shower_water_m3_per_visitor", "hot_shower_share", "dhw_tank_m3"):
                v = pd.to_numeric(g[col], errors="coerce")
                if (g[col].notna() & v.isna()).any():
                    errors.append(f"dhw_facility: {col} must be numeric or blank")
                if (v < 0).any():
                    errors.append(f"dhw_facility: {col} must not be negative")
            hs_ = pd.to_numeric(g["hot_shower_share"], errors="coerce")
            if (hs_ > 1).any():
                errors.append("dhw_facility: hot_shower_share must be between 0 and 1")
    if errors:
        raise DataError("data validation failed:\n  - " + "\n  - ".join(errors))
    for name, flag in d.synthetic_flags.items():
        if flag:
            log.warning("INPUT '%s' IS SYNTHETIC: results are for method development only", name)
